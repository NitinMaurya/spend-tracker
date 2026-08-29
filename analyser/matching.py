"""Inter-account transfer matching and account identity (D-007, D-028c/e).

A transfer is the same money seen twice: a debit on one account and the
matching credit on another.  Both legs reconcile against their own statement,
so a wrong pairing is invisible to the reconciliation gate (D-004) — hence
ambiguity is always escalated, never resolved by guessing.
"""
import hashlib
from datetime import date, datetime

DEFAULT_DAY_WINDOW = 5

# Types that can never be one leg of an internal transfer. Earnings arrive from
# outside and have no matching debit; fees and interest are charges with no
# counterpart; a refund comes from a merchant, not from another of your accounts.
# Without this guard a salary and an unrelated same-sized outgoing on the same
# day would pair and cancel, erasing the month's income.
UNPAIRABLE = frozenset({"SALARY", "INCOME", "REFUND", "FEE", "INTEREST"})


def _as_date(value):
    """Accept ISO strings, `date` and `datetime`; anything else is unusable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _field(txn, name):
    if isinstance(txn, dict):
        return txn.get(name)
    return getattr(txn, name, None)


def _is_candidate(a, b, day_window):
    """D-028c: opposite signs, different accounts, exact amount, +/- window."""
    amt_a, amt_b = _field(a, "amount_minor"), _field(b, "amount_minor")
    if amt_a is None or amt_b is None or amt_a == 0 or amt_b == 0:
        return False
    if (amt_a > 0) == (amt_b > 0):
        return False
    if amt_a != -amt_b:  # exact magnitude, integer minor units only
        return False
    if _field(a, "account_id") == _field(b, "account_id"):
        return False
    # Never pair a leg whose meaning is already settled by the statement. A
    # salary has no matching debit anywhere, and a fee has no counterpart at all,
    # so a same-amount coincidence must not be allowed to swallow either.
    if _field(a, "txn_type") in UNPAIRABLE or _field(b, "txn_type") in UNPAIRABLE:
        return False
    # Posting date is the right key -- it is when the money actually moved -- but
    # not every statement prints one, and falling back keeps a whole account from
    # dropping out of matching over a missing column.
    d_a = _as_date(_field(a, "posting_date")) or _as_date(_field(a, "txn_date"))
    d_b = _as_date(_field(b, "posting_date")) or _as_date(_field(b, "txn_date"))
    if d_a is None or d_b is None:
        return False
    return abs((d_a - d_b).days) <= day_window


def transfer_group_id(txn_ids) -> str:
    """Deterministic id so re-matching the same legs is a no-op."""
    key = "|".join(sorted(str(t) for t in txn_ids))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def match_transfers(txns, *, day_window=DEFAULT_DAY_WINDOW):
    """Pair inter-account transfer legs.

    Returns a list of groups: ``{"txn_ids": [...], "transfer_group_id": ...,
    "needs_review": bool}``.  A leg with more than one candidate is never
    auto-matched — the whole candidate cluster is returned for review.
    """
    txns = list(txns)
    candidates = {}
    for i, a in enumerate(txns):
        for j in range(i + 1, len(txns)):
            b = txns[j]
            if _is_candidate(a, b, day_window):
                candidates.setdefault(i, set()).add(j)
                candidates.setdefault(j, set()).add(i)

    groups = []
    consumed = set()
    for i in sorted(candidates):
        if i in consumed:
            continue
        peers = candidates[i]
        if len(peers) == 1:
            (j,) = tuple(peers)
            if len(candidates[j]) == 1:
                consumed.update({i, j})
                groups.append(_group([txns[i], txns[j]], needs_review=False))
                continue
        # Ambiguous: this leg (or its only peer) has competing candidates.
        cluster = {i} | peers
        for j in peers:
            cluster |= candidates[j]
        cluster -= consumed
        if not cluster:
            continue
        consumed |= cluster
        groups.append(_group([txns[k] for k in sorted(cluster)], needs_review=True))

    return groups


def _group(legs, *, needs_review):
    txn_ids = [_field(t, "txn_id") for t in legs]
    group = {"txn_ids": txn_ids, "transfer_group_id": transfer_group_id(txn_ids)}
    if needs_review:
        group["needs_review"] = True
    return group


def resolve_account(masked_number, aliases):
    """D-028e: a masked PAN is an alias, not identity.

    A reissued card adds an alias pointing at the same `account_id`; an
    unknown PAN returns None so ingestion can ask rather than invent one.
    """
    if not masked_number or not aliases:
        return None
    key = " ".join(str(masked_number).split())
    return aliases.get(key) or aliases.get(masked_number)


def link_transfers(conn, *, day_window=DEFAULT_DAY_WINDOW, apply=False):
    """Find and record internal transfers across every account in the database.

    The same money seen twice -- a card paid from a current account, a loan
    landing in a bank account -- is two rows that each reconcile perfectly
    against their own statement. Nothing about either row is wrong; the error
    only appears when they are added together, which is exactly what a
    consolidated ledger does. Left unlinked, every internal movement is counted
    on both sides: money out AND money in.

    Only UNAMBIGUOUS pairs are written. Where several legs compete for the same
    counterpart, the cluster is reported and left alone -- a wrong pairing is
    invisible to the reconciliation gate (D-004), so it must never be guessed at.

    Returns ``{"linked": [...], "ambiguous": [...], "written": int}``.
    """
    # Built positionally rather than with dict(row): whether rows arrive as
    # tuples or as sqlite3.Row is the CALLER's setting, and this has to work the
    # same when ingest calls it as when the CLI does.
    cols = ("txn_id", "account_id", "txn_date", "posting_date", "amount_minor", "txn_type")
    rows = [dict(zip(cols, r)) for r in conn.execute(
        "SELECT t.txn_id, t.account_id, t.txn_date, t.posting_date, t.amount_minor,"
        "       COALESCE(t.user_txn_type, t.system_txn_type)"
        "  FROM transactions t"
        " WHERE t.excluded = 0 AND t.transfer_group_id IS NULL"
        " ORDER BY t.txn_id")]

    groups = match_transfers(rows, day_window=day_window)
    linked = [g for g in groups if not g.get("needs_review")]
    ambiguous = [g for g in groups if g.get("needs_review")]

    written = 0
    if apply and linked:
        for g in linked:
            conn.executemany(
                "UPDATE transactions SET transfer_group_id = ?"
                " WHERE txn_id = ? AND transfer_group_id IS NULL",
                [(g["transfer_group_id"], t) for t in g["txn_ids"]])
            written += len(g["txn_ids"])
        conn.commit()

    return {"linked": linked, "ambiguous": ambiguous, "written": written}
