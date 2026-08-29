"""Command-line surface (D-028f).

    analyse ingest <path|dir>     parse, reconcile, store  (idempotent)
    analyse review                the correction queue
    analyse rules <card>          extracted rules + provenance + conflicts
    analyse plan                  the routing plan  (primary output, D-027)
    analyse value <card>          net value, break-even, sensitivity
    analyse forget <doc|account>  delete, with cascade

Invoked as ``python -m analyser <command>``.

Two rules govern every line of output here:

* **Money is printed through `fmt_money`, never formatted inline.** The exponent
  travels with the currency (D-020a); dividing by 100 is correct for AED and
  silently wrong for KWD (3) and JPY (0). The schema stores a currency code per
  row but no exponent column, so the exponent is resolved from the ISO 4217
  table below at print time -- see the module note in `exponent_for`.
* **No financial value ever reaches a log record** (D-028i). Logging carries
  counts, ids and statuses; amounts go to stdout only.

Corrections are made by editing the map files, never through interactive
prompts (D-001), so no command here reads from stdin.
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sqlite3
import sys
from collections import Counter
from decimal import Decimal

from analyser import db

LOG = logging.getLogger("analyser.cli")

#: Wallet definition: the confirmed card rules used by `plan` and `value`.
#: Extracted rules require human confirmation before they may be used in any
#: calculation (D-022 / D-028h.4), and this file *is* that confirmation step.
DEFAULT_WALLET_PATH = os.path.join(db.PROJECT_ROOT, "data", "wallet.json")
#: Where `rules` looks for KFS / T&C documents.
DEFAULT_TERMS_DIR = os.path.join(db.PROJECT_ROOT, "sample_kfs")

_PARSER_ISSUERS = {
    "fab": "FAB",
    "mashreq": "MASHREQ",
    "cbd": "CBD",
    "emirates_islamic": "EMIRATES_ISLAMIC",
    "wio": "WIO",
}
#: Wio-style facilities settle other cards; their outflows are not spending.
_SETTLEMENT_PARSERS = ("wio",)


# ---------------------------------------------------------------------------
# money printing (D-020a)
# ---------------------------------------------------------------------------

#: ISO 4217 minor-unit exponents that are NOT 2. Everything absent from this
#: table is a 2-exponent currency.
_EXPONENTS = {
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
    "JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "ISK": 0, "PYG": 0, "RWF": 0,
    "UGX": 0, "XAF": 0, "XOF": 0, "XPF": 0, "BIF": 0, "DJF": 0, "GNF": 0,
    "KMF": 0, "VUV": 0,
}


def exponent_for(currency):
    """Minor-unit exponent for an ISO 4217 code.

    D-020a wants the exponent stored *with the row* so an ISO revision cannot
    retroactively change what a historical amount meant. The current schema
    (001_init.sql / 002_raw_extraction.sql) has a `currency` column but no
    `exponent` column, and migrations are not mine to edit, so the CLI resolves
    it from the code here. The lookup is confined to this one function: nothing
    else in the CLI knows a scale factor, and no division by 100 appears
    anywhere. Raised as a disagreement rather than papered over.
    """
    return _EXPONENTS.get(str(currency or "AED").upper(), 2)


def fmt_money(minor, currency="AED", exponent=None):
    """Format integer minor units for display. Never floats, never /100."""
    if minor is None:
        return "—"
    exp = exponent_for(currency) if exponent is None else int(exponent)
    value = Decimal(int(minor)).scaleb(-exp)
    return f"{currency} {value:,.{exp}f}"


def fmt_amount(money):
    """Format a domain `Money` (which carries its own stored exponent)."""
    if money is None:
        return "—"
    return fmt_money(money.minor, money.currency, money.exponent)


# ---------------------------------------------------------------------------
# small output helpers
# ---------------------------------------------------------------------------

def out(text=""):
    print(text, file=sys.stdout)


def heading(text):
    out()
    out(text)
    out("─" * len(text))


def _rows(conn, sql, params=()):
    cursor = conn.execute(sql, params)
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _table_exists(conn, table):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


# ---------------------------------------------------------------------------
# shared plumbing
# ---------------------------------------------------------------------------

def open_db(args):
    conn = db.connect(args.db)
    db.migrate(conn)
    return conn


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def _pdf_targets(path):
    path = os.path.abspath(str(path))
    if os.path.isdir(path):
        return sorted(glob.glob(os.path.join(path, "*.pdf")) +
                      glob.glob(os.path.join(path, "*.PDF")))
    return [path]


def _slug(text):
    keep = [c.lower() if c.isalnum() else "-" for c in str(text or "")]
    return "-".join(part for part in "".join(keep).split("-") if part)


def _derive_account(path, parser_name):
    """(account_id, product_name, masked_number, currency) for a statement.

    The account slug is stable across months and survives reissue (D-028e): it
    is issuer + the last group of the masked PAN, not anything file-derived.
    Falls back to the issuer alone when the parser prints no masked number.
    """
    from analyser.parsers import get_parser

    from analyser.pdfaccess import readable

    issuer = _PARSER_ISSUERS.get(parser_name, parser_name.upper())
    product = masked = None
    account_type = None
    try:
        # MUST decrypt first. Probing the raw path on a password-protected statement
        # throws, the PAN comes back empty, and the slug silently degrades to the bare
        # issuer -- which created a SECOND account ("fab" alongside "fab-0000") for the
        # same card and split its history in two.
        with readable(path) as usable:
            result = get_parser(parser_name).parse(usable)
        header = result[0] or {}
        product = header.get("product_name")
        masked = header.get("masked_number") or header.get("card_number")
        account_type = header.get("account_type")
    except Exception as exc:                       # parsing is ingest's job to report
        LOG.debug("header probe failed for %s: %s", os.path.basename(path), exc)

    # The LAST FOUR DIGITS, whatever the printed format. Taking the last
    # space-separated group only worked for issuers that space their PANs:
    # "4XXX XX** **** NNNN" gave 1902, but CBD's "4XXXXX******0000" and Dubai
    # First's "524204XXXXXX7264" have no spaces at all, so the tail came back
    # empty and every one of that bank's statements collapsed onto a single
    # issuer-level account.
    tail = ""
    if masked:
        digits = "".join(ch for ch in str(masked) if ch.isdigit())
        if len(digits) >= 4:
            tail = digits[-4:]
    slug = _slug(issuer) + (f"-{tail}" if tail else "")
    return slug, product, masked, "AED", account_type


def _resolve_alias(conn, account_id, *, issuer, masked, account_type):
    """Map an UNIDENTIFIED statement onto an existing account (D-028e).

    The only safe automatic merge is when a document yields NO identifier at all --
    the parser could not read a PAN or account number, so the slug degraded to the
    bare issuer. In that case, if the issuer has exactly one account of this type,
    the statement almost certainly belongs to it.

    Two different identifiers are NEVER merged automatically. An earlier version did,
    and merged Emirates NBD's savings account (…6901) into its current account
    (…6902) -- two genuinely separate accounts. A person can hold several accounts,
    and several cards, at one bank; guessing they are the same corrupts every total
    derived from them.

    A bank that identifies one card two ways (CBD prints a PAN on one statement and
    an account number on another) therefore still produces two accounts. That is
    visible and correctable, which is better than a silent wrong merge.
    """
    from datetime import datetime, timezone

    existing = conn.execute("SELECT account_id FROM account_aliases WHERE alias=?",
                            (account_id,)).fetchone()
    if existing:
        return existing[0]

    if conn.execute("SELECT 1 FROM accounts WHERE account_id=?", (account_id,)).fetchone():
        return account_id

    # Only the no-identifier case qualifies: the slug is the bare issuer slug.
    if account_id != _slug(issuer):
        return account_id

    kind = account_type or "CREDIT_CARD"
    siblings = [r[0] for r in conn.execute(
        "SELECT account_id FROM accounts WHERE issuer=? AND account_type=?",
        (issuer, kind))]
    if len(siblings) != 1:
        return account_id

    target = siblings[0]
    conn.execute(
        "INSERT OR IGNORE INTO account_aliases (alias,account_id,source,linked_at,link_kind)"
        " VALUES (?,?,?,?,'AUTO')",
        (account_id, target, str(masked or ""),
         datetime.now(timezone.utc).isoformat()))
    conn.commit()
    LOG.info("linked unidentified %s -> %s", account_id, target)
    return target


def _ensure_account(conn, account_id, *, issuer, product, masked, currency,
                    parser_name, account_type=None):
    account_id = _resolve_alias(conn, account_id, issuer=issuer, masked=masked,
                                account_type=account_type)
    row = conn.execute(
        "SELECT account_id FROM accounts WHERE account_id=?", (account_id,)
    ).fetchone()
    if row:
        # D-028e: a reissue adds an alias, it never creates a second account.
        if masked:
            conn.execute(
                "UPDATE accounts SET masked_number=COALESCE(masked_number,?) "
                "WHERE account_id=?", (masked, account_id))
            conn.commit()
        return account_id
    # A parser may declare the document is a deposit account rather than a card
    # (Emirates NBD mails both from one address). Deposit accounts are excluded from
    # spending -- a salary credit is not a purchase.
    if account_type is None:
        account_type = "BANK" if parser_name in _SETTLEMENT_PARSERS else "CREDIT_CARD"
    include = 0 if account_type == "BANK" or parser_name in _SETTLEMENT_PARSERS else 1
    conn.execute(
        "INSERT INTO accounts (account_id,issuer,product_name,account_type,"
        "currency,masked_number,include_in_spending,notes) VALUES (?,?,?,?,?,?,?,?)",
        (account_id, issuer, product, account_type, currency, masked, include,
         "created by `analyse ingest`"),
    )
    conn.commit()
    LOG.info("created account %s (%s)", account_id, issuer)
    return account_id
    return True


def cmd_ingest(args):
    from analyser.ingest import ingest_document
    from analyser.parsers import DocumentEncrypted, detect_parser

    targets = _pdf_targets(args.path)
    if not targets:
        out(f"nothing to ingest: no PDF found at {args.path}")
        return 1

    # D-028j: snapshot before every ingest, keep the last 10.
    if not args.no_snapshot and os.path.exists(args.db):
        dest = db.snapshot(args.db)
        LOG.info("snapshot -> %s", os.path.basename(dest))
        out(f"snapshot  {dest}")

    conn = open_db(args)
    failures = 0

    for path in targets:
        name = os.path.basename(path)
        try:
            parser_name = detect_parser(path)
        except DocumentEncrypted:
            failures += 1
            LOG.warning("encrypted document refused: %s", name)
            out(f"ENCRYPTED {name}")
            out("          This PDF needs a user password. Add it to the macOS "
                "Keychain, e.g.")
            out(f'          security add-generic-password -a "$USER" '
                f'-s "credit-analyser:{name}" -w')
            out("          then re-run ingest. The password is never typed at "
                "this prompt and never echoed.")
            continue

        if parser_name is None:
            failures += 1
            LOG.warning("no parser recognises %s", name)
            out(f"SKIPPED   {name} — no parser recognises this issuer")
            continue

        account_id = args.account
        issuer = _PARSER_ISSUERS.get(parser_name, parser_name.upper())
        derived_id, product, masked, currency, acct_type = _derive_account(path, parser_name)
        account_id = account_id or derived_id
        account_id = _ensure_account(conn, account_id, issuer=issuer, product=product,
                                     masked=masked, currency=currency,
                                     parser_name=parser_name, account_type=acct_type)

        try:
            result = ingest_document(path, conn=conn, account_id=account_id)
        except Exception as exc:
            failures += 1
            LOG.error("ingest failed for %s: %s", name, type(exc).__name__)
            out(f"FAILED    {name} — {type(exc).__name__}: {exc}")
            continue

        LOG.info("ingested %s status=%s txns=%s", name, result["status"],
                 result.get("transactions"))
        if not result["inserted"]:
            out(f"UNCHANGED {name} — {result['reason']} "
                f"[{result['document_id'][:12]}]")
            continue

        coverage = result.get("coverage") or {}
        out(f"{result['status']:<9} {name}  [{result['document_id'][:12]}]")
        out(f"          parser={result['parser_name']} pages={result['pages']} "
            f"lines={result['lines']} raw_txns={result['transactions_raw']} "
            f"stored={result['transactions']} rewards={result['rewards']}")
        out(f"          unparsed={coverage.get('unparsed_lines')}/"
            f"{coverage.get('considered_lines')} "
            f"({coverage.get('unparsed_pct')}%) account={account_id}")
        if not result["reconciled"]:
            failures += 1
            out(f"          NOT STORED (D-004): {result['reject_reason']}")
            out("          Raw evidence is kept; the rows do not enter analysis "
                "until the statement closes.")

    # Linking runs on every ingest, not as a chore the user has to remember.
    # A new statement is precisely what completes a pair whose other leg was
    # already on file, and until both legs are linked the ledger counts the same
    # money twice -- once leaving one account and once arriving in another.
    # Ambiguous clusters are reported, never resolved.
    from analyser.matching import link_transfers
    links = link_transfers(conn, apply=True)
    if links["written"]:
        out(f"linked    {links['written']} transfer leg(s) into "
            f"{len(links['linked'])} group(s)")
    if links["ambiguous"]:
        out(f"          {len(links['ambiguous'])} ambiguous cluster(s) left "
            f"unlinked — run `link-transfers` to see them")

    conn.close()
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------

_REVIEW_CONFIDENCE = ("LOW", "UNKNOWN")


def cmd_review(args):
    conn = open_db(args)
    items = 0

    rejected = _rows(conn,
        "SELECT document_id, file_name, account_id, reject_reason FROM documents "
        "WHERE status='REJECTED' ORDER BY ingested_at")
    if rejected:
        items += len(rejected)
        heading(f"Statements that did not reconcile ({len(rejected)}) — D-004")
        for row in rejected:
            out(f"  {row['file_name']}  [{row['document_id'][:12]}]  "
                f"{row['account_id']}")
            out(f"      {row['reject_reason']}")

    uncategorized = _rows(conn,
        "SELECT txn_id, account_id, txn_date, merchant, category, confidence, "
        "amount_minor, currency FROM v_spend "
        "WHERE category IS NULL OR confidence IN (?,?) "
        "ORDER BY txn_date, txn_id LIMIT ?",
        _REVIEW_CONFIDENCE + (args.limit,))
    total = conn.execute(
        "SELECT COUNT(*) FROM v_spend WHERE category IS NULL OR confidence IN (?,?)",
        _REVIEW_CONFIDENCE).fetchone()[0]
    if total:
        items += total
        heading(f"Uncategorized / low-confidence transactions ({total})")
        out("  Correct these by editing merchant_map.csv / category_overrides.csv "
            "(D-001).")
        out()
        out(f"  {'date':<11} {'account':<14} {'merchant':<28} "
            f"{'category':<14} {'conf':<8} amount")
        for row in uncategorized:
            out(f"  {row['txn_date']:<11} {row['account_id']:<14} "
                f"{(row['merchant'] or row['txn_id'][:8])[:28]:<28} "
                f"{(row['category'] or '—')[:14]:<14} "
                f"{(row['confidence'] or 'UNKNOWN'):<8} "
                f"{fmt_money(row['amount_minor'], row['currency'])}")
        if total > len(uncategorized):
            out(f"  … {total - len(uncategorized)} more (use --limit)")

    if _table_exists(conn, "document_lines"):
        unparsed = _rows(conn,
            "SELECT d.file_name, l.page_number, l.line_index, l.raw_text "
            "FROM document_lines l JOIN documents d USING (document_id) "
            "WHERE l.disposition='UNPARSED' ORDER BY d.file_name, l.page_number, "
            "l.line_index LIMIT ?", (args.limit,))
        unparsed_total = conn.execute(
            "SELECT COUNT(*) FROM document_lines WHERE disposition='UNPARSED'"
        ).fetchone()[0]
        if unparsed_total:
            items += unparsed_total
            heading(f"Lines a parser did not understand ({unparsed_total}) — D-018")
            for row in unparsed:
                text = " ".join(row["raw_text"].split())[:90]
                out(f"  {row['file_name']} p{row['page_number']}"
                    f":{row['line_index']:<4} {text}")
            if unparsed_total > len(unparsed):
                out(f"  … {unparsed_total - len(unparsed)} more (use --limit)")

    flagged = _rows(conn,
        "SELECT transfer_group_id, COUNT(*) AS legs FROM transactions "
        "WHERE transfer_group_id LIKE 'REVIEW%' GROUP BY transfer_group_id")
    if flagged:
        items += len(flagged)
        heading(f"Transfer groups needing review ({len(flagged)}) — D-028c")
        for row in flagged:
            out(f"  {row['transfer_group_id']}  legs={row['legs']}")

    if not items:
        heading("Correction queue")
        out("  Empty — nothing is waiting on you.")
    conn.close()
    return 0


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def _terms_documents(terms_dir):
    return sorted(glob.glob(os.path.join(terms_dir, "*.pdf")) +
                  glob.glob(os.path.join(terms_dir, "*.PDF")))


def _extract_document_text(path):
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _document_text(path):
    """Extracted text, cached on disk by file size + mtime (see analyser/textcache)."""
    from analyser.textcache import cached_text

    return cached_text(path, _extract_document_text)


def _source_kind(file_name):
    low = file_name.lower()
    if "kfs" in low:
        return "KFS"
    if "terms" in low or "t&c" in low or "tc" in low:
        return "TC"
    return "PRODUCT_PAGE"


def cmd_rules(args):
    from analyser import rules as rules_mod
    from analyser.parsers import DocumentEncrypted

    documents = _terms_documents(args.terms_dir)
    if not documents:
        out(f"no terms documents found in {args.terms_dir}")
        return 1

    found = []
    for path in documents:
        name = os.path.basename(path)
        try:
            text = _document_text(path)
        except DocumentEncrypted:
            out(f"ENCRYPTED {name} — add the password to the macOS Keychain, "
                "then re-run.")
            continue
        except Exception as exc:
            LOG.warning("unreadable terms document %s: %s", name, type(exc).__name__)
            continue
        extracted = rules_mod.extract_rules(text, card_name=args.card)
        if extracted is None:
            continue
        found.append({"source": _source_kind(name), "file": name,
                      "text": text, "facts": extracted})

    if not found:
        heading(f"Rules for {args.card}")
        out(f"  No document in {args.terms_dir} names this card.")
        out("  A card's rules are never inferred from a neighbouring product "
            "(D-022).")
        return 1

    merged = rules_mod.merge_sources(found)
    provenance = merged.get("provenance") or {}

    heading(f"Rules for {args.card}")
    out(f"  sources: " + ", ".join(f"{d['source']} ({d['file']})" for d in found))
    out("  precedence: KFS > T&C > product page > third party (D-022)")

    heading("Reward tiers")
    if merged["tiers"]:
        for tier in merged["tiers"]:
            cap = tier.get("cap_per_cycle")
            cap_text = ("" if cap is None
                        else f"  cap/cycle {fmt_money(cap, args.currency)}")
            out(f"  {tier['rate_bps'] / 100:.2f}%  {tier['category']}{cap_text}")
            out(f"      source={tier.get('source')}  \"{tier.get('source_quote', '')[:100]}\"")
    else:
        out("  none stated in the documents on file")

    heading("Facts")
    for key in sorted(k for k in merged
                      if k not in ("tiers", "exclusions", "sources", "provenance")):
        value = merged[key]
        if key.endswith("_minor"):
            shown = fmt_money(value, args.currency)
        elif value is None:
            shown = "UNKNOWN (not derivable from the documents — D-013)"
        else:
            shown = value
        out(f"  {key:<22} {shown}    [{provenance.get(key, '—')}]")

    heading(f"Exclusions ({len(merged['exclusions'])}) — D-025")
    for exclusion in merged["exclusions"]:
        out(f"  [{exclusion.get('detectability', 'DETECTABLE')}] "
            f"{exclusion['description'][:110]}")
        out(f"      source={exclusion.get('source')}")

    claims = []
    for document in found:
        facts = document["facts"]
        for key in ("fx_spread_bps", "retail_interest_bps", "expiry_months",
                    "annual_fee_minor"):
            if facts.get(key) is not None:
                claims.append({"rule": key, "value": facts[key],
                               "source": document["source"]})
        for tier in facts.get("tiers", []):
            claims.append({"rule": f"tier:{tier['category'].strip().lower()}",
                           "value": tier["rate_bps"], "source": document["source"]})
    conflicts = rules_mod.detect_conflicts(claims)

    heading(f"Conflicts ({len(conflicts)}) — D-023")
    if not conflicts:
        out("  none")
    for conflict in conflicts:
        out(f"  {conflict['rule']}: {', '.join(conflict['values'])} "
            f"from {', '.join(conflict['sources'])} — {conflict['resolution']}")
        out("      Not resolved by precedence: two authoritative documents "
            "disagreeing is yours to settle.")

    out()
    out("  Extracted rules require confirmation before they are used in any "
        "calculation (D-022).")
    out(f"  Confirm by writing them into {args.wallet}.")
    return 0


# ---------------------------------------------------------------------------
# wallet + transactions for the engine
# ---------------------------------------------------------------------------

class WalletError(Exception):
    """The wallet definition is missing or unusable."""


_WALLET_TEMPLATE = {
    "cards": [
        {
            "card_id": "yourbank-0000",
            "account_id": "yourbank-0000",
            "issuer": "YOURBANK",
            "currency": "AED",
            "annual_fee_minor": 0,
            "reward": {
                "unit": "AED",
                "cycle": {"anchor_day": 1, "key": "POSTING"},
                "rounding": {"mode": "HALF_UP", "unit": "MINOR", "scope": "CYCLE"},
                "tiers": [
                    {"categories": ["GROCERIES"], "rate_bps": 300,
                     "cap_per_cycle_minor": 10000},
                    {"categories": None, "rate_bps": 50},
                ],
            },
        }
    ],
    "routing": {"merchant_locked": [], "direct_debit": []},
}


def _money(minor, currency):
    from analyser.domain.model import Money

    if minor is None:
        return None
    return Money(int(minor), currency, exponent_for(currency))


def _build_card(spec):
    from analyser.domain.model import (Card, CycleSpec, Exclusion, RewardProgram,
                                       RewardTier, RoundingSpec)

    currency = spec.get("currency", "AED")
    reward = spec.get("reward") or {}
    tiers = []
    for tier in reward.get("tiers", []):
        categories = tier.get("categories")
        tiers.append(RewardTier(
            categories=None if categories is None else frozenset(categories),
            rate_bps=int(tier["rate_bps"]),
            cap_per_cycle=_money(tier.get("cap_per_cycle_minor"), currency),
            cap_per_year=_money(tier.get("cap_per_year_minor"), currency),
            priority=int(tier.get("priority", 0)),
            valid_from=tier.get("valid_from"),
            valid_to=tier.get("valid_to"),
        ))
    cycle = reward.get("cycle") or {}
    rounding = reward.get("rounding") or {}
    exclusions = tuple(
        Exclusion(label=e.get("label", ""),
                  categories=frozenset(e.get("categories") or ()),
                  txn_types=frozenset(e.get("txn_types") or ()),
                  channels=frozenset(e.get("channels") or ()),
                  detectability=e.get("detectability", "DETECTABLE"),
                  source_quote=e.get("source_quote", ""))
        for e in reward.get("exclusions", []))
    program = RewardProgram(
        tiers=tuple(tiers),
        cycle=CycleSpec(anchor_day=int(cycle.get("anchor_day", 1)),
                        key=cycle.get("key", "POSTING")),
        rounding=RoundingSpec(mode=rounding.get("mode", "HALF_UP"),
                              unit=rounding.get("unit", "MINOR"),
                              scope=rounding.get("scope", "CYCLE")),
        exclusions=exclusions,
        expiry_months=reward.get("expiry_months"),
        redemption_channel=reward.get("redemption_channel"),
        is_cash_equivalent=bool(reward.get("is_cash_equivalent", True)),
        unit=reward.get("unit", "AED"),
    )
    return Card(
        card_id=spec["card_id"],
        issuer=spec.get("issuer", ""),
        annual_fee=_money(spec.get("annual_fee_minor", 0), currency),
        reward=program,
        supplementary_fee=_money(spec.get("supplementary_fee_minor"), currency),
        fx_fee_bps=spec.get("fx_fee_bps"),
        financing_charge_bps=spec.get("financing_charge_bps"),
        charge_basis=spec.get("charge_basis", "INTEREST"),
        min_spend_per_cycle=_money(spec.get("min_spend_per_cycle_minor"), currency),
        has_unknowable_exclusion=bool(spec.get("has_unknowable_exclusion", False)),
    )


def load_wallet(path):
    """Read the confirmed card definitions. Returns (cards, spec_by_id, config)."""
    if not os.path.exists(path):
        raise WalletError(
            f"no wallet definition at {path}.\n"
            "  `plan` and `value` compare cards per category, which needs each "
            "card's confirmed rules (D-027).\n"
            "  Run `python -m analyser rules <card>` to see what the terms "
            "documents state, then write the\n"
            "  confirmed values into that file. A starting shape:\n\n"
            + json.dumps(_WALLET_TEMPLATE, indent=2))
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    specs = config.get("cards") or []
    if not specs:
        raise WalletError(f"{path} defines no cards.")
    cards, by_id = [], {}
    for spec in specs:
        card = _build_card(spec)
        cards.append(card)
        by_id[card.card_id] = spec
    return cards, by_id, config


def _routability(merchant, category, routing_config):
    from analyser.domain.model import Routability

    name = (merchant or "").upper()
    for needle in routing_config.get("merchant_locked") or ():
        if str(needle).upper() in name:
            return Routability.MERCHANT_LOCKED
    for needle in routing_config.get("direct_debit") or ():
        if str(needle).upper() in name:
            return Routability.DIRECT_DEBIT
    for needle in routing_config.get("acceptance_limited") or ():
        if str(needle).upper() in name:
            return Routability.ACCEPTANCE_LIMITED
    return Routability.ROUTABLE


def load_txns(conn, account_ids, *, account_to_card, routing_config,
              currency_default="AED"):
    """Read normalized rows into domain `Txn`s. Only reconciled data is here."""
    from analyser.domain.model import Money, Txn

    if not account_ids:
        return []
    marks = ",".join("?" * len(account_ids))
    rows = _rows(conn,
        f"SELECT txn_id, account_id, txn_date, posting_date, amount_minor, "
        f"currency, txn_type, merchant, category, confidence, excluded "
        f"FROM v_transactions WHERE account_id IN ({marks}) "
        f"ORDER BY txn_date, txn_id", tuple(account_ids))
    txns = []
    for row in rows:
        currency = row["currency"] or currency_default
        txns.append(Txn(
            txn_id=row["txn_id"],
            account_id=account_to_card.get(row["account_id"], row["account_id"]),
            txn_date=row["txn_date"],
            posting_date=row["posting_date"],
            amount=Money(int(row["amount_minor"]), currency, exponent_for(currency)),
            txn_type=row["txn_type"],
            category=row["category"],
            confidence=row["confidence"] or "UNKNOWN",
            routability=_routability(row["merchant"], row["category"],
                                     routing_config),
            merchant=row["merchant"],
            excluded=bool(row["excluded"]),
        ))
    return txns


def _horizon(args, txns):
    from analyser.domain.model import AnalysisHorizon

    if args.start:
        start = args.start
    elif txns:
        start = min(t.txn_date for t in txns)[:8] + "01"
    else:
        from datetime import date
        start = date.today().replace(day=1).isoformat()
    return AnalysisHorizon(start=start, months=args.months)


def _wallet_context(args, conn):
    cards, specs, config = load_wallet(args.wallet)
    account_to_card = {}
    for card in cards:
        account_id = specs[card.card_id].get("account_id", card.card_id)
        account_to_card[account_id] = card.card_id
    txns = load_txns(conn, sorted(account_to_card),
                     account_to_card=account_to_card,
                     routing_config=config.get("routing") or {})
    return cards, specs, account_to_card, txns


# ---------------------------------------------------------------------------
# plan (D-027) — the primary output
# ---------------------------------------------------------------------------

def cmd_plan(args):
    from analyser.domain.routing import route

    conn = open_db(args)
    try:
        cards, _specs, _accounts, txns = _wallet_context(args, conn)
    except WalletError as exc:
        out(str(exc))
        conn.close()
        return 1

    horizon = _horizon(args, txns)
    if not txns:
        out("no transactions on file for the wallet's accounts — run "
            "`ingest` first.")
        conn.close()
        return 1

    plan = route(txns, cards, horizon)

    heading(f"Routing plan — {horizon.months} months from {horizon.start}")
    out(f"  cards: {', '.join(c.card_id for c in cards)}")
    out(f"  transactions considered: {len(txns)}")
    out()
    out(f"  value if you change nothing : {fmt_amount(plan.value_unchanged)}")
    out(f"  value if you route as planned: {fmt_amount(plan.value_if_routed)}")
    out(f"  the plan is worth            : {fmt_amount(plan.annual_gain)}")

    heading(f"Changes ({len(plan.moves)}) — ranked by value per change")
    if not plan.moves:
        out("  Nothing worth moving. Every routable category is already on the "
            "card that pays most for it.")
    total = sum(m.annual_gain.minor for m in plan.moves) or 1
    running = 0
    headline = 0
    for index, move in enumerate(plan.moves, start=1):
        running += move.annual_gain.minor
        if headline == 0 and running * 100 >= total * 80:
            headline = index
        out(f"  {index}. move {move.category} from "
            f"{move.from_card or 'unassigned'} → {move.to_card}")
        out(f"     {fmt_amount(move.monthly_spend)}/month  "
            f"worth {fmt_amount(move.annual_gain)}/year")
    if headline and len(plan.moves) > headline:
        rest = sum(m.annual_gain.minor for m in plan.moves[headline:])
        currency = plan.annual_gain.currency
        out()
        out(f"  {headline} change(s) capture 80% of the benefit. The remaining "
            f"{len(plan.moves) - headline} are worth "
            f"{fmt_money(rest, currency, plan.annual_gain.exponent)}/year "
            f"combined.")
    out()
    out("  Only routable spend is planned: merchant-locked, direct-debit and "
        "acceptance-limited rows stay put (D-027.4).")
    conn.close()
    return 0


# ---------------------------------------------------------------------------
# value
# ---------------------------------------------------------------------------

def cmd_value(args):
    from analyser.domain.value import break_even_spend, net_value, sensitivity_bands

    conn = open_db(args)
    try:
        cards, _specs, _accounts, txns = _wallet_context(args, conn)
    except WalletError as exc:
        out(str(exc))
        conn.close()
        return 1

    card = next((c for c in cards if c.card_id == args.card), None)
    if card is None:
        out(f"unknown card '{args.card}'. The wallet defines: "
            f"{', '.join(c.card_id for c in cards)}")
        conn.close()
        return 1

    own = [t for t in txns if t.account_id == card.card_id]
    horizon = _horizon(args, own or txns)
    result = net_value(own, card, horizon)
    year_one = net_value(own, card, horizon, year_one=True)

    heading(f"Net value — {card.card_id} ({card.issuer})")
    out(f"  horizon: {horizon.months} months from {horizon.start}   "
        f"transactions: {len(own)}")
    out()
    out(f"  rewards              {fmt_amount(result.rewards)}")
    if result.perk_value is not None:
        out(f"  perks                {fmt_amount(result.perk_value)}")
    out(f"  annual fee           {fmt_amount(-result.annual_fee)}")
    if result.supplementary_fee is not None and result.supplementary_fee.minor:
        out(f"  supplementary fee    {fmt_amount(-result.supplementary_fee)}")
    if result.financing_cost is not None and result.financing_cost.minor:
        out(f"  financing charge     {fmt_amount(-result.financing_cost)}")
    out("  fx cost              " + ("UNKNOWN (D-013)" if result.fx_cost is None
                                     else fmt_amount(-result.fx_cost)))
    out(f"  net (steady state)   {fmt_amount(result.net)}")
    out(f"  net (year one)       {fmt_amount(year_one.net)}")

    mix = {}
    for txn in own:
        if txn.category and txn.amount.minor < 0:
            mix[txn.category] = mix.get(txn.category, 0) + abs(txn.amount.minor)
    total = sum(mix.values())
    share = {k: Decimal(v) / Decimal(total) for k, v in mix.items()} if total else {}

    heading("Break-even")
    if not share:
        out("  not computable: no categorised spend on this card yet.")
    else:
        break_even = break_even_spend(card, share)
        if break_even is None:
            out("  unreachable at any spend level — the caps bite before the fee "
                "is recovered.")
        else:
            out(f"  annual spend needed to reach zero: {fmt_amount(break_even)}")
            out("  at this card's observed category mix: "
                + ", ".join(f"{k} {v:.0%}" for k, v in
                            sorted(share.items(), key=lambda kv: -kv[1])))

    heading("Sensitivity bands (D-010)")
    conservative, expected, optimistic = sensitivity_bands(own, card, horizon)
    out(f"  conservative  {fmt_amount(conservative)}")
    out(f"  expected      {fmt_amount(expected)}")
    out(f"  optimistic    {fmt_amount(optimistic)}")
    out("  The spread is the uncertainty in the data, not a choice.")

    if result.assumptions:
        heading("Assumptions")
        for assumption in result.assumptions:
            out(f"  [{assumption.source}] {assumption.label}: {assumption.value}")
    if result.warnings:
        heading("Warnings")
        for warning in result.warnings:
            out(f"  {warning}")
    conn.close()
    return 0


# ---------------------------------------------------------------------------
# forget (D-028i)
# ---------------------------------------------------------------------------

def _resolve_documents(conn, target):
    rows = _rows(conn,
        "SELECT document_id, file_name, account_id FROM documents "
        "WHERE document_id=? OR document_id LIKE ? OR file_name=?",
        (target, target + "%", target))
    return rows


def cmd_reclassify(args):
    """Re-run transaction typing over stored rows, from the ORIGINAL statement text.

    Typing rules improve; already-ingested rows should not stay wrong just because
    they were read first. Re-parsing every PDF to get there would be wasteful and
    would risk changing amounts, so this reads `transactions_raw.raw_description`
    -- the verbatim line -- and rewrites only `system_txn_type`.

    A user correction always wins: `user_txn_type` is never touched, and rows
    carrying one are reported as held rather than silently left behind.
    """
    from analyser.normalize import classify_txn_type

    conn = db.connect(args.db)
    conn.row_factory = sqlite3.Row
    known_issuers = [r[0] for r in conn.execute(
        "SELECT DISTINCT issuer FROM accounts WHERE issuer IS NOT NULL")]
    rows = conn.execute(
        "SELECT t.txn_id, t.system_txn_type, t.user_txn_type, t.amount_minor,"
        "       t.account_id, a.issuer, a.account_type, r.raw_description"
        "  FROM transactions t"
        "  JOIN transactions_raw r ON r.raw_id = t.txn_id"
        "  JOIN accounts a ON a.account_id = t.account_id"
    ).fetchall()

    changes, held = [], 0
    for r in rows:
        if r["user_txn_type"]:
            held += 1
            continue
        fresh = classify_txn_type(r["raw_description"], r["amount_minor"],
                                  r["issuer"], r["account_type"], known_issuers)
        if fresh != r["system_txn_type"]:
            changes.append((fresh, r["system_txn_type"], r["txn_id"]))

    if not changes:
        print(f"{len(rows)} transactions, nothing to reclassify."
              + (f" {held} held by a user override." if held else ""))
        return 0

    moves = Counter((was, now) for now, was, _ in changes)
    for (was, now), n in sorted(moves.items(), key=lambda kv: -kv[1]):
        print(f"  {was:<16} -> {now:<16} {n:>5}")
    print(f"{len(changes)} of {len(rows)} transactions would be retyped."
          + (f" {held} held by a user override." if held else ""))

    if not args.yes:
        print("\nNothing was written. Re-run with --yes to apply.")
        return 0

    if not args.no_snapshot:
        snap = db.snapshot(args.db)
        print(f"snapshot: {snap}")
    conn.executemany(
        "UPDATE transactions SET system_txn_type = ? WHERE system_txn_type = ? AND txn_id = ?",
        changes)
    conn.commit()
    print(f"{len(changes)} transactions retyped.")
    return 0


def cmd_link_transfers(args):
    """Pair the two legs of every internal movement (D-007, D-028c)."""
    from analyser.matching import link_transfers

    conn = db.connect(args.db)
    conn.row_factory = sqlite3.Row
    result = link_transfers(conn, day_window=args.days, apply=False)
    linked, ambiguous = result["linked"], result["ambiguous"]

    if not linked and not ambiguous:
        print("No unlinked transfer pairs found.")
        return 0
    print(f"{len(linked)} pair(s) can be linked; "
          f"{len(ambiguous)} cluster(s) are ambiguous and will be left alone.")
    if ambiguous:
        print("  Ambiguous clusters are reported, never resolved by guessing --\n"
              "  a wrong pairing reconciles perfectly and so would be invisible.")
    if not args.yes:
        print("\nNothing was written. Re-run with --yes to apply.")
        return 0

    if not args.no_snapshot:
        print(f"snapshot: {db.snapshot(args.db)}")
    result = link_transfers(conn, day_window=args.days, apply=True)
    print(f"{result['written']} transaction(s) linked into "
          f"{len(result['linked'])} transfer group(s).")
    return 0


def cmd_forget(args):
    conn = open_db(args)
    target = args.target

    documents = _resolve_documents(conn, target)
    account = conn.execute("SELECT account_id FROM accounts WHERE account_id=?",
                           (target,)).fetchone()

    if not documents and not account:
        out(f"nothing matches '{target}' — neither a document id/file name nor "
            f"an account id.")
        conn.close()
        return 1

    if account:
        documents = _rows(conn,
            "SELECT document_id, file_name, account_id FROM documents "
            "WHERE account_id=?", (target,))

    heading(f"forget {target}")
    for document in documents:
        out(f"  document {document['file_name']} "
            f"[{document['document_id'][:12]}] ({document['account_id']})")
    if account:
        out(f"  account  {target} (and its aliases)")
    out("  cascade: pages, words, tables, lines, raw + normalized transactions, "
        "summary, rewards (D-028i)")

    if not args.yes:
        out()
        out("  nothing deleted — re-run with --yes to confirm.")
        conn.close()
        return 0

    if not args.no_snapshot and os.path.exists(args.db):
        dest = db.snapshot(args.db)
        out(f"  snapshot {dest}")

    for document in documents:
        db.forget_document(conn, document["document_id"])
        LOG.info("forgot document %s", document["document_id"][:12])
    if account:
        conn.execute("DELETE FROM transactions WHERE account_id=?", (target,))
        conn.execute("DELETE FROM transactions_raw WHERE account_id=?", (target,))
        conn.execute("DELETE FROM reward_statements WHERE account_id=?", (target,))
        conn.execute("DELETE FROM accounts WHERE account_id=?", (target,))
        conn.commit()
        LOG.info("forgot account %s", target)

    out()
    out(f"  deleted {len(documents)} document(s)"
        + (" and the account" if account else "") + ".")
    out("  The original PDFs were read in place and never copied here, so "
        "nothing else remains (D-028i).")
    conn.close()
    return 0


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="analyse",
        description="Credit card statement analyser — routing plan, net value, "
                    "and the evidence behind both.",
        epilog="Corrections are made by editing merchant_map.csv / "
               "category_overrides.csv, never interactively (D-001).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", default=db.DEFAULT_DB_PATH,
                        help="SQLite database (default: %(default)s)")
    parser.add_argument("--log-level", default="WARNING",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
                        help="log verbosity; logs never carry money (D-028i)")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_ingest = sub.add_parser("ingest", help="parse, reconcile and store (idempotent)")
    p_ingest.add_argument("path", help="a PDF, or a directory of PDFs")
    p_ingest.add_argument("--account", help="account slug (default: derived from "
                                            "issuer + masked PAN)")
    p_ingest.add_argument("--no-snapshot", action="store_true",
                          help="skip the pre-ingest backup (D-028j)")
    p_ingest.set_defaults(func=cmd_ingest)

    p_review = sub.add_parser("review", help="the correction queue")
    p_review.add_argument("--limit", type=int, default=25,
                          help="rows per section (default: %(default)s)")
    p_review.set_defaults(func=cmd_review)

    p_rules = sub.add_parser("rules", help="extracted rules, provenance, conflicts")
    p_rules.add_argument("card", help="card name as printed in the terms document")
    p_rules.add_argument("--terms-dir", default=DEFAULT_TERMS_DIR,
                         help="directory of KFS / T&C PDFs (default: %(default)s)")
    p_rules.add_argument("--currency", default="AED",
                         help="currency for printed amounts (default: %(default)s)")
    p_rules.set_defaults(func=cmd_rules)

    p_plan = sub.add_parser("plan", help="the routing plan (primary output, D-027)")
    p_plan.set_defaults(func=cmd_plan)

    p_value = sub.add_parser("value", help="net value, break-even, sensitivity")
    p_value.add_argument("card", help="card_id as defined in the wallet")
    p_value.set_defaults(func=cmd_value)

    for analysis in (p_plan, p_value, p_rules):
        analysis.add_argument("--wallet", default=DEFAULT_WALLET_PATH,
                              help="confirmed card rules (default: %(default)s)")
    for analysis in (p_plan, p_value):
        analysis.add_argument("--months", type=int, default=12,
                              help="horizon length (default: %(default)s)")
        analysis.add_argument("--start", help="horizon start, ISO-8601 "
                                              "(default: first month on file)")

    p_reclassify = sub.add_parser(
        "reclassify",
        help="re-run transaction typing over stored rows (dry run by default)")
    p_reclassify.add_argument("--yes", action="store_true",
                              help="actually write the new types")
    p_reclassify.add_argument("--no-snapshot", action="store_true",
                              help="skip the pre-write backup")
    p_reclassify.set_defaults(func=cmd_reclassify)

    p_link = sub.add_parser(
        "link-transfers",
        help="pair the two legs of internal transfers (dry run by default)")
    p_link.add_argument("--days", type=int, default=5,
                        help="how far apart the legs may post (default: %(default)s)")
    p_link.add_argument("--yes", action="store_true", help="actually write the links")
    p_link.add_argument("--no-snapshot", action="store_true",
                        help="skip the pre-write backup")
    p_link.set_defaults(func=cmd_link_transfers)

    p_forget = sub.add_parser("forget", help="delete a document or account, "
                                             "with cascade")
    p_forget.add_argument("target", help="document id, file name, or account id")
    p_forget.add_argument("--yes", action="store_true", help="actually delete")
    p_forget.add_argument("--no-snapshot", action="store_true",
                          help="skip the pre-delete backup")
    p_forget.set_defaults(func=cmd_forget)
    return parser


def _configure_logging(level):
    """Logs go to a file and carry no financial values (D-028i)."""
    log_dir = os.path.join(db.PROJECT_ROOT, "logs")
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        filename=os.path.join(log_dir, "analyser.log"),
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    _configure_logging(args.log_level)
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
