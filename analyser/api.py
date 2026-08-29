"""Localhost-only HTTP API over the analyser engine (D-029).

Binds to 127.0.0.1. No auth, because there is no remote surface. Never calculates
money -- every figure comes from analyser/domain and is serialised as
{minor, currency, exponent} so the client formats using the STORED exponent (D-020a).

Run:  .venv/bin/python -m analyser.api
"""
import json
import logging
import os
import sqlite3
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from typing import List
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from analyser.db import connect
from analyser.corrections import (
    MERCHANT_MAP, CATEGORY_MAP, ensure_files, load_alias_map, load_category_map,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "analyser.db")
HOST, PORT = "127.0.0.1", 8787

app = FastAPI(title="Spend Tracker", docs_url="/api/docs")
app.add_middleware(
    CORSMiddleware,
    # The UI dev server picks a free port; 3000 is often taken. Localhost only --
    # this is not a public surface (D-029).
    allow_origins=[f"http://{h}:{p}"
                   for h in ("localhost", "127.0.0.1", "spend-tracker.personal")
                   for p in (3000, 3111, 3999)],
    allow_methods=["*"], allow_headers=["*"],
)


def db():
    if not os.path.exists(DB_PATH):
        raise HTTPException(404, "No database yet. Run: python -m analyser ingest <path>")
    c = connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def money(minor, currency="AED", exponent=2):
    """The ONLY money shape crossing the wire. The client must not divide by 100."""
    if minor is None:
        return None
    return {"minor": int(minor), "currency": currency, "exponent": exponent}


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------- overview

@app.get("/api/overview")
def overview(from_date: Optional[str] = None, to_date: Optional[str] = None):
    c = db()
    w, a = _window(from_date, to_date)
    docs = rows(c.execute(
        "SELECT status, COUNT(*) n FROM documents GROUP BY status"))
    spend = c.execute(
        f"SELECT COALESCE(SUM(-amount_minor),0) FROM v_spend WHERE 1=1{w}", a).fetchone()[0]
    uncat = c.execute(
        f"SELECT COALESCE(SUM(-amount_minor),0) FROM v_spend WHERE category IS NULL{w}",
        a).fetchone()[0]
    n_tx = c.execute(f"SELECT COUNT(*) FROM v_spend WHERE 1=1{w}", a).fetchone()[0]
    accounts = rows(c.execute(
        "SELECT a.account_id, a.issuer, a.product_name, a.account_type, a.currency,"
        "       a.include_in_spending,"
        "       (SELECT COUNT(*) FROM transactions t WHERE t.account_id=a.account_id) txns"
        "  FROM accounts a ORDER BY a.issuer"))
    cycles = c.execute(
        f"SELECT COUNT(DISTINCT substr(txn_date,1,7)) FROM v_spend WHERE 1=1{w}",
        a).fetchone()[0]
    return {
        "documents": {d["status"]: d["n"] for d in docs},
        "transactions": n_tx,
        "accounts": accounts,
        "total_spend": money(spend),
        "uncategorized_spend": money(uncat),
        "uncategorized_pct": round(100.0 * uncat / spend, 1) if spend else 0.0,
        "months_covered": cycles,
        # D-016d: the gate is weighted by VALUE, not transaction count.
        "gates": [
            {"gate": "UNCATEGORIZED_SPEND", "failing": bool(spend and uncat / spend > 0.10),
             "detail": "uncategorized spend must stay at or below 10% by value"},
            {"gate": "COVERAGE", "failing": cycles < 6,
             "detail": f"{cycles} of 6 months minimum"},
        ],
    }


# ---------------------------------------------------------------- documents

@app.get("/api/documents")
def documents():
    c = db()
    return rows(c.execute(
        "SELECT d.document_id, d.file_name, d.parser_name, d.parser_version, d.status,"
        "       d.reject_reason, d.statement_date, d.period_start, d.period_end,"
        "       d.page_count, d.ingested_at, d.account_id,"
        "       (SELECT COUNT(*) FROM transactions_raw r WHERE r.document_id=d.document_id) txns,"
        "       (SELECT COUNT(*) FROM document_lines l WHERE l.document_id=d.document_id) lines,"
        "       (SELECT COUNT(*) FROM document_lines l WHERE l.document_id=d.document_id"
        "         AND l.disposition='UNPARSED') unparsed"
        "  FROM documents d ORDER BY d.file_name"))


@app.get("/api/documents/{document_id}/summary")
def document_summary(document_id: str):
    c = db()
    r = c.execute("SELECT * FROM statement_summary WHERE document_id=?",
                  (document_id,)).fetchone()
    if not r:
        raise HTTPException(404, "no summary for that document")
    d = dict(r)
    return {k: (money(v) if k != "document_id" else v) for k, v in d.items()}


# A "repayment" is money moving between the user's own accounts, not spending:
# a card payment, an inter-account transfer, or any row on a settlement facility
# such as Wio whose outflows settle other cards (D-007). Hidden by default
# everywhere, because counting it as spending double-counts the same dirhams.
REPAYMENT_SQL = "(a.include_in_spending = 0 OR COALESCE(t.user_txn_type,t.system_txn_type) IN ('PAYMENT','TRANSFER'))"


#: Product names printed on statements are sometimes useless as labels -- Dubai
#: First prints the single word "CREDIT". Fall back to the issuer's display name
#: when the printed product tells the reader nothing.
_GENERIC_PRODUCTS = {"CREDIT", "CREDIT CARD", "CARD", "ACCOUNT", "STATEMENT", "CIA"}


def _card_label(product, issuer, account_id):
    from analyser import issuers as iss

    name = (product or "").strip()
    issuer_name = None
    if issuer:
        found = iss.by_id(str(issuer).lower().replace(" ", "_"))
        issuer_name = found.name if found is not iss.UNKNOWN else str(issuer).title()
    if not name or name.upper() in _GENERIC_PRODUCTS:
        return issuer_name or account_id
    return name


# ---------------------------------------------------------------- transactions

@app.get("/api/transactions")
def transactions(account_id: Optional[str] = None, category: Optional[str] = None,
                 uncategorized: bool = False, include_repayments: bool = False,
                 from_date: Optional[str] = None, to_date: Optional[str] = None,
                 limit: int = 500):
    c = db()
    q = ("SELECT t.txn_id, t.account_id, t.txn_date, t.posting_date, t.amount_minor,"
         "       t.currency, t.system_txn_type, t.user_txn_type, t.system_merchant,"
         "       t.user_merchant, t.system_category, t.user_category,"
         "       t.category_confidence, t.excluded, t.transfer_group_id,"
         "       a.include_in_spending, a.product_name, a.issuer, a.account_type,"
         "       r.raw_description"
         "  FROM transactions t"
         "  JOIN accounts a ON a.account_id = t.account_id"
         "  LEFT JOIN transactions_raw r ON r.raw_id = t.txn_id WHERE 1=1")
    args: list[Any] = []
    if not include_repayments:
        q += f" AND NOT {REPAYMENT_SQL}"
    if from_date:
        q += " AND t.txn_date >= ?"; args.append(from_date)
    if to_date:
        q += " AND t.txn_date <= ?"; args.append(to_date)
    if account_id:
        q += " AND t.account_id=?"; args.append(account_id)
    if category:
        q += " AND COALESCE(t.user_category,t.system_category)=?"; args.append(category)
    if uncategorized:
        q += " AND COALESCE(t.user_category,t.system_category) IS NULL"
    q += " ORDER BY t.txn_date DESC, ABS(t.amount_minor) DESC, t.txn_id LIMIT ?"
    args.append(limit)
    out = []
    for r in rows(c.execute(q, args)):
        r["amount"] = money(r.pop("amount_minor"), r.get("currency") or "AED")
        r["merchant"] = r["user_merchant"] or r["system_merchant"]
        r["category"] = r["user_category"] or r["system_category"]
        r["txn_type"] = r["user_txn_type"] or r["system_txn_type"]
        r["corrected"] = bool(r["user_merchant"] or r["user_category"] or r["user_txn_type"])
        r["card"] = _card_label(r.get("product_name"), r.get("issuer"),
                                r["account_id"])
        out.append(r)
    return out


@app.get("/api/transactions/{txn_id}/evidence")
def txn_evidence(txn_id: str):
    """Where a single figure came from, verbatim.

    Full traceability (spec P5) was a promise in the footer rather than
    something you could click. Everything needed was already stored: the raw
    row keeps the source line, its page and its ordinal within the statement,
    and the document keeps the parser that read it and whether it reconciled.
    """
    c = db()
    r = c.execute(
        "SELECT r.raw_id, r.document_id, r.account_id, r.page_number, r.line_index,"
        "       r.raw_text, r.raw_description, r.amount_minor, r.currency,"
        "       r.txn_date, r.posting_date, r.fx_amount_minor, r.fx_currency,"
        "       d.file_name, d.parser_name, d.parser_version, d.status,"
        "       d.reject_reason, d.statement_date, d.period_start, d.period_end,"
        "       d.page_count, d.ingested_at,"
        "       a.issuer, a.product_name, a.account_type,"
        "       t.system_category, t.user_category, t.category_confidence,"
        "       t.system_merchant, t.user_merchant, t.excluded, t.exclude_reason,"
        "       t.transfer_group_id"
        "  FROM transactions_raw r"
        "  JOIN documents d ON d.document_id = r.document_id"
        "  JOIN accounts  a ON a.account_id  = r.account_id"
        "  LEFT JOIN transactions t ON t.txn_id = r.raw_id"
        " WHERE r.raw_id = ?", (txn_id,)).fetchone()
    if r is None:
        raise HTTPException(404, f"No stored line for {txn_id}")
    r = dict(r)

    # The lines printed either side, so the figure can be read in context. A
    # CONTINUATION row is part of the same charge, which is often where the real
    # merchant name is hiding.
    #
    # transactions_raw.line_index counts TRANSACTIONS within the statement;
    # document_lines.line_index counts EVERY printed line. They are independent
    # sequences, so the source line has to be located by its own text before its
    # neighbours mean anything -- joining the two ordinals directly returns the
    # page header.
    anchor = c.execute(
        "SELECT line_index FROM document_lines"
        " WHERE document_id = ? AND page_number = ? AND raw_text = ?"
        " ORDER BY line_index LIMIT 1",
        (r["document_id"], r["page_number"], r["raw_text"])).fetchone()
    around = []
    if anchor is not None:
        at = anchor["line_index"]
        around = rows(c.execute(
            "SELECT page_number, line_index, raw_text, disposition"
            "  FROM document_lines"
            " WHERE document_id = ? AND page_number = ?"
            "   AND line_index BETWEEN ? AND ?"
            " ORDER BY line_index",
            (r["document_id"], r["page_number"], at - 2, at + 2)))
        for line in around:
            line["is_this_charge"] = line["line_index"] == at

    return {
        "txn_id": r["raw_id"],
        "amount": money(r["amount_minor"], r["currency"] or "AED"),
        "fx": (money(r["fx_amount_minor"], r["fx_currency"])
               if r["fx_amount_minor"] is not None and r["fx_currency"] else None),
        "txn_date": r["txn_date"],
        "posting_date": r["posting_date"],
        "merchant": r["user_merchant"] or r["system_merchant"],
        "category": r["user_category"] or r["system_category"],
        "category_confidence": r["category_confidence"],
        "corrected": bool(r["user_category"] or r["user_merchant"]),
        "excluded": bool(r["excluded"]),
        "exclude_reason": r["exclude_reason"],
        "is_transfer": bool(r["transfer_group_id"]),
        "source": {
            "raw_text": r["raw_text"],
            "raw_description": r["raw_description"],
            "page_number": r["page_number"],
            "line_index": r["line_index"],
            "printed_at_line": (anchor["line_index"] if anchor is not None else None),
            "context": around,
        },
        "document": {
            "document_id": r["document_id"],
            "file_name": r["file_name"],
            "parser_name": r["parser_name"],
            "parser_version": r["parser_version"],
            "status": r["status"],
            "reject_reason": r["reject_reason"],
            "statement_date": r["statement_date"],
            "period_start": r["period_start"],
            "period_end": r["period_end"],
            "page_count": r["page_count"],
            "ingested_at": r["ingested_at"],
        },
        "account": {
            "account_id": r["account_id"],
            "issuer": r["issuer"],
            "product_name": r["product_name"],
            "account_type": r["account_type"],
        },
    }


@app.get("/api/expenses")
def expenses(from_date: Optional[str] = None, to_date: Optional[str] = None,
             account_id: Optional[str] = None, category: Optional[str] = None,
             limit: int = 1000):
    """Every EXPENSE in a window, newest first, with the card it was paid on.

    Restricted to v_spend: payments, transfers, loan instalments, fees and internal
    adjustments are not expenses, and mixing them into a ledger makes the month's
    figures impossible to reconcile by eye (D-007, D-028b, D-037).
    """
    c = db()
    w, window_args = _window(from_date, to_date, "v")

    filters, filter_args = "", []
    if account_id:
        filters += " AND v.account_id = ?"; filter_args.append(account_id)
    if category:
        filters += " AND v.category = ?"; filter_args.append(category)

    q = ("SELECT v.txn_id, v.account_id, v.txn_date, v.posting_date, v.amount_minor,"
         "       v.currency, v.merchant, v.category, v.confidence,"
         "       a.product_name, a.issuer, r.raw_description"
         "  FROM v_spend v"
         "  JOIN accounts a ON a.account_id = v.account_id"
         "  LEFT JOIN transactions_raw r ON r.raw_id = v.txn_id"
         f" WHERE 1=1{w}{filters}"
         " ORDER BY v.txn_date DESC, ABS(v.amount_minor) DESC, v.txn_id LIMIT ?")

    items, total = [], 0
    for r in rows(c.execute(q, window_args + filter_args + [limit])):
        cur = r.get("currency") or "AED"
        magnitude = -r.pop("amount_minor")
        total += magnitude
        r["amount"] = money(magnitude, cur)
        r["card"] = _card_label(r.pop("product_name", None), r.pop("issuer", None),
                                r["account_id"])
        items.append(r)

    # Per-card totals for the same window, so the ledger can be read by card.
    by_card = [
        {"account_id": r["account_id"],
         "card": _card_label(r["product_name"], r["issuer"], r["account_id"]),
         "spend": money(r["spend"]), "transactions": r["n"]}
        for r in c.execute(
            "SELECT v.account_id, a.product_name, a.issuer,"
            "       SUM(-v.amount_minor) spend, COUNT(*) n"
            "  FROM v_spend v JOIN accounts a ON a.account_id=v.account_id"
            f" WHERE 1=1{w} GROUP BY v.account_id ORDER BY spend DESC", window_args)
    ]

    # Reimbursables are excluded from expenses but reported alongside, so the
    # difference between "what I spent" and "what went on the card" is visible.
    reimb = c.execute(
        f"SELECT COALESCE(SUM(-amount_minor),0) s, COUNT(*) n"
        f"  FROM v_reimbursable WHERE 1=1{_window(from_date, to_date)[0]}",
        _window(from_date, to_date)[1]).fetchone()

    return {"expenses": items, "total": money(total), "count": len(items),
            "by_card": by_card,
            "reimbursable": {"total": money(reimb["s"]), "count": reimb["n"]}}


@app.get("/api/review")
def review(limit: int = 200, include_repayments: bool = False):
    """The correction queue: uncategorized or low-confidence SPEND, by value (D-016d).

    Repayments are excluded by default -- categorising a card payment is meaningless
    work, and it was crowding out the transactions that actually matter.
    """
    c = db()
    # Restricted to rows that are actually SPEND (v_spend). Fees, loan instalments,
    # internal adjustments and payments are excluded: they are costs or bookkeeping,
    # not purchases at a merchant, so there is no category to choose.
    q = ("SELECT t.txn_id, t.account_id, t.txn_date, t.amount_minor, t.currency,"
         "       t.system_merchant, t.user_merchant, t.system_category, t.user_category,"
         "       t.category_confidence, r.raw_description"
         "  FROM transactions t"
         "  JOIN accounts a ON a.account_id = t.account_id"
         "  LEFT JOIN transactions_raw r ON r.raw_id=t.txn_id"
         " WHERE t.txn_id IN (SELECT txn_id FROM v_spend)"
         "   AND (COALESCE(t.user_category,t.system_category) IS NULL"
         "        OR t.category_confidence IN ('LOW','UNKNOWN'))")
    q += " ORDER BY ABS(t.amount_minor) DESC LIMIT ?"
    out = []
    for r in rows(c.execute(q, (limit,))):
        r["amount"] = money(r.pop("amount_minor"), r.get("currency") or "AED")
        r["merchant"] = r["user_merchant"] or r["system_merchant"]
        r["category"] = r["user_category"] or r["system_category"]
        out.append(r)
    return out


# ---------------------------------------------------------------- corrections

class Correction(BaseModel):
    match: Optional[str] = None       # substring of the raw description
    canonical: Optional[str] = None   # canonical merchant name
    category: Optional[str] = None    # category for that canonical merchant


@app.get("/api/corrections")
def get_corrections():
    ensure_files()
    return {"merchants": load_alias_map(), "categories": load_category_map(),
            "files": {"merchant_map": MERCHANT_MAP, "category_map": CATEGORY_MAP}}


@app.post("/api/corrections")
def add_correction(body: Correction):
    """Append to the SAME csv files the CLI and a text editor use (D-001, D-029).

    Corrections are authoritative and permanent; they take effect on the next ingest.
    """
    import csv
    ensure_files()
    wrote = []
    if body.match and body.canonical:
        existing = load_alias_map()
        if existing.get(body.match.strip().upper()) != body.canonical:
            with open(MERCHANT_MAP, "a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow([body.match.strip(), body.canonical.strip()])
            wrote.append("merchant_map.csv")
    if body.canonical and body.category:
        existing = load_category_map()
        if existing.get(body.canonical) != body.category.upper():
            with open(CATEGORY_MAP, "a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow([body.canonical.strip(), body.category.strip().upper()])
            wrote.append("category_overrides.csv")
    if not wrote:
        return {"written": [], "note": "already present, nothing appended"}
    return {"written": wrote,
            "note": "Re-ingest to apply: python -m analyser ingest sample_statements/"}


class Recategorise(BaseModel):
    category: str
    # Whether the rule should apply to every charge from this merchant. Left unset,
    # it is decided per category: a reimbursable is a one-off (you bought something
    # for someone else at a shop you normally use yourself), while "Lulu is
    # groceries" is a standing fact.
    apply_to_merchant: Optional[bool] = None


#: Categories that describe a SITUATION rather than a merchant, so a rule about the
#: merchant would be wrong.
_ONE_OFF_PREFIXES = ("REIMBURSABLE", "GIFT", "ONE_OFF")


@app.post("/api/transactions/{txn_id}/category")
def set_category(txn_id: str, body: Recategorise):
    """Recategorise a charge from anywhere it appears.

    Two effects, both required for corrections to compound (spec §18, D-001):

    1. `transactions.user_category` is set NOW, so the change is visible immediately.
       A user correction outranks anything the system inferred and is never
       overwritten by a later re-ingest.
    2. When `apply_to_merchant`, the rule is appended to data/category_overrides.csv
       and applied to every other charge from that merchant, so the same correction
       never has to be made twice — including on statements not yet downloaded.
    """
    import csv
    from analyser.corrections import CATEGORY_MAP, ensure_files, load_category_map

    category = (body.category or "").strip().upper().replace(" ", "_")
    if not category:
        raise HTTPException(400, "A category is required.")

    apply_to_merchant = body.apply_to_merchant
    if apply_to_merchant is None:
        apply_to_merchant = not category.startswith(_ONE_OFF_PREFIXES)

    c = db()
    row = c.execute(
        "SELECT t.txn_id, COALESCE(t.user_merchant,t.system_merchant) merchant"
        "  FROM transactions t WHERE t.txn_id=?", (txn_id,)).fetchone()
    if not row:
        raise HTTPException(404, "No such transaction.")
    merchant = row["merchant"]

    c.execute("UPDATE transactions SET user_category=?, category_confidence='HIGH'"
              " WHERE txn_id=?", (category, txn_id))
    updated = 1

    if apply_to_merchant and merchant:
        cur = c.execute(
            "UPDATE transactions SET user_category=?, category_confidence='HIGH'"
            " WHERE COALESCE(user_merchant,system_merchant)=? AND txn_id<>?",
            (category, merchant, txn_id))
        updated += cur.rowcount or 0

        ensure_files()
        if load_category_map().get(merchant) != category:
            with open(CATEGORY_MAP, "a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow([merchant, category])
    c.commit()

    return {
        "txn_id": txn_id, "merchant": merchant, "category": category,
        "updated": updated,
        "applied_to_merchant": bool(apply_to_merchant and merchant),
        "note": (f"{merchant} is now {category.lower().replace('_', ' ')} — {updated} "
                 f"charge{'s' if updated != 1 else ''} updated, and future statements too."
                 if apply_to_merchant and merchant
                 else f"This one charge is now {category.lower().replace('_', ' ')}. "
                      f"Other {merchant} charges are untouched."),
    }


@app.get("/api/categories")
def categories():
    """Known categories: the core taxonomy plus anything already in use."""
    core = ["GROCERIES", "DINING", "TRAVEL", "AIRLINES", "HOTELS", "FUEL",
            "TRANSPORTATION", "SHOPPING", "E_COMMERCE", "ENTERTAINMENT", "UTILITIES",
            "TELECOM", "SUBSCRIPTIONS", "HEALTHCARE", "EDUCATION", "INSURANCE",
            "GOVERNMENT", "RENT", "CASH", "FEES", "NOON", "OTHER"]
    try:
        used = {r[0] for r in db().execute(
            "SELECT DISTINCT COALESCE(user_category,system_category) FROM transactions") if r[0]}
    except HTTPException:
        used = set()
    return sorted(set(core) | used)


# ---------------------------------------------------------------- rewards / rules

@app.get("/api/rewards")
def rewards():
    """Issuer-PRINTED reward figures -- the engine's ground truth (D-011)."""
    c = db()
    out = []
    for r in rows(c.execute("SELECT * FROM reward_statements")):
        for k in ("spend_minor", "earned", "opening_balance", "closing_balance",
                  "adjusted", "redeemed"):
            if k in r:
                r[k] = money(r[k], r.get("reward_unit") or "AED") if r[k] is not None else None
        out.append(r)
    return out


@app.get("/api/cards/{card}/rules")
def card_rules(card: str):
    """Extracted terms with provenance and conflicts (D-022, D-023). Never silently
    resolves a conflict -- both readings are returned."""
    from analyser import rules as rules_mod
    from analyser.cli import _terms_documents, _document_text, _source_kind, DEFAULT_TERMS_DIR
    from analyser.parsers import DocumentEncrypted

    found, unreadable = [], []
    for path in _terms_documents(DEFAULT_TERMS_DIR):
        name = os.path.basename(path)
        try:
            text = _document_text(path)
        except DocumentEncrypted:
            unreadable.append({"file": name, "reason": "ENCRYPTED"})
            continue
        except Exception:                            # noqa: BLE001
            unreadable.append({"file": name, "reason": "UNREADABLE"})
            continue
        extracted = rules_mod.extract_rules(text, card_name=card)
        if extracted is None:
            continue                                 # D-022: never borrow a neighbour's row
        found.append({"source": _source_kind(name), "file": name,
                      "text": text, "facts": extracted})

    if not found:
        raise HTTPException(404,
            f"No terms document names '{card}'. A card's rules are never inferred "
            "from a neighbouring product (D-022).")

    merged = rules_mod.merge_sources(found)
    conflicts = merged.get("conflicts") or []
    return {
        "card": card,
        "sources": [{"source": d["source"], "file": d["file"]} for d in found],
        "unreadable": unreadable,
        "precedence": "KFS > T&C > product page > third party",
        "tiers": merged.get("tiers") or [],
        "exclusions": merged.get("exclusions") or [],
        "cycle": merged.get("cycle"),
        "expiry_months": merged.get("expiry_months"),
        "fx_spread_bps": merged.get("fx_spread_bps"),
        "fx_total_bps": merged.get("fx_total_bps"),
        "conflicts": conflicts,
        "provenance": merged.get("provenance") or {},
    }


# ---------------------------------------------------------------- analytics
# A date window applied to v_spend. Every figure in the app is scoped by it, so
# "this month" and "last 6 months" are answerable without the client ever slicing
# money itself (D-029).
def _window(from_date: Optional[str], to_date: Optional[str], alias: str = ""):
    """`alias` qualifies the column, e.g. _window(a, b, "v") -> "v.txn_date >= ?".

    Required whenever the query joins: a bare `txn_date` is ambiguous once more than
    one table in scope has that column.
    """
    col = f"{alias}.txn_date" if alias else "txn_date"
    clauses, args = [], []
    if from_date:
        clauses.append(f"{col} >= ?"); args.append(from_date)
    if to_date:
        clauses.append(f"{col} <= ?"); args.append(to_date)
    return (" AND " + " AND ".join(clauses) if clauses else ""), args


@app.get("/api/analytics/range")
def analytics_range():
    """The full span of data held, so the UI can offer sensible period choices."""
    c = db()
    r = c.execute("SELECT MIN(txn_date) lo, MAX(txn_date) hi, COUNT(*) n"
                  "  FROM v_spend").fetchone()
    months = [x[0] for x in c.execute(
        "SELECT DISTINCT substr(txn_date,1,7) m FROM v_spend ORDER BY m DESC")]
    return {"first": r["lo"], "last": r["hi"], "transactions": r["n"], "months": months}



# Every aggregate here is summed in SQL/Python. The browser receives finished
# figures and never adds money (D-029).

@app.get("/api/analytics/by-category")
def by_category(from_date: Optional[str] = None, to_date: Optional[str] = None):
    c = db()
    w, a = _window(from_date, to_date)
    total = c.execute(f"SELECT COALESCE(SUM(-amount_minor),0) FROM v_spend WHERE 1=1{w}",
                      a).fetchone()[0] or 0
    out = []
    for r in c.execute(
        "SELECT COALESCE(category,'UNCATEGORIZED') cat, SUM(-amount_minor) spend,"
        "       COUNT(*) txns"
        f"  FROM v_spend WHERE 1=1{w} GROUP BY cat ORDER BY spend DESC", a
    ):
        out.append({"category": r["cat"], "spend": money(r["spend"]), "txns": r["txns"],
                    "pct": round(100.0 * r["spend"] / total, 1) if total else 0.0})
    return {"total": money(total), "categories": out}


@app.get("/api/analytics/by-month")
def by_month():
    c = db()
    return [
        {"month": r["m"], "spend": money(r["spend"]), "txns": r["txns"]}
        for r in c.execute(
            "SELECT substr(txn_date,1,7) m, SUM(-amount_minor) spend, COUNT(*) txns"
            "  FROM v_spend GROUP BY m ORDER BY m")
    ]


@app.get("/api/analytics/category/{category}")
def category_detail(category: str, from_date: Optional[str] = None,
                    to_date: Optional[str] = None):
    """Every charge in one category, grouped BY MONTH.

    Feeds the detail sheet: a category total is only useful if you can open it and
    see what is actually inside, month by month.
    """
    c = db()
    w, args = _window(from_date, to_date, "v")
    target = category.upper()

    months: dict = {}
    total = 0
    for r in rows(c.execute(
        "SELECT v.txn_id, v.txn_date, v.merchant, v.amount_minor, v.currency,"
        "       v.account_id, v.category, a.product_name, a.issuer,"
        "       substr(v.txn_date,1,7) month, r.raw_description"
        "  FROM v_spend v"
        "  JOIN accounts a ON a.account_id = v.account_id"
        "  LEFT JOIN transactions_raw r ON r.raw_id = v.txn_id"
        f" WHERE UPPER(COALESCE(v.category,'UNCATEGORIZED')) = ?{w}"
        " ORDER BY v.txn_date DESC, ABS(v.amount_minor) DESC",
        [target] + args)
    ):
        cur = r.get("currency") or "AED"
        magnitude = -r.pop("amount_minor")
        total += magnitude
        month = r.pop("month")
        r["amount"] = money(magnitude, cur)
        r["card"] = _card_label(r.pop("product_name", None), r.pop("issuer", None),
                                r["account_id"])
        bucket = months.setdefault(month, {"month": month, "charges": [],
                                           "spend_minor": 0})
        bucket["charges"].append(r)
        bucket["spend_minor"] += magnitude

    out = []
    for m in sorted(months.values(), key=lambda x: x["month"], reverse=True):
        out.append({"month": m["month"], "spend": money(m["spend_minor"]),
                    "count": len(m["charges"]), "charges": m["charges"]})

    # Which merchants drive this category — the usual first question.
    merchants = [
        {"merchant": r["m"] or "—", "spend": money(r["s"]), "count": r["n"]}
        for r in c.execute(
            "SELECT v.merchant m, SUM(-v.amount_minor) s, COUNT(*) n FROM v_spend v"
            f" WHERE UPPER(COALESCE(v.category,'UNCATEGORIZED')) = ?{w}"
            " GROUP BY v.merchant ORDER BY s DESC LIMIT 12", [target] + args)
    ]

    return {"category": target, "total": money(total),
            "count": sum(m["count"] for m in out),
            "months": out, "merchants": merchants}


@app.get("/api/analytics/by-merchant")
def by_merchant(limit: int = 10, from_date: Optional[str] = None,
                to_date: Optional[str] = None):
    c = db()
    w, a = _window(from_date, to_date)
    return [
        {"merchant": r["m"] or "—", "category": r["cat"],
         "spend": money(r["spend"]), "txns": r["txns"]}
        for r in c.execute(
            "SELECT merchant m, category cat, SUM(-amount_minor) spend, COUNT(*) txns"
            f"  FROM v_spend WHERE 1=1{w} GROUP BY m, cat ORDER BY spend DESC LIMIT ?",
            a + [limit])
    ]


@app.get("/api/analytics/by-account")
def by_account():
    c = db()
    return [
        {"account_id": r["account_id"], "issuer": r["issuer"],
         "spend": money(r["spend"]), "txns": r["txns"]}
        for r in c.execute(
            "SELECT account_id, issuer, SUM(-amount_minor) spend, COUNT(*) txns"
            "  FROM v_spend GROUP BY account_id, issuer ORDER BY spend DESC")
    ]


@app.get("/api/analytics/recurring")
def recurring(min_months: int = 2):
    """Merchants charged in several distinct months — subscriptions and standing costs.

    Spec §G2 calls these out as behavioural signal: they are the predictable floor of
    the spending profile, and the easiest thing to act on.
    """
    c = db()
    return [
        {"merchant": r["m"], "category": r["cat"], "months": r["months"],
         "txns": r["txns"], "total": money(r["total"]), "typical": money(r["typical"])}
        for r in c.execute(
            "SELECT merchant m, category cat,"
            "       COUNT(DISTINCT substr(txn_date,1,7)) months, COUNT(*) txns,"
            "       SUM(-amount_minor) total,"
            "       CAST(AVG(-amount_minor) AS INTEGER) typical"
            "  FROM v_spend WHERE merchant IS NOT NULL"
            " GROUP BY m, cat HAVING months >= ?"
            " ORDER BY total DESC", (min_months,))
    ]


@app.get("/api/analytics/trend")
def trend():
    """Month-over-month spend, with the change already computed (D-029)."""
    c = db()
    months = [
        {"month": r["m"], "spend": money(r["spend"]), "txns": r["txns"],
         "spend_minor": r["spend"]}
        for r in c.execute(
            "SELECT substr(txn_date,1,7) m, SUM(-amount_minor) spend, COUNT(*) txns"
            "  FROM v_spend GROUP BY m ORDER BY m")
    ]
    raw = [m["spend_minor"] for m in months]      # snapshot before the key is removed
    for i, m in enumerate(months):
        prev = raw[i - 1] if i else None
        m["change_minor"] = (m["spend_minor"] - prev) if prev is not None else None
        m["change"] = money(m["change_minor"]) if prev is not None else None
        m["change_pct"] = (round(100.0 * (m["spend_minor"] - prev) / prev, 1)
                           if prev else None)
        del m["spend_minor"]
    current = months[-1] if months else None
    return {"months": months, "current": current,
            "average": money(
                int(sum(x["spend"]["minor"] for x in months) / len(months))) if months else None}


@app.get("/api/analytics/largest")
def largest(limit: int = 8, from_date: Optional[str] = None,
            to_date: Optional[str] = None):
    """Biggest single charges — the ones worth eyeballing."""
    c = db()
    w, a = _window(from_date, to_date)
    return [
        {"txn_id": r["txn_id"], "txn_date": r["txn_date"], "merchant": r["merchant"],
         "category": r["category"], "account_id": r["account_id"],
         "amount": money(-r["amount_minor"])}
        for r in c.execute(
            "SELECT txn_id, txn_date, merchant, category, account_id, amount_minor"
            f"  FROM v_spend WHERE 1=1{w} ORDER BY amount_minor ASC LIMIT ?",
            a + [limit])
    ]


@app.get("/api/analytics/calendar")
def calendar():
    """Also reports which year the UI should open on."""
    """Spending rolled up by YEAR and MONTH — the unit people manage money in.

    Returns each year with its months nested, so the UI can offer year-then-month
    navigation without doing any arithmetic on money itself (D-029).
    """
    c = db()
    years: dict = {}
    for r in c.execute(
        "SELECT substr(txn_date,1,4) y, substr(txn_date,1,7) m,"
        "       SUM(-amount_minor) spend, COUNT(*) txns"
        "  FROM v_spend GROUP BY m ORDER BY m"
    ):
        y = years.setdefault(r["y"], {"year": r["y"], "spend_minor": 0,
                                      "txns": 0, "months": []})
        y["spend_minor"] += r["spend"]
        y["txns"] += r["txns"]
        y["months"].append({
            "month": r["m"],
            "spend": money(r["spend"]),
            "txns": r["txns"],
            "spend_minor": r["spend"],
        })

    out = []
    for y in sorted(years.values(), key=lambda x: x["year"], reverse=True):
        months = y["months"]
        busiest = max(months, key=lambda m: m["spend_minor"]) if months else None
        quietest = min(months, key=lambda m: m["spend_minor"]) if months else None
        # Month-on-month change, computed here so the client never subtracts money.
        # Snapshot the raw values FIRST: reading a neighbour's key while deleting it
        # in the same pass is the bug that broke /analytics/trend.
        raw = [m["spend_minor"] for m in months]
        for i, m in enumerate(months):
            prev = raw[i - 1] if i else None
            m["change"] = money(raw[i] - prev) if prev is not None else None
            m["change_pct"] = (round(100.0 * (raw[i] - prev) / prev, 1)
                               if prev else None)
            del m["spend_minor"]
        out.append({
            "year": y["year"],
            "is_current": y["year"] == str(datetime.now().year),
            "spend": money(y["spend_minor"]),
            "txns": y["txns"],
            "average_month": money(int(y["spend_minor"] / len(months))) if months else None,
            "busiest_month": busiest["month"] if busiest else None,
            "quietest_month": quietest["month"] if quietest else None,
            "months": list(reversed(months)),
        })
    # Default view: the CURRENT calendar year when there is data for it, else the
    # most recent year held. People manage money by the year they are living in.
    current = str(datetime.now().year)
    default = current if any(y["year"] == current for y in out) else (
        out[0]["year"] if out else None)
    return {"years": out, "default_year": default, "current_year": current}


# ---------------------------------------------------------------- positions

@app.get("/api/positions")
def positions():
    """What is owed on each card, and when. The core money-management view (D-031)."""
    c = db()
    out = []
    for r in rows(c.execute("SELECT * FROM v_position ORDER BY payment_due_date")):
        cur = r.get("currency") or "AED"
        for k in ("closing_balance", "total_payment_due", "minimum_due",
                  "credit_limit", "available_limit"):
            r[k] = money(r[k], cur) if r[k] is not None else None
        out.append(r)
    return out


# ---------------------------------------------------------------- evaluate a card

def _card_names_in(text):
    """Best-effort list of product names a terms document mentions.

    A KFS often covers several products in one table (D-022), and rotated table
    headers extract reversed ("kcabhsaC"), so candidates are matched in both
    directions. This drives a disambiguation prompt in the UI -- it is deliberately
    NOT used to guess silently, because applying a neighbouring product's rates is
    the worst failure mode this document class has.
    """
    import re as _re
    known = ["noon", "Cashback", "Elite", "Platinum Plus", "Platinum", "Solitaire",
             "World", "Signature", "Titanium", "Infinite", "Gold", "Classic",
             "Smart Saver", "Skywards", "Etihad", "Manchester United", "Flexi"]
    found, low = [], text.lower()
    for name in known:
        n = name.lower()
        if n in low or n[::-1] in low:
            found.append(name)
    # longest first, so "Platinum Plus" is offered before "Platinum"
    return sorted(dict.fromkeys(found), key=len, reverse=True)


@app.post("/api/evaluate")
async def evaluate(file: UploadFile = File(...), card_name: str = Form("")):
    """THE feature: drop a Key Facts Statement, get a verdict against real spending.

    The uploaded file is parsed in a temp directory and deleted immediately -- it is
    never stored (D-028i). Rules are extracted deterministically; every rate returned
    carries the verbatim quote it came from (spec §F9).
    """
    import tempfile
    from analyser import rules as rules_mod
    from analyser.cli import _extract_document_text

    raw = await file.read()
    if not raw[:5].startswith(b"%PDF"):
        raise HTTPException(400, "That does not look like a PDF.")

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp.write(raw); tmp.close()
        try:
            text = _extract_document_text(tmp.name)
        except Exception:                                    # noqa: BLE001
            raise HTTPException(400, "Could not read text from that PDF. "
                                     "Scanned documents are not supported yet.")
    finally:
        os.unlink(tmp.name)                                  # never retained

    names = _card_names_in(text)
    target = (card_name or "").strip() or (names[0] if names else "")
    facts = rules_mod.extract_rules(text, card_name=target) if target else None
    if not facts or not facts.get("tiers"):
        raise HTTPException(422, {
            "message": "No reward rules could be read from that document.",
            "cards_found": names,
            "hint": "If this KFS covers several products, pass card_name.",
        })

    merged = rules_mod.merge_sources([{"source": "KFS", "file": file.filename,
                                       "text": text, "facts": facts}])
    tiers = merged.get("tiers") or []

    # Project the card's tiers onto ACTUAL spend, per category, in Python.
    c = db()
    spend = {r["cat"]: r["spend"] for r in c.execute(
        "SELECT COALESCE(category,'UNCATEGORIZED') cat, SUM(-amount_minor) spend"
        "  FROM v_spend GROUP BY cat")}
    months = c.execute(
        "SELECT COUNT(DISTINCT substr(txn_date,1,7)) FROM v_spend").fetchone()[0] or 0

    # Our taxonomy (GROCERIES, FUEL, ...) and the card's eligibility wording
    # ("Government payments, utilities, education, charity, fuel, rental and telecom")
    # are different vocabularies. Mapping between them is INFERRED, never known
    # (D-009), so each line records how it matched and the UI shows that.
    SYNONYMS = {
        "GROCERIES": ("grocer", "supermarket", "supermall"),
        "DINING": ("dining", "restaurant", "food delivery"),
        "FUEL": ("fuel", "petrol"),
        "UTILITIES": ("utilit", "electricity", "water"),
        "TELECOM": ("telecom", "mobile"),
        "GOVERNMENT": ("government",),
        "EDUCATION": ("education",),
        "RENT": ("rental", "rent"),
        "TRAVEL": ("travel", "airline", "hotel"),
        "TRANSPORTATION": ("transport", "taxi"),
        "NOON": ("noon", "namshi", "nownow"),
        "SHOPPING": ("shopping", "retail"),
    }

    def tier_for(category):
        """Return (tier, how) where how is EXPLICIT | CATCH_ALL | NONE."""
        cat = (category or "").upper()
        words = SYNONYMS.get(cat, ()) + (cat.lower(),)
        best = None
        for t in tiers:
            prose = (t.get("category") or "").lower()
            if not prose or "all other" in prose:
                continue
            if any(w and w in prose for w in words):
                if best is None or t["rate_bps"] > best["rate_bps"]:
                    best = t
        if best is not None:
            return best, "EXPLICIT"
        for t in tiers:
            if "all other" in (t.get("category") or "").lower():
                return t, "CATCH_ALL"
        return None, "NONE"

    lines, projected = [], 0
    for cat, amount in sorted(spend.items(), key=lambda kv: -kv[1]):
        t, how = tier_for(cat)
        rate = t["rate_bps"] if t else 0
        # ROUND_HALF_UP, matching analyser.domain.rewards (D-023). Floor division
        # here would silently disagree with the engine: 36.57 at 5% is 1.83, not 1.82.
        reward = int((Decimal(amount) * Decimal(rate) / Decimal(10000))
                     .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        projected += reward
        lines.append({
            "category": cat, "spend": money(amount), "rate_bps": rate,
            "reward": money(reward),
            "matched_rule": (t or {}).get("source_quote"),
            "match": how,     # EXPLICIT | CATCH_ALL | NONE -- surfaced, never hidden
        })

    annualised = int(projected * 12 / months) if months else None
    fee = merged.get("annual_fee_minor") or 0
    gate_ok = months >= 6
    return {
        "file": file.filename,
        "card": target,
        "cards_found": names,
        "months_of_data": months,
        "tiers": tiers,
        "exclusions": merged.get("exclusions") or [],
        "conflicts": merged.get("conflicts") or [],
        "observed_reward": money(projected),
        "annualised_reward": money(annualised) if annualised is not None else None,
        "annual_fee": money(fee),
        "net_annual": money(annualised - fee) if annualised is not None else None,
        "lines": lines,
        # D-016d: below six cycles the engine will not issue a verdict, and neither do we.
        "verdict": None if not gate_ok else ("BENEFICIAL" if (annualised or 0) > fee
                                             else "NOT_BENEFICIAL"),
        "verdict_blocked": not gate_ok,
        "verdict_blocked_reason": (
            f"Only {months} month(s) of statements. A verdict needs at least 6 reward "
            "cycles so a single unusual month cannot drive the answer (D-016d)."
            if not gate_ok else None),
    }


@app.get("/api/accounts/{account_id}")
def account_detail(account_id: str, limit: int = 100):
    """Everything about one card: position, its statements, its recent spending.

    Statements are the point of this view -- selecting a card should show what the
    bank actually sent for it, month by month, with what each one contained.
    """
    from analyser import issuers as iss

    c = db()
    acct = c.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
    if not acct:
        # Might be an old identifier for a card that has since been merged (D-028e).
        alias = c.execute("SELECT account_id FROM account_aliases WHERE alias=?",
                          (account_id,)).fetchone()
        if alias:
            return account_detail(alias[0], limit)
        raise HTTPException(404, f"no account '{account_id}'")

    acct = dict(acct)
    cur = acct.get("currency") or "AED"

    pos = c.execute("SELECT * FROM v_position WHERE account_id=?", (account_id,)).fetchone()
    position = dict(pos) if pos else None
    if position:
        for k in ("closing_balance", "total_payment_due", "minimum_due",
                  "credit_limit", "available_limit"):
            position[k] = money(position[k], cur) if position[k] is not None else None

    statements = []
    for r in rows(c.execute(
        "SELECT d.document_id, d.file_name, d.statement_date, d.period_start,"
        "       d.period_end, d.payment_due_date, d.status, d.reject_reason,"
        "       d.page_count, d.parser_name,"
        "       (SELECT COUNT(*) FROM transactions_raw t"
        "         WHERE t.document_id=d.document_id) txns,"
        "       s.purchases_debits, s.payments_credits, s.closing_balance,"
        "       s.total_payment_due, s.credit_limit,"
        "       g.message_id, g.subject, g.sender, g.received_at"
        "  FROM documents d"
        "  LEFT JOIN statement_summary s ON s.document_id=d.document_id"
        "  LEFT JOIN gmail_messages g ON g.file_name = d.file_name"
        " WHERE d.account_id=? ORDER BY COALESCE(d.statement_date, d.file_name) DESC",
        (account_id,))
    ):
        for k in ("purchases_debits", "payments_credits", "closing_balance",
                  "total_payment_due", "credit_limit"):
            r[k] = money(r[k], cur) if r[k] is not None else None
        # A link straight back to the email the statement arrived in (D-035).
        r["email_url"] = (f"https://mail.google.com/mail/u/0/#all/{r['message_id']}"
                          if r.get("message_id") else None)
        statements.append(r)

    spend_rows = []
    for r in rows(c.execute(
        "SELECT txn_id, txn_date, merchant, category, amount_minor"
        "  FROM v_spend WHERE account_id=? ORDER BY txn_date DESC LIMIT ?",
        (account_id, limit))
    ):
        r["amount"] = money(-r.pop("amount_minor"), cur)
        spend_rows.append(r)

    totals = c.execute(
        "SELECT COALESCE(SUM(-amount_minor),0) spend, COUNT(*) n,"
        "       COUNT(DISTINCT substr(txn_date,1,7)) months"
        "  FROM v_spend WHERE account_id=?", (account_id,)).fetchone()

    rewards = []
    for r in rows(c.execute(
        "SELECT * FROM reward_statements WHERE account_id=?"
        " ORDER BY cycle_end DESC LIMIT 12", (account_id,))
    ):
        unit = r.get("reward_unit") or "POINTS"
        for k in ("spend_minor", "earned", "opening_balance", "closing_balance"):
            r[k] = money(r[k], unit) if r.get(k) is not None else None
        rewards.append(r)

    issuer = iss.by_id(acct["issuer"].lower().replace(" ", "_")) if acct.get("issuer") else iss.UNKNOWN
    return {
        "account": {**acct, "issuer_name": issuer.name if issuer is not iss.UNKNOWN
                    else acct.get("issuer")},
        "position": position,
        "statements": statements,
        "transactions": spend_rows,
        "totals": {"spend": money(totals["spend"], cur), "transactions": totals["n"],
                   "months": totals["months"]},
        "rewards": rewards,
    }


# ---------------------------------------------------------------- statement library
# Uploaded statements live in data/statements/ -- local, gitignored, user-owned.
# `forget` deletes the file along with its rows (D-028i as amended by D-033).

STATEMENT_DIR = os.path.join(ROOT, "data", "statements")
# Only the managed library. sample_statements/ holds the hand-supplied originals of
# statements Gmail has since downloaded; scanning both ingested every statement twice
# under two document ids, which is what made every card appear twice.
EXTRA_DIRS: list = []


def _library_paths():
    seen, out = set(), []
    for d in [STATEMENT_DIR] + EXTRA_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.lower().endswith(".pdf") and name not in seen:
                seen.add(name)
                out.append(os.path.join(d, name))
    return out


@app.get("/api/statements/library")
def library():
    """The statement library, GROUPED BY BANK.

    Bank is the unit the user thinks in: passwords, accounts and parsers are all
    per-issuer (D-036), so a flat file list forces them to do the grouping in their
    head. Each bank reports its own read/rejected/pending counts and password state.
    """
    from analyser import issuers as iss
    from analyser.pdfaccess import is_encrypted, try_password
    from analyser.secrets import all_passwords, get_password

    try:
        c = db()
        known = {r["source_ref"]: dict(r) for r in c.execute(
            "SELECT source_ref, document_id, status, reject_reason, account_id,"
            "       statement_date,"
            "       (SELECT COUNT(*) FROM transactions_raw t"
            "         WHERE t.document_id = d.document_id) txns"
            "  FROM documents d")}
    except HTTPException:
        known = {}

    stored = all_passwords()
    banks: dict = {}
    for path in _library_paths():
        name = os.path.basename(path)
        row = known.get(path) or {}
        issuer = iss.resolve(parser_name=None, file_name=name)
        b = banks.setdefault(issuer.id, {
            "issuer_id": issuer.id, "name": issuer.name,
            "has_parser": issuer.parser is not None,
            "has_password": get_password(issuer.id) is not None,
            "total": 0, "read": 0, "rejected": 0, "pending": 0,
            "locked": 0, "transactions": 0, "files": [],
        })
        locked = is_encrypted(path) and not any(try_password(path, pw) for _l, pw in stored)
        status = row.get("status")
        b["total"] += 1
        b["transactions"] += row.get("txns") or 0
        if status == "RECONCILED":
            b["read"] += 1
        elif status == "REJECTED":
            b["rejected"] += 1
        else:
            b["pending"] += 1
        if locked:
            b["locked"] += 1
        b["files"].append({
            "file_name": name, "status": status, "locked": locked,
            "statement_date": row.get("statement_date"),
            "reject_reason": row.get("reject_reason"),
            "txns": row.get("txns"),
            "size_bytes": os.stat(path).st_size,
        })

    for b in banks.values():
        b["files"].sort(key=lambda f: f["file_name"], reverse=True)

    rows = sorted(banks.values(), key=lambda b: (-b["pending"] - b["rejected"], b["name"]))
    return {
        "banks": rows,
        "directory": STATEMENT_DIR,
        "totals": {
            "files": sum(b["total"] for b in rows),
            "read": sum(b["read"] for b in rows),
            "rejected": sum(b["rejected"] for b in rows),
            "pending": sum(b["pending"] for b in rows),
            "locked": sum(b["locked"] for b in rows),
            "transactions": sum(b["transactions"] for b in rows),
        },
    }


@app.post("/api/statements/upload")
async def upload_statements(files: List[UploadFile] = File(...)):
    """Accept statement PDFs and place them in the library. Does not process them --
    processing is a separate, explicit action so nothing is ingested by surprise."""
    os.makedirs(STATEMENT_DIR, exist_ok=True)
    saved, rejected = [], []
    for f in files:
        raw = await f.read()
        if not raw[:5].startswith(b"%PDF"):
            rejected.append({"file_name": f.filename, "reason": "not a PDF"})
            continue
        safe = os.path.basename(f.filename or "statement.pdf").replace("/", "_")
        dest = os.path.join(STATEMENT_DIR, safe)
        stem, ext = os.path.splitext(safe)
        n = 1
        while os.path.exists(dest) and open(dest, "rb").read() != raw:
            dest = os.path.join(STATEMENT_DIR, f"{stem}-{n}{ext}")   # never overwrite
            n += 1
        with open(dest, "wb") as fh:
            fh.write(raw)
        saved.append({"file_name": os.path.basename(dest), "size_bytes": len(raw)})
    return {"saved": saved, "rejected": rejected,
            "note": "Nothing is analysed until you press Process."}


@app.post("/api/statements/process")
def process_statements():
    """Parse, reconcile and store every unprocessed statement in the library.

    Idempotent (D-003): files already ingested are reported UNCHANGED and re-running
    inserts nothing. Snapshots the database first (D-028j).
    """
    from analyser import db as dbmod
    from analyser.cli import _derive_account, _ensure_account, _PARSER_ISSUERS
    from analyser.ingest import ingest_document
    from analyser.parsers import DocumentEncrypted, detect_parser

    paths = _library_paths()
    if not paths:
        return {"results": [], "note": "No statement files found."}

    if os.path.exists(DB_PATH):
        dbmod.snapshot(DB_PATH)
    conn = dbmod.connect(DB_PATH)
    dbmod.migrate(conn)

    results = []
    for path in paths:
        name = os.path.basename(path)
        try:
            parser_name = detect_parser(path)
        except DocumentEncrypted:
            results.append({"file_name": name, "status": "ENCRYPTED",
                            "detail": "This PDF needs a password. Add it to the macOS "
                                      "Keychain, then process again. It is never typed "
                                      "here and never echoed."})
            continue
        except Exception as exc:                                   # noqa: BLE001
            results.append({"file_name": name, "status": "UNREADABLE",
                            "detail": type(exc).__name__})
            continue

        if parser_name is None:
            results.append({"file_name": name, "status": "UNSUPPORTED",
                            "detail": "No parser recognises this issuer. A parser is "
                                      "written per bank format; nothing is guessed."})
            continue

        account_id, product, masked, currency, acct_type = _derive_account(path, parser_name)
        account_id = _ensure_account(conn, account_id,
                                     issuer=_PARSER_ISSUERS.get(parser_name,
                                                                parser_name.upper()),
                                     product=product, masked=masked, currency=currency,
                                     parser_name=parser_name, account_type=acct_type)
        try:
            r = ingest_document(path, conn=conn, account_id=account_id)
        except Exception as exc:                                   # noqa: BLE001
            results.append({"file_name": name, "status": "FAILED",
                            "detail": f"{type(exc).__name__}: {exc}"})
            continue

        if not r["inserted"]:
            results.append({"file_name": name, "status": "UNCHANGED",
                            "detail": r.get("reason"), "account_id": account_id})
            continue
        results.append({
            "file_name": name, "status": r["status"], "account_id": account_id,
            "transactions": r.get("transactions"), "pages": r.get("pages"),
            "detail": r.get("reject_reason"),
        })
    conn.close()
    ok = sum(1 for r in results if r["status"] == "RECONCILED")
    return {"results": results, "reconciled": ok, "total": len(results)}


# ---------------------------------------------------------------- pdf passwords

class PasswordBody(BaseModel):
    password: str
    label: str = ""          # e.g. "FAB" -- what this password belongs to


@app.get("/api/statements/passwords")
def password_status():
    """Locked statements grouped BY ISSUER (analyser.issuers), because that is how
    passwords actually work: one per cardholder per bank, reused every month (D-034).

    Passwords are never returned -- only issuer ids and counts (D-015).
    """
    from analyser import issuers as iss
    from analyser.pdfaccess import is_encrypted, try_password
    from analyser.secrets import all_passwords, get_password

    stored = all_passwords()
    banks: dict = {}
    for path in _library_paths():
        if not is_encrypted(path):
            continue
        name = os.path.basename(path)
        issuer = iss.resolve(file_name=name)
        opened_by = next((label for label, pw in stored if try_password(path, pw)), None)
        b = banks.setdefault(issuer.id, {
            "issuer_id": issuer.id, "name": issuer.name,
            "total": 0, "unlocked": 0, "examples": [],
            # Whether a password is SAVED is separate from whether it WORKS: a bank
            # can change its scheme, leaving a stored secret that no longer opens
            # anything. Both states are reported so the UI can say which it is.
            "has_password": get_password(issuer.id) is not None,
        })
        b["total"] += 1
        if opened_by:
            b["unlocked"] += 1
        elif len(b["examples"]) < 3:
            b["examples"].append(name)

    rows = sorted(banks.values(), key=lambda r: (r["unlocked"] == r["total"], r["name"]))
    return {
        "banks": rows,
        "locked_banks": sum(1 for r in rows if r["unlocked"] < r["total"]),
        "locked_files": sum(r["total"] - r["unlocked"] for r in rows),
    }


@app.post("/api/statements/password")
def add_statement_password(body: PasswordBody):
    """Store one issuer's password and report what it unlocked.

    `label` is an issuer id from analyser.issuers. Scoping the attempt to that issuer
    stops a password shared across banks being attributed to the wrong one.
    """
    from analyser import issuers as iss
    from analyser.pdfaccess import is_encrypted, try_password
    from analyser.secrets import set_password

    locked = [p for p in _library_paths() if is_encrypted(p)]
    if body.label:
        issuer = iss.by_id(body.label)
        if issuer is iss.UNKNOWN:
            raise HTTPException(400, f"Unknown issuer '{body.label}'.")
        locked = [p for p in locked
                  if iss.resolve(file_name=os.path.basename(p)).id == issuer.id]

    opens = [os.path.basename(p) for p in locked if try_password(p, body.password)]
    if not opens:
        who = iss.by_id(body.label).name if body.label else "any locked statement"
        raise HTTPException(400, f"That password does not open {who}.")

    label = body.label or iss.resolve(file_name=opens[0]).id
    if not set_password(label, body.password):
        raise HTTPException(500, "Could not save to the macOS Keychain.")
    return {"issuer_id": label, "name": iss.by_id(label).name,
            "unlocked": len(opens), "files": opens[:50],
            "note": f"Saved for {iss.by_id(label).name} — unlocks {len(opens)} "
                    f"statement{'s' if len(opens) != 1 else ''}. Press Process to read them."}


@app.delete("/api/statements/password/{label}")
def clear_statement_password(label: str):
    from analyser.secrets import delete_password
    return {"label": label, "removed": delete_password(label)}


# ---------------------------------------------------------------- gmail intake

@app.get("/api/gmail/status")
def gmail_status():
    from analyser import gmail as gm
    check = gm.check_client_secret()
    out = {"configured": bool(check.get("ok")), "connected": gm.is_connected(),
           "scope": gm.SCOPES[0], "setup_doc": os.path.join(gm.GMAIL_DIR, "README.md"),
           "credential_path": gm.CLIENT_SECRET,
           "credential_check": check, "email": None}
    if out["connected"]:
        try:
            out.update(gm.profile())
        except Exception as exc:                                  # noqa: BLE001
            out["error"] = type(exc).__name__
    return out


@app.post("/api/gmail/connect")
def gmail_connect():
    """Run the desktop OAuth consent flow. Opens a browser on THIS machine."""
    from analyser import gmail as gm
    try:
        return {"connected": True, **gm.connect()}
    except gm.GmailNotConfigured as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:                                      # noqa: BLE001
        raise HTTPException(500, f"{type(exc).__name__}: {exc}")


@app.post("/api/gmail/disconnect")
def gmail_disconnect():
    from analyser import gmail as gm
    return {"disconnected": gm.disconnect()}


@app.get("/api/gmail/search")
def gmail_search(q: str = "", limit: int = 25):
    """Preview matching emails WITHOUT downloading anything."""
    from analyser import gmail as gm
    try:
        return gm.search(q or None, limit)
    except gm.GmailNotConfigured as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/gmail/download")
def gmail_download(q: str = "", limit: int = 25):
    """Download matching PDF attachments into the statement library.

    Downloading does NOT process them -- that stays an explicit action (D-033).
    """
    from analyser import gmail as gm
    try:
        return gm.download(q or None, limit)
    except gm.GmailNotConfigured as exc:
        raise HTTPException(400, str(exc))


# ---------------------------------------------------------------- wallet & plan
#
# The routing plan is the product's primary output, and it is deliberately gated
# on a HUMAN-CONFIRMED wallet (D-027). Rule extraction reads a rate and the
# sentence it came from, but it will not guess which of your categories that
# sentence covers -- "5% cashback on dining spends" is a quote, not a mapping.
# Confirming that mapping is what these endpoints are for; until it exists the
# engine refuses to produce a plan rather than inventing one (P1, P3).


def _wallet_path():
    from analyser.cli import DEFAULT_WALLET_PATH
    return DEFAULT_WALLET_PATH


@app.get("/api/wallet")
def get_wallet():
    """What has been confirmed, and which cards are still waiting on it."""
    path = _wallet_path()
    config = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            try:
                config = json.load(handle)
            except json.JSONDecodeError as exc:
                raise HTTPException(500, f"{path} is not valid JSON: {exc}")

    confirmed = {str(spec.get("account_id") or spec.get("card_id")): spec
                 for spec in (config.get("cards") or [])}

    c = db()
    accounts = rows(c.execute(
        "SELECT a.account_id, a.issuer, a.product_name, a.currency, a.account_type,"
        "       (SELECT COUNT(*) FROM transactions t"
        "         WHERE t.account_id = a.account_id) txns"
        "  FROM accounts a"
        " WHERE a.account_type = 'CREDIT_CARD'"
        " ORDER BY a.issuer, a.product_name"))
    for a in accounts:
        spec = confirmed.get(a["account_id"])
        a["confirmed"] = spec is not None
        a["tier_count"] = len((spec or {}).get("reward", {}).get("tiers") or [])
        a["annual_fee"] = money((spec or {}).get("annual_fee_minor"),
                                a["currency"] or "AED") if spec else None

    return {
        "path": path,
        "exists": os.path.exists(path),
        "cards": config.get("cards") or [],
        "routing": config.get("routing") or {"merchant_locked": [], "direct_debit": []},
        "accounts": accounts,
        "confirmed_count": len(confirmed),
    }


class WalletBody(BaseModel):
    cards: List[dict]
    routing: Optional[dict] = None


@app.put("/api/wallet")
def put_wallet(body: WalletBody):
    """Write the confirmed wallet, but only if the engine can build every card.

    Validation runs through the same `_build_card` the CLI uses, so a spec that
    is accepted here cannot fail later inside `plan`.
    """
    from analyser.cli import _build_card

    if not body.cards:
        raise HTTPException(400, "A wallet needs at least one card.")

    for spec in body.cards:
        card_id = spec.get("card_id") or spec.get("account_id")
        if not card_id:
            raise HTTPException(400, "Every card needs a card_id.")
        tiers = (spec.get("reward") or {}).get("tiers") or []
        if not tiers:
            raise HTTPException(400, f"{card_id} has no reward tiers confirmed.")
        try:
            _build_card(spec)
        except Exception as exc:                       # noqa: BLE001 - reported verbatim
            raise HTTPException(400, f"{card_id}: {exc}")

    config = {"cards": body.cards,
              "routing": body.routing or {"merchant_locked": [], "direct_debit": []}}

    path = _wallet_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)                              # atomic: never a half-written wallet
    return {"path": path, "cards": len(body.cards),
            "note": f"Confirmed {len(body.cards)} card(s). A plan can be produced now."}


def _money_out(m):
    """Domain Money -> the wire shape. Never divide by 100 on the client."""
    if m is None:
        return None
    return {"minor": int(m.minor), "currency": m.currency, "exponent": m.exponent}


@app.get("/api/plan")
def get_plan(months: int = 12):
    """The routing plan, or exactly what is missing before there can be one."""
    from analyser.cli import WalletError, load_txns, load_wallet
    from analyser.domain.model import AnalysisHorizon
    from analyser.domain.routing import route

    path = _wallet_path()
    try:
        cards, specs, config = load_wallet(path)
    except WalletError as exc:
        return {"ready": False, "reason": "NO_WALLET", "detail": str(exc),
                "wallet_path": path, "plan": None}

    account_to_card = {}
    for card in cards:
        account_to_card[specs[card.card_id].get("account_id", card.card_id)] = card.card_id

    c = db()
    txns = load_txns(c, sorted(account_to_card),
                     account_to_card=account_to_card,
                     routing_config=config.get("routing") or {})
    if not txns:
        return {"ready": False, "reason": "NO_TRANSACTIONS",
                "detail": "No reconciled transactions on the confirmed cards yet.",
                "wallet_path": path, "plan": None}

    start = min(t.txn_date for t in txns)[:8] + "01"
    horizon = AnalysisHorizon(start=start, months=months)
    plan = route(txns, cards, horizon)

    moves = [{
        "category": m.category,
        "from_card": m.from_card,
        "to_card": m.to_card,
        "monthly_spend": _money_out(m.monthly_spend),
        "annual_gain": _money_out(m.annual_gain),
    } for m in plan.moves]

    # How few changes capture most of the benefit -- the plan is only worth
    # following if the first handful of moves carry it.
    total = sum(m["annual_gain"]["minor"] for m in moves) or 1
    running, headline = 0, 0
    for i, m in enumerate(moves, start=1):
        running += m["annual_gain"]["minor"]
        if not headline and running * 100 >= total * 80:
            headline = i

    return {
        "ready": True,
        "reason": None,
        "wallet_path": path,
        "horizon": {"start": horizon.start, "months": horizon.months},
        "cards": [c_.card_id for c_ in cards],
        "transactions_considered": len(txns),
        "plan": {
            "value_unchanged": _money_out(plan.value_unchanged),
            "value_if_routed": _money_out(plan.value_if_routed),
            "annual_gain": _money_out(plan.annual_gain),
            "moves": moves,
            "moves_for_80pct": headline,
        },
    }


# ---------------------------------------------------------------- import warmup
#
# Endpoints import their heavy dependencies lazily, which keeps startup quick but
# is not thread-safe: sync endpoints run in a threadpool, so two requests can
# import the same package while it is still initialising and one of them sees a
# half-built entry in sys.modules. That surfaced as
#
#     KeyError: 'analyser.domain'   (from `from analyser.domain.routing import route`)
#
# and, because an unhandled exception bypasses CORSMiddleware, the browser only
# ever saw "No 'Access-Control-Allow-Origin' header" -- a CORS message for what
# was really an import race.
#
# Importing them once here, at module scope and single-threaded, keeps the lazy
# style at the call sites while guaranteeing every module is fully built before
# the first request is served.
def _warm_imports() -> None:
    import importlib

    for name in (
        "analyser.cli",
        "analyser.corrections",
        "analyser.domain.model",
        "analyser.domain.rewards",
        "analyser.domain.routing",
        "analyser.domain.value",
        "analyser.ingest",
        "analyser.parsers",
        "analyser.pdfaccess",
        "analyser.secrets",
    ):
        try:
            importlib.import_module(name)
        except Exception:                                  # noqa: BLE001
            # An optional dependency missing here must not stop the API booting;
            # the endpoint that needs it will raise its own error, in context.
            logging.getLogger("analyser.api").debug(
                "could not warm %s", name, exc_info=True)


_warm_imports()


@app.get("/api/health")
def health():
    return {"ok": True, "db": os.path.exists(DB_PATH), "db_path": DB_PATH}


def main():
    import uvicorn
    print(f"Spend Tracker API — http://{HOST}:{PORT}/api/docs  (localhost only)")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
