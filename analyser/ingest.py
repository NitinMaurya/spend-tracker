"""Document ingestion and the reconciliation gate (D-004, D-018)."""
import hashlib
import os
import re
from datetime import datetime, timezone
from decimal import Decimal

from analyser.ids import document_id, raw_id

# D-018: dispositions that carry no parseable content, so they must not dilute
# (or inflate) the coverage ratio. A statement that is 90% terms & conditions is
# not 90% unparsed.
EXCLUDED_DISPOSITIONS = ("BOILERPLATE", "UNREADABLE")
UNPARSED_DISPOSITION = "UNPARSED"


def reconcile(summary, transactions):
    """D-004: extracted rows must sum to the issuer's printed totals.
    Returns (ok: bool, reason: str|None).

    Exact integer-minor-unit equality on both sides — one fil off is a failure.
    """
    debits = 0    # money out, stored negative; compared as a positive magnitude
    credits = 0   # money in, stored positive
    for txn in transactions or ():
        amount = txn["amount_minor"] if isinstance(txn, dict) else txn.amount_minor
        if amount is None:
            continue
        if amount < 0:
            debits += -amount
        else:
            credits += amount

    expected_debits = summary.get("purchases_debits") or 0
    expected_credits = summary.get("payments_credits") or 0

    problems = []
    if debits != expected_debits:
        problems.append(
            f"debit mismatch: extracted {debits} != statement {expected_debits} "
            f"(delta {debits - expected_debits})"
        )
    if credits != expected_credits:
        problems.append(
            f"credit mismatch: extracted {credits} != statement {expected_credits} "
            f"(delta {credits - expected_credits})"
        )
    if problems:
        return False, "; ".join(problems)
    return True, None




def parse_coverage(lines):
    """D-018: proportion of non-boilerplate lines a parser understood."""
    considered = 0
    unparsed = 0
    for line in lines or ():
        disposition = (line.get("disposition") if isinstance(line, dict)
                       else getattr(line, "disposition", None))
        disposition = (disposition or "").upper()
        if disposition in EXCLUDED_DISPOSITIONS:
            continue
        considered += 1
        if disposition == UNPARSED_DISPOSITION:
            unparsed += 1

    if considered == 0:
        pct = Decimal(0)
    else:
        pct = (Decimal(unparsed) * 100 / Decimal(considered)).quantize(Decimal("0.01"))
    return {
        "total_lines": len(lines or ()),
        "considered_lines": considered,
        "unparsed_lines": unparsed,
        "unparsed_pct": pct,
    }


# ---------------------------------------------------------------------------
# raw extraction (D-018)
# ---------------------------------------------------------------------------

#: Vertical tolerance, in points, for deciding that two words share a baseline.
#: Same value the FAB parser uses, so the lines stored here are the lines the
#: parser saw.
LINE_TOLERANCE = 2.5

#: Minimum indent, in points, before a line is read as a continuation of the
#: transaction above it rather than a new block.
CONTINUATION_INDENT = 4.0

# Marker sets for line classification. Matched case-insensitively against the
# line text. Deliberately phrase-level: a bare "credit" appears in marketing
# copy as often as in a column header.
_SUMMARY_MARKERS = (
    "summary details", "statement summary", "previous balance", "opening balance",
    "closing balance", "purchases/debits", "payments/credits", "total payment due",
    "minimum payment due", "minimum amount due", "current balance", "credit limit",
    "available limit", "finance charges", "cash advances", "new balance",
)
_REWARD_MARKERS = (
    "reward", "cashback", "cash back", "air miles", "points earned",
    "points balance", "loyalty",
)
_BOILERPLATE_MARKERS = (
    "important information", "terms and conditions", "e. & o. e", "e.&o.e",
    "contact centre", "contact center", "customer service", "lost or stolen",
    "interest rate", "profit rate", "remittance", "please complete",
    "see reverse side", "authorized signature", "authorised signature",
    "objection", "www.", "@", "p.o. box", "po box", "cheque", "sms",
    "mobile app", "mobile banking", "working days", "standing instructions",
    "no objection", "complaint",
)
_HEADER_MARKERS = (
    "statement date", "payment due date", "due date", "main card", "card number",
    "card product", "card type", "account number", "transaction details",
    "transaction date", "posting date", "original currency", "description",
    "page ", "statement of", "account summary", "date date", "debit", "credit",
)

_AMOUNTISH = re.compile(r"^[(\-+]?[\d,]+(?:\.\d+)?\)?(?:\s*CR)?$", re.I)
_DATEISH = re.compile(r"^\d{1,4}[-/]\d{1,2}[-/]\d{1,4}$")


#: A glyph-tripling font renders every letter three times ("WWWaaarrrnnn").
#: Three such runs in one line is well past what English spelling produces.
_TRIPLED = re.compile(r"([A-Za-z])\1\1")


def _is_unreadable(text):
    """Broken font encoding: no ToUnicode map, mojibake, or glyph tripling."""
    if "(cid:" in text or "�" in text:
        return True
    return len(_TRIPLED.findall(text)) >= 3


def _is_figures_only(text):
    """A bare row of numbers -- it belongs to whatever block introduced it."""
    tokens = text.split()
    if not tokens:
        return False
    return all(_AMOUNTISH.match(t) or _DATEISH.match(t) for t in tokens)


def _matches(text, markers):
    low = text.lower()
    return any(marker in low for marker in markers)


def classify_line(text, *, is_transaction=False, previous=None, indented=False):
    """Give a visual line exactly one disposition (D-018). Never returns None.

    Order is significant: a line the parser actually consumed is a TRANSACTION
    whatever else it contains, encoding failure is decided before content, and
    prose markers are checked before column-header markers because marketing
    copy is full of the words ("credit", "debit") that headers use.
    """
    if is_transaction:
        return "TRANSACTION"
    if _is_unreadable(text):
        return "UNREADABLE"
    if not any(ch.isalnum() for ch in text):
        # Rules, dotted separators, stray underscores: ink, not content.
        return "BOILERPLATE"
    if _is_figures_only(text) and previous in ("SUMMARY", "REWARD", "HEADER"):
        return previous
    # Totals and rewards outrank the continuation rule: an issuer's own totals
    # row sits directly under the last transaction and is indented like one.
    if _matches(text, _SUMMARY_MARKERS) or text.split()[0].lower() == "total":
        return "SUMMARY"
    if _matches(text, _REWARD_MARKERS):
        return "REWARD"
    if previous in ("TRANSACTION", "CONTINUATION") and indented:
        return "CONTINUATION"
    if _matches(text, _BOILERPLATE_MARKERS):
        return "BOILERPLATE"
    if _matches(text, _HEADER_MARKERS):
        return "HEADER"
    return UNPARSED_DISPOSITION


def _page_lines(words, tol=LINE_TOLERANCE):
    """Group extracted words into visual lines, left-to-right, top-to-bottom."""
    rows = {}
    for word in words:
        rows.setdefault(round(word["top"] / tol), []).append(word)
    return [sorted(rows[key], key=lambda w: w["x0"]) for key in sorted(rows)]


def extract_pages(path):
    """Everything pdfplumber can see, per page: text, words, visual lines.

    This is the record D-018 requires. Coordinates are kept because they carry
    information the text does not -- FAB's Debit and Credit columns hold
    textually identical numbers.
    """
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pdfplumber

        pages = []
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(
                    use_text_flow=False,
                    keep_blank_chars=False,
                    extra_attrs=["fontname", "size"],
                )
                lines = [
                    {
                        "line_index": index,
                        "raw_text": " ".join(w["text"] for w in row),
                        "top": row[0]["top"],
                        "x0": min(w["x0"] for w in row),
                    }
                    for index, row in enumerate(_page_lines(words))
                ]
                pages.append({
                    "page_number": page_number,
                    "width": page.width,
                    "height": page.height,
                    "rotation": page.rotation or 0,
                    "layout_text": page.extract_text(layout=True) or "",
                    "plain_text": page.extract_text() or "",
                    "words": words,
                    "lines": lines,
                })
    return pages


def _parse(module, path):
    """Call a parser and normalise its return shape.

    Older parsers return (header, summary, transactions); newer ones append a
    rewards list. Both are supported so a parser can gain reward extraction
    without a coordinated change here.
    """
    result = module.parse(path)
    if len(result) == 4:
        header, summary, transactions, rewards = result
    else:
        header, summary, transactions = result
        rewards = []
    return (header or {}, summary or {}, list(transactions or ()), list(rewards or ()))


def _normalise_text(text):
    return " ".join((text or "").split())


def _dispose_lines(pages, transactions):
    """Attach a disposition (and, where it exists, a transaction) to every line.

    Matching is by (page, whitespace-normalised text) and consumes the queue in
    order, so FAB's two identical `CAREEM PLUS AED 1.00` rows bind to the two
    distinct lines that produced them rather than both to the first (D-003).
    """
    pending = {}
    for index, txn in enumerate(transactions):
        text = _normalise_text(txn.get("raw_text"))
        if text:
            pending.setdefault((txn.get("page_number"), text), []).append(index)

    rows = []
    for page in pages:
        previous = None
        transaction_x0 = None
        for line in page["lines"]:
            queue = pending.get((page["page_number"], _normalise_text(line["raw_text"])))
            txn_index = queue.pop(0) if queue else None
            indented = (transaction_x0 is not None
                        and line["x0"] > transaction_x0 + CONTINUATION_INDENT)
            disposition = classify_line(
                line["raw_text"],
                is_transaction=txn_index is not None,
                previous=previous,
                indented=indented,
            )
            rows.append({
                "page_number": page["page_number"],
                "line_index": line["line_index"],
                "raw_text": line["raw_text"],
                "top": line["top"],
                "disposition": disposition,
                "txn_index": txn_index,
            })
            if disposition == "TRANSACTION":
                transaction_x0 = line["x0"]
            elif disposition != "CONTINUATION":
                transaction_x0 = None
            previous = disposition
    return rows


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

_SUMMARY_COLUMNS = (
    "opening_balance", "purchases_debits", "cash_advances", "finance_charges",
    "payments_credits", "closing_balance", "total_payment_due", "minimum_due",
    "credit_limit", "available_limit",
)
_REWARD_COLUMNS = (
    "reward_program",
    "reward_unit", "cycle_start", "cycle_end", "category_label", "spend_minor",
    "rate_bps", "opening_balance", "earned", "adjusted", "redeemed",
    "closing_balance", "source_page",
)


def _store_pages(conn, doc_id, pages):
    for page in pages:
        conn.execute(
            "INSERT INTO document_pages (document_id,page_number,width,height,"
            "rotation,layout_text,plain_text,word_count) VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, page["page_number"], page["width"], page["height"],
             page["rotation"], page["layout_text"], page["plain_text"],
             len(page["words"])),
        )
        conn.executemany(
            "INSERT INTO document_words (document_id,page_number,word_index,text,"
            "x0,x1,top,bottom,font_name,font_size) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (doc_id, page["page_number"], index, word["text"],
                 float(word["x0"]), float(word["x1"]),
                 float(word["top"]), float(word["bottom"]),
                 word.get("fontname"),
                 float(word["size"]) if word.get("size") is not None else None)
                for index, word in enumerate(page["words"])
            ],
        )


def _store_raw_transactions(conn, doc_id, account_id, transactions):
    """Append the evidence layer and return raw_id per transaction (None if unusable).

    `seq` is the ordinal within the statement and is the component of the id that
    keeps a genuine same-day duplicate distinct from a double-insert (D-003).
    """
    ids = []
    for seq, txn in enumerate(transactions, start=1):
        amount = txn.get("amount_minor")
        if amount is None:
            ids.append(None)
            continue
        rid = raw_id(account_id, txn.get("txn_date"), txn.get("posting_date"),
                     amount, txn.get("raw_description"), seq)
        conn.execute(
            "INSERT OR IGNORE INTO transactions_raw (raw_id,document_id,account_id,"
            "page_number,line_index,raw_text,txn_date,posting_date,raw_description,"
            "amount_minor,currency,fx_amount_minor,fx_currency) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, doc_id, account_id, txn.get("page_number") or 1, seq,
             txn.get("raw_text") or txn.get("raw_description") or "",
             txn.get("txn_date"), txn.get("posting_date"),
             txn.get("raw_description") or "", amount,
             txn.get("currency") or "AED",
             txn.get("fx_amount_minor"), txn.get("fx_currency")),
        )
        ids.append(rid)
    return ids


def _store_transactions(conn, account_id, issuer, transactions, raw_ids):
    """The normalized layer. Only reached once the document has reconciled (D-004)."""
    from analyser.normalize import categorize, classify_txn_type, normalize_merchant
    from analyser.corrections import load_alias_map, load_category_map

    # User corrections are authoritative and permanent (D-001, spec §18).
    alias_map = load_alias_map()
    category_map = load_category_map()

    stored = 0
    for txn, rid in zip(transactions, raw_ids):
        if rid is None:
            continue
        txn_date = txn.get("txn_date") or txn.get("posting_date")
        if not txn_date:
            # transactions.txn_date is NOT NULL: an undated row stays raw-only
            # rather than being given a fabricated date.
            continue
        description = txn.get("raw_description")
        amount = txn["amount_minor"]
        merchant, _city, merchant_confidence = normalize_merchant(description, issuer, alias_map=alias_map)
        category, category_confidence = categorize(merchant, description, category_map=category_map)
        conn.execute(
            "INSERT OR IGNORE INTO transactions (txn_id,account_id,txn_date,posting_date,"
            "amount_minor,currency,system_txn_type,system_merchant,system_category,"
            "category_confidence) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, account_id, txn_date, txn.get("posting_date"), amount,
             txn.get("currency") or "AED",
             classify_txn_type(description, amount, issuer),
             merchant, category,
             category_confidence if category else merchant_confidence),
        )
        stored += 1
    return stored


def _store_lines(conn, doc_id, line_rows, raw_ids):
    conn.executemany(
        "INSERT INTO document_lines (document_id,page_number,line_index,raw_text,"
        "top,disposition,raw_id) VALUES (?,?,?,?,?,?,?)",
        [
            (doc_id, row["page_number"], row["line_index"], row["raw_text"],
             row["top"], row["disposition"],
             raw_ids[row["txn_index"]] if row["txn_index"] is not None else None)
            for row in line_rows
        ],
    )


def _store_summary(conn, doc_id, summary):
    present = [c for c in _SUMMARY_COLUMNS if summary.get(c) is not None]
    columns = ",".join(["document_id"] + present)
    placeholders = ",".join("?" * (len(present) + 1))
    conn.execute(
        f"INSERT INTO statement_summary ({columns}) VALUES ({placeholders})",
        [doc_id] + [summary[c] for c in present],
    )


def _store_rewards(conn, doc_id, account_id, rewards, default_unit):
    """The issuer's own printed reward figures -- ground truth for the engine.

    `reward_unit` is NOT NULL, and a cashback parser that only ever deals in one
    unit does not always print it on the row, so `default_unit` (the parser's
    declared unit, else the account currency) fills the gap.
    """
    for index, reward in enumerate(rewards):
        row = dict(reward)
        row.setdefault("reward_unit", default_unit)
        row = _normalise_reward(row)   # split programme name out of the unit
        present = [c for c in _REWARD_COLUMNS if row.get(c) is not None]
        reward_id = hashlib.sha256(
            f"{doc_id}|{index}|{row.get('category_label') or ''}".encode("utf-8")
        ).hexdigest()[:32]
        columns = ",".join(["reward_id", "document_id", "account_id"] + present)
        placeholders = ",".join("?" * (len(present) + 3))
        conn.execute(
            f"INSERT INTO reward_statements ({columns}) VALUES ({placeholders})",
            [reward_id, doc_id, account_id] + [row[c] for c in present],
        )


# ---------------------------------------------------------------------------
# ingestion
# ---------------------------------------------------------------------------

#: Issuers name their points programme in the unit field. The unit is what the
#: reward IS (points / miles / cash); the programme is whose points they are.
_REWARD_UNITS = {"AED", "POINTS", "MILES"}


def _normalise_reward(row):
    """Split a reward programme name out of the unit, leaving a storable unit.

    "PLUS_POINTS" (Emirates NBD) is POINTS from the Plus Points programme. Storing
    it verbatim violated the unit CHECK and lost five statements (D-024).
    """
    unit = (row.get("reward_unit") or "POINTS").upper().strip()
    if unit in _REWARD_UNITS:
        return row
    out = dict(row)
    out["reward_program"] = row.get("reward_program") or unit.replace("_", " ").title()
    out["reward_unit"] = (
        "MILES" if "MILE" in unit else "AED" if "CASH" in unit or "AED" in unit
        else "POINTS")
    return out


def ingest_document(path, *, conn, account_id, source_kind="LOCAL"):
    """Ingest one statement PDF. Idempotent (D-003), full raw capture (D-018).

    Re-ingesting a file whose bytes have already been seen is a no-op -- nothing
    is re-parsed, nothing is written, `inserted` is 0. That is what makes the
    Phase 2 Gmail poller safe to run repeatedly over the same mailbox.

    Everything else happens in a single transaction: the document, its pages,
    words and lines, the issuer's summary block, the raw transactions and any
    reward block either all land or none do. The normalized `transactions` rows
    are the exception -- they are written only when the extraction reconciles
    against the issuer's own totals (D-004), so a statement that does not close
    is recorded in full as evidence but contributes nothing to the analysis.
    """
    from analyser.parsers import detect_parser, get_parser

    path = os.path.abspath(str(path))
    with open(path, "rb") as handle:
        blob = handle.read()
    doc_id = document_id(blob)

    existing = conn.execute(
        "SELECT status, parser_name FROM documents WHERE document_id=?", (doc_id,)
    ).fetchone()
    if existing:
        return {
            "document_id": doc_id,
            "inserted": 0,
            "status": existing[0],
            "parser_name": existing[1],
            "transactions": 0,
            "reason": "already ingested (D-003)",
        }

    parser_name = detect_parser(path)
    if parser_name is None:
        raise ValueError(f"no parser recognises {os.path.basename(path)}")
    module = get_parser(parser_name)

    # `readable` yields a decrypted temp copy when the statement is password
    # protected and a password is stored (D-034); the copy is deleted on exit,
    # so an unlocked statement never persists. The document_id above is the hash
    # of the ORIGINAL bytes, so idempotency is unaffected by decryption.
    from analyser.pdfaccess import readable

    with readable(path) as usable:
        header, summary, transactions, rewards = _parse(module, usable)
        pages = extract_pages(usable)
    line_rows = _dispose_lines(pages, transactions)

    reconciled, reject_reason = reconcile(summary, transactions)
    status = "RECONCILED" if reconciled else "REJECTED"

    account = conn.execute(
        "SELECT issuer, currency FROM accounts WHERE account_id=?", (account_id,)
    ).fetchone()
    issuer = account[0] if account else None
    reward_unit = getattr(module, "REWARD_UNIT", None) or (
        account[1] if account else "AED")

    try:
        conn.execute(
            "INSERT INTO documents (document_id,account_id,source_kind,source_ref,"
            "file_name,parser_name,parser_version,statement_date,period_start,"
            "period_end,payment_due_date,page_count,ingested_at,status,reject_reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, account_id, source_kind, path, os.path.basename(path),
             getattr(module, "PARSER_NAME", parser_name),
             getattr(module, "PARSER_VERSION", 1),
             header.get("statement_date"), header.get("period_start"),
             header.get("period_end"), header.get("payment_due_date"), len(pages),
             datetime.now(timezone.utc).isoformat(), status, reject_reason),
        )
        _store_pages(conn, doc_id, pages)
        _store_summary(conn, doc_id, summary)
        # Raw rows are evidence and are kept even for a rejected statement
        # (D-018); document_lines points at them, so they go in first.
        raw_ids = _store_raw_transactions(conn, doc_id, account_id, transactions)
        _store_lines(conn, doc_id, line_rows, raw_ids)
        _store_rewards(conn, doc_id, account_id, rewards, reward_unit)
        stored = (_store_transactions(conn, account_id, issuer, transactions, raw_ids)
                  if reconciled else 0)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "document_id": doc_id,
        "inserted": 1,
        "status": status,
        "parser_name": parser_name,
        "file_name": os.path.basename(path),
        "pages": len(pages),
        "words": sum(len(page["words"]) for page in pages),
        "lines": len(line_rows),
        "transactions_raw": sum(1 for rid in raw_ids if rid),
        "transactions": stored,
        "rewards": len(rewards),
        "reconciled": reconciled,
        "reject_reason": reject_reason,
        "coverage": parse_coverage(line_rows),
    }
