"""Inter-account transfer matching and account identity (D-007, D-028c/e).

A transfer is the same money seen twice: a debit on one account and the
matching credit on another.  Both legs reconcile against their own statement,
so a wrong pairing is invisible to the reconciliation gate (D-004) — hence
ambiguity is always escalated, never resolved by guessing.
"""
import hashlib
from datetime import date, datetime

DEFAULT_DAY_WINDOW = 5


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
    d_a, d_b = _as_date(_field(a, "posting_date")), _as_date(_field(b, "posting_date"))
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
