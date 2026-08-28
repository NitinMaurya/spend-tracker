"""CBD (Commercial Bank of Dubai) statement parser.

Two CBD layouts arrive from estatements@cbdstatements.ae and both route here
(D-006 detection matches "commercial bank of dubai" / "customercare@cbd.ae"):

  * ``card``    -- "Statement of Account - Credit Card". Summary block of four
                   columns, then a ruled transaction table.
  * ``account`` -- the current-account statement ("Acct. Type : CIA",
                   "Balance Brought FWD", "ITEM COUNT" / "TURN OVER"). Not a
                   card at all, but it is a CBD document and it must be read
                   honestly rather than silently returning an empty summary --
                   a missing total is not a zero total.

Anything that is neither raises, because guessing a layout produces
plausible-but-wrong money.

Format notes
------------
* The document is BILINGUAL: the Arabic label and its English counterpart sit
  on the SAME physical baseline (the Arabic hugs the right margin, the English
  the middle band). Reading a line as text is therefore meaningless. Every
  value here is found by x-coordinate geometry over ASCII-only words (D-006).
* THREE date formats appear across the two layouts (D-020c): the card
  statement period is ISO ("From: 2026-07-13") while its statement date is
  DD-MM-YYYY ("12-08-2026"); the account statement uses DD/MM/YYYY
  ("Period :01/03/2026 - 31/03/2026"). All three are declared below; none is
  sniffed.
* A credit balance carries a trailing "CR" ("0.59 CR"), meaning the bank owes
  the cardholder, so the stored value is NEGATIVE. money.to_minor() applies
  the sign.
* A statement with no activity prints "No Transactions Available". That is a
  VALID statement, not a parse failure: transactions == [].

Column geometry, not token counting
-----------------------------------
Both tables are RULED. The vertical rules that cross the table give the exact
cell edges, so every body word is assigned to a column by which cell it falls
in, and the column's meaning comes from which cell its heading falls in. That
is the only approach that survives a description starting far left of the
"Transaction Description" heading, an amount that prints "0.66CR", or an
Arabic caption sharing the baseline. The table header row itself is located by
requiring ALL of its headings on one baseline IN ORDER -- the prose sentence
"...from Transaction Date till payment is received in full." above the summary
also contains the words "Transaction Date", and anchoring on the first match
of that pair is exactly the bug that made this parser find no transactions at
all on a statement that has them.

Internal adjustments (card layout)
----------------------------------
CBD prints its two movement columns as "Payments Received / Other Credits (-)
(Including internal adjustments)" and "New Purchases / Cash / Debits (+)
(Including internal adjustments)". On 2026-03-14 those columns read 112.46 and
360.33 while the transaction table itemises a single 247.87 purchase: an equal
and opposite pair of 112.46 is included in the totals but never itemised.

That is reconciled EXPLICITLY, never silently: only when the "(Including
internal adjustments)" caption is actually printed, only when the two gaps are
equal and non-negative (i.e. the unitemised entries cancel), and only when the
itemised rows already close the balance identity

    opening_balance - sum(signed amounts) == closing_balance

which is an INDEPENDENT check that a genuinely missed row would fail. The pair
is then emitted as two visible transactions so D-004 stays a real gate rather
than a tautology. Any other shape of gap raises.
"""
import re
import warnings

warnings.filterwarnings("ignore")
import pdfplumber

PARSER_NAME = "cbd"
PARSER_VERSION = 2

# D-020b / D-020c: formats are parser-declared, never sniffed.
NUMBER_FORMAT = "1,234.56"
DATE_FORMATS = ("YYYY-MM-DD", "DD-MM-YYYY", "DD/MM/YYYY")

ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
DMY_DATE = re.compile(r"^(\d{2})[-/](\d{2})[-/](\d{4})$")
AMOUNT = re.compile(r"^[\d,]+\.\d{2}$")
#: The per-card sub-heading inside the transaction table, e.g.
#: "4XXXXX******0000 -CARDHOLDER NAME". It is not a transaction and it is not a
#: continuation of the row above it.
CARD_SECTION = re.compile(r"^\d{6}\*+\d{4}\b")

NO_TXNS = "no transactions available"
END_OF_STATEMENT = "end of statement"
ADJUSTMENT_CAPTION = "(including internal adjustments)"

#: Widened window for a value printed against a two-line label (see
#: _label_value). Still far below the ~9pt spacing between header-box rows.
VALUE_TOL = 6.0

#: Baseline tolerance: words whose 'top' differs by less than this are on the
#: same physical line even though they belong to different scripts.
TOL = 3.0

#: Two vertical rules closer together than this are the same cell edge drawn
#: twice (the tables draw abutting cell borders).
EDGE_TOL = 2.0


class CbdLayoutError(ValueError):
    """The document is CBD, but not in a layout this parser can read."""


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------

def _iso(text):
    """Accept any of the printed date formats and return YYYY-MM-DD."""
    if not text:
        return None
    text = text.strip().lstrip(":").strip()
    if ISO_DATE.match(text):
        return text
    m = DMY_DATE.match(text)
    if m:
        dd, mm, yyyy = m.groups()
        return f"{yyyy}-{mm}-{dd}"
    return None


def _ascii_words(page):
    """Every word that is pure Latin/ASCII, i.e. the English band.

    Arabic (U+0600 and above) is dropped outright so it can never leak into an
    extracted field.
    """
    words = []
    for w in page.extract_words(use_text_flow=False, keep_blank_chars=False):
        t = w["text"]
        if t and all(ord(c) < 0x0600 for c in t):
            words.append(w)
    return sorted(words, key=lambda w: (w["top"], w["x0"]))


def _baselines(words, tol=TOL):
    """Group words into physical lines, each sorted left to right."""
    rows, current, anchor = [], [], None
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if anchor is None or abs(w["top"] - anchor) <= tol:
            if anchor is None:
                anchor = w["top"]
            current.append(w)
        else:
            rows.append(sorted(current, key=lambda x: x["x0"]))
            current, anchor = [w], w["top"]
    if current:
        rows.append(sorted(current, key=lambda x: x["x0"]))
    return rows


def _same_baseline(words, anchor, tol=TOL):
    top = anchor["top"] if isinstance(anchor, dict) else anchor
    return [w for w in words if abs(w["top"] - top) <= tol]


def _find_label(words, labels, tol=TOL):
    """Locate a run of consecutive words matching `labels` on one baseline."""
    first = labels[0]
    for candidate in words:
        if candidate["text"] != first:
            continue
        row = sorted(_same_baseline(words, candidate, tol), key=lambda w: w["x0"])
        i = row.index(candidate)
        run = row[i:i + len(labels)]
        if len(run) == len(labels) and [w["text"] for w in run] == list(labels):
            return run
    return None


def _right_of(words, run, tol=TOL):
    """Tokens sitting to the right of a label run on the same baseline."""
    row = sorted(_same_baseline(words, run[0], tol), key=lambda w: w["x0"])
    return [w for w in row if w["x0"] >= run[-1]["x1"] - 0.5]


def _label_value(words, labels, tol=TOL, value_tol=None):
    """The first value printed to the right of a label, as text.

    A trailing 'CR' is kept attached so money.to_minor() sees the suffix.
    `value_tol` widens the baseline window for the value only: in the card's
    header box a two-line label ("Minimum Amount Due" over "(to avoid Late
    Payment Fee)") is printed against a value vertically centred in the cell,
    three points off the label's own baseline. The label run is still matched
    on its exact baseline, so no neighbouring row can be pulled in.
    """
    run = _find_label(words, labels, tol)
    if not run:
        return None
    tail = [w["text"] for w in _right_of(words, run, value_tol or tol)]
    if not tail:
        return None
    value = tail[0]
    if len(tail) > 1 and tail[1].upper() == "CR":
        value = f"{value} CR"
    return value


def _label_text(words, labels, tol=TOL):
    """Everything printed to the right of a label, joined (e.g. a product name)."""
    run = _find_label(words, labels, tol)
    if not run:
        return None
    tail = [w["text"] for w in _right_of(words, run, tol)]
    return " ".join(tail).strip() or None


def _money(text):
    """to_minor() with an explicit failure, so a bad cell can never read as 0."""
    from analyser.money import to_minor

    value = to_minor(text)
    if value is None:
        raise CbdLayoutError(f"unreadable amount: {text!r}")
    return value


# ---------------------------------------------------------------------------
# ruled-table geometry
# ---------------------------------------------------------------------------

def _match_in_order(texts, groups):
    """Greedy left-to-right match of `groups` (tuples of literal words).

    Returns the index span of each group, or None if any group is missing or
    out of order. Matching in order is what distinguishes a real table header
    from a prose sentence that happens to contain two of the heading words.
    """
    spans, cursor = [], 0
    for group in groups:
        found = None
        for i in range(cursor, len(texts) - len(group) + 1):
            if texts[i:i + len(group)] == list(group):
                found = (i, i + len(group) - 1)
                break
        if found is None:
            return None
        spans.append(found)
        cursor = found[1] + 1
    return spans


def _header_row(rows, groups):
    """The first baseline carrying every heading in `groups`, in order.

    Returns (row, {field: (x0, x1)}) or (None, None).
    """
    for row in rows:
        texts = [w["text"] for w in row]
        spans = _match_in_order(texts, [g for _, g in groups])
        if spans is None:
            continue
        extents = {}
        for (field, _), (i, j) in zip(groups, spans):
            extents[field] = (row[i]["x0"], row[j]["x1"])
        return row, extents
    return None, None


def _table_extent(page, header_top, gap=15.0):
    """Bottom of the ruled table that starts at `header_top`.

    Grown rule by rule: a rect that starts more than `gap` below everything
    collected so far belongs to a different block (the page footer draws its
    own rules), so the table stops there. Without this the "body" of the table
    runs on into the footer text.
    """
    bottom = header_top
    for r in sorted((r for r in page.rects if r["bottom"] > header_top),
                    key=lambda r: r["top"]):
        if r["top"] > bottom + gap:
            break
        bottom = max(bottom, r["bottom"])
    return bottom


def _cell_edges(page, top, bottom):
    """x positions of the vertical rules crossing the band [top, bottom].

    These are the table's true cell borders. Rules from other tables (the
    summary block above, the page frame below) are excluded by the band.
    """
    xs = []
    for r in page.rects:
        if (r["x1"] - r["x0"]) >= EDGE_TOL:
            continue
        if (r["bottom"] - r["top"]) <= 5.0:
            continue
        if r["bottom"] < top or r["top"] > bottom:
            continue
        xs.append((r["x0"] + r["x1"]) / 2.0)
    merged = []
    for x in sorted(xs):
        if not merged or x - merged[-1] > EDGE_TOL:
            merged.append(x)
    return merged


def _cell_index(edges, x0, x1):
    """Index of the cell containing the horizontal centre of [x0, x1]."""
    centre = (x0 + x1) / 2.0
    for i in range(len(edges) - 1):
        if edges[i] <= centre < edges[i + 1]:
            return i
    return None


def _column_cells(page, header_row, extents, bottom):
    """Map each heading to the ruled cell it sits in.

    Raises if the table is not ruled or two headings share a cell -- either
    means the geometry is not the one this parser was written against.
    """
    top = min(w["top"] for w in header_row)
    edges = _cell_edges(page, top, bottom)
    if len(edges) < 2:
        raise CbdLayoutError("transaction table has no vertical rules to read columns from")
    cells = {}
    for field, (x0, x1) in extents.items():
        index = _cell_index(edges, x0, x1)
        if index is None:
            raise CbdLayoutError(f"heading {field!r} falls outside the ruled table")
        if index in cells.values():
            raise CbdLayoutError(f"two headings share one column near {field!r}")
        cells[field] = index
    return edges, cells


def _split_row(row, edges, cells):
    """Bucket a body row's words into {field: [words]} by ruled cell."""
    buckets = {field: [] for field in cells}
    inverse = {index: field for field, index in cells.items()}
    other = []
    for w in row:
        index = _cell_index(edges, w["x0"], w["x1"])
        field = inverse.get(index)
        if field is None:
            other.append(w)
        else:
            buckets[field].append(w)
    return buckets, other


def _cell_text(words):
    return " ".join(w["text"] for w in words).strip()


def _cell_amount(words):
    """A money cell: exactly one figure, optionally suffixed 'CR'.

    Returns (minor, text) or (None, "") for an empty cell. Anything else is a
    layout this parser does not understand, so it raises.
    """
    texts = [w["text"] for w in words]
    if not texts:
        return None, ""
    if len(texts) == 1 and AMOUNT.match(texts[0]):
        return _money(texts[0]), texts[0]
    if len(texts) == 2 and AMOUNT.match(texts[0]) and texts[1].upper() == "CR":
        text = f"{texts[0]} CR"
        return _money(text), text
    if len(texts) == 1 and AMOUNT.match(texts[0][:-2]) and texts[0][-2:].upper() == "CR":
        # "0.66CR" -- printed with no space.
        return _money(texts[0]), texts[0]
    raise CbdLayoutError(f"unreadable money cell: {texts!r}")


# ---------------------------------------------------------------------------
# card layout
# ---------------------------------------------------------------------------

_CARD_TABLE = (
    ("txn_date", ("Transaction", "Date")),
    ("posting_date", ("Posting", "Date")),
    ("description", ("Transaction", "Description")),
    ("amount", ("Amount", "in", "AED")),
)

_SUMMARY_COLUMNS = (
    ("opening_balance", ("Opening", "Balance")),
    ("payments_credits", ("Payments", "Received")),
    ("purchases_debits", ("New", "Purchases")),
    ("closing_balance", ("Total", "Outstanding", "Balance")),
)


def _card_header(words, header):
    header.setdefault("masked_number", _label_value(words, ("Card", "Number")))
    product = _label_text(words, ("Card", "Type"))
    if product:
        header["product_name"] = product
    statement_date = _iso(_label_value(words, ("Statement", "Date")))
    if statement_date:
        header["statement_date"] = statement_date
    due = _iso(_label_value(words, ("Payment", "Due", "Date")))
    if due:
        header["payment_due_date"] = due
    # 'From:' / 'To:' are printed on their own baselines, to the right of the
    # two-line 'Statement Period' label.
    for w in words:
        if w["text"] == "From:":
            header["period_start"] = _iso(
                (_right_of(words, [w]) or [{"text": ""}])[0]["text"])
        elif w["text"] == "To:":
            header["period_end"] = _iso(
                (_right_of(words, [w]) or [{"text": ""}])[0]["text"])


def _card_summary(words, rows):
    """The four Summary figures, read by column geometry.

    The heading baseline gives four x bands; the value baseline below it must
    carry exactly four figures, one per band. Fewer, more, or two figures
    landing in one band means the block is not the one described here, so it
    raises rather than filling in what it can.
    """
    row, extents = _header_row(rows, _SUMMARY_COLUMNS)
    if row is None:
        return {}, False

    header_top = min(w["top"] for w in row)
    caption = any(
        ADJUSTMENT_CAPTION in _cell_text(r).lower()
        for r in rows
        if min(w["top"] for w in r) > header_top
        and min(w["top"] for w in r) < header_top + 40
    )

    values = None
    for candidate in rows:
        top = min(w["top"] for w in candidate)
        if top <= header_top + TOL:
            continue
        if any(AMOUNT.match(w["text"]) for w in candidate):
            values = candidate
            break
    if values is None:
        raise CbdLayoutError("summary block has no value row")

    centres = {field: (x0 + x1) / 2.0 for field, (x0, x1) in extents.items()}
    cells, index = [], 0
    while index < len(values):
        text = values[index]["text"]
        if not AMOUNT.match(text):
            index += 1
            continue
        x0, x1 = values[index]["x0"], values[index]["x1"]
        if index + 1 < len(values) and values[index + 1]["text"].upper() == "CR":
            text = f"{text} CR"
            x1 = values[index + 1]["x1"]
            index += 1
        cells.append((text, (x0 + x1) / 2.0))
        index += 1

    if len(cells) != len(centres):
        raise CbdLayoutError(
            f"summary has {len(cells)} figures for {len(centres)} columns")

    summary = {}
    for text, centre in cells:
        field = min(centres, key=lambda f: abs(centre - centres[f]))
        if field in summary:
            raise CbdLayoutError(f"two summary figures land in the {field!r} column")
        summary[field] = _money(text)
    return summary, caption


def _card_extras(words, summary):
    from analyser.money import to_minor

    for field, labels in (
        ("minimum_due", ("Minimum", "Amount", "Due")),
        ("total_payment_due", ("Total", "Amount", "Due*")),
        ("credit_limit", ("Total", "Credit", "Limit")),
        ("available_limit", ("Available", "Credit", "Limit")),
    ):
        text = _label_value(words, labels, value_tol=VALUE_TOL)
        if text is None:
            continue
        value = to_minor(text)
        if value is None:
            raise CbdLayoutError(f"unreadable {field}: {text!r}")
        summary.setdefault(field, value)


def _card_transactions(page, pageno, rows, txns):
    """Read one page's transaction table. Returns True if a table was found."""
    header, extents = _header_row(rows, _CARD_TABLE)
    if header is None:
        return False
    header_top = min(w["top"] for w in header)
    bottom = _table_extent(page, header_top)
    body = [r for r in rows
            if header_top + TOL < min(w["top"] for w in r) <= bottom]
    if not body:
        return True
    edges, cells = _column_cells(page, header, extents, bottom)

    current = None
    for row in body:
        buckets, stray = _split_row(row, edges, cells)
        if stray:
            raise CbdLayoutError(
                f"page {pageno}: text outside every column: "
                f"{[w['text'] for w in stray]!r}")
        joined = _cell_text(row)
        lowered = joined.lower()
        if NO_TXNS in lowered or END_OF_STATEMENT in lowered:
            current = None
            continue

        date_text = _cell_text(buckets["txn_date"])
        amount_minor, amount_text = _cell_amount(buckets["amount"])
        description = _cell_text(buckets["description"])

        if not date_text and amount_minor is None:
            # A card sub-heading, or the continuation of the row above it.
            if CARD_SECTION.match(description):
                current = None
            elif current is not None and description:
                current["raw_description"] = (
                    f"{current['raw_description']} {description}".strip())
                current["raw_text"] = f"{current['raw_text']} {joined}".strip()
            continue

        if not date_text or amount_minor is None:
            raise CbdLayoutError(
                f"page {pageno}: half a transaction row: {joined!r}")

        txn_date = _iso(date_text)
        if txn_date is None:
            raise CbdLayoutError(f"page {pageno}: unreadable date {date_text!r}")
        posting_text = _cell_text(buckets["posting_date"])
        posting_date = _iso(posting_text) if posting_text else None
        if posting_text and posting_date is None:
            raise CbdLayoutError(
                f"page {pageno}: unreadable posting date {posting_text!r}")

        # to_minor() already made a 'CR' figure negative; flip so that money in
        # is positive and a bare (debit) figure is negative.
        current = {
            "page_number": pageno,
            "txn_date": txn_date,
            "posting_date": posting_date,
            "raw_description": description,
            "currency": "AED",
            "amount_minor": -amount_minor,
            "raw_text": joined,
        }
        txns.append(current)
    return True


def _totals(txns):
    debits = sum(-t["amount_minor"] for t in txns if t["amount_minor"] < 0)
    credits = sum(t["amount_minor"] for t in txns if t["amount_minor"] > 0)
    return debits, credits


def _check_balance_identity(summary, txns):
    """opening - sum(signed amounts) == closing, on the ITEMISED rows.

    Independent of the two movement columns, so it still catches a dropped row
    when the movement columns themselves are reconciled by an adjustment.
    """
    opening = summary.get("opening_balance")
    closing = summary.get("closing_balance")
    if opening is None or closing is None:
        return
    movement = sum(t["amount_minor"] for t in txns)
    if opening - movement != closing:
        raise CbdLayoutError(
            f"balance identity fails: opening {opening} - movement {movement} "
            f"!= closing {closing}")


def _apply_internal_adjustment(header, summary, txns, disclosed):
    """Emit CBD's unitemised, self-cancelling internal adjustment.

    The two legs are described as a REVERSAL pair, which is what they are: a
    debit and an exactly offsetting credit inside one cycle. That wording also
    keeps normalize.classify_txn_type() from typing the debit leg as a
    PURCHASE, so an entry the bank never itemised cannot inflate spend,
    rewards or routing (TxnType.SPEND excludes REVERSAL).
    """
    printed_debits = summary.get("purchases_debits")
    printed_credits = summary.get("payments_credits")
    if printed_debits is None or printed_credits is None:
        return
    debits, credits = _totals(txns)
    debit_gap = printed_debits - debits
    credit_gap = printed_credits - credits
    if debit_gap == 0 and credit_gap == 0:
        return
    if not disclosed:
        raise CbdLayoutError(
            f"totals do not match the itemised rows (debits {debits} vs "
            f"{printed_debits}, credits {credits} vs {printed_credits}) and the "
            f"statement discloses no internal adjustment")
    if debit_gap != credit_gap or debit_gap < 0:
        raise CbdLayoutError(
            f"unitemised movement does not cancel: debit gap {debit_gap}, "
            f"credit gap {credit_gap}")

    when = header.get("period_end") or header.get("statement_date")
    note = ("CBD INTERNAL ADJUSTMENT REVERSAL PAIR - INCLUDED IN THE STATEMENT "
            "TOTALS, NOT ITEMISED BY THE BANK")
    for amount, leg in ((-debit_gap, "DEBIT"), (credit_gap, "CREDIT")):
        txns.append({
            "page_number": 1,
            "txn_date": when,
            "posting_date": when,
            "raw_description": f"{note} ({leg} LEG)",
            "currency": "AED",
            "amount_minor": amount,
            "raw_text": note,
        })


def _parse_card(pdf, header, summary, txns):
    disclosed = False
    saw_table = False
    for pageno, page in enumerate(pdf.pages, start=1):
        words = _ascii_words(page)
        if not words:
            continue
        rows = _baselines(words)
        if "statement_date" not in header:
            _card_header(words, header)
        if not summary:
            summary, disclosed = _card_summary(words, rows)
            if summary:
                _card_extras(words, summary)
        if _card_transactions(page, pageno, rows, txns):
            saw_table = True
    if not summary:
        raise CbdLayoutError("credit card statement has no Summary block")
    if not saw_table:
        raise CbdLayoutError("credit card statement has no transaction table")
    _check_balance_identity(summary, txns)
    _apply_internal_adjustment(header, summary, txns, disclosed)
    return summary


# ---------------------------------------------------------------------------
# current-account layout
# ---------------------------------------------------------------------------

_ACCOUNT_TABLE = (
    ("txn_date", ("Date",)),
    ("description", ("Description",)),
    ("value_date", ("Value", "Date")),
    ("debit", ("Debit",)),
    ("credit", ("Credit",)),
    ("balance", ("Balance",)),
)

BROUGHT_FORWARD = "balance brought fwd"
ITEM_COUNT = "item count"
TURN_OVER = "turn over"


def _account_header(words, header):
    number = _label_value(words, ("Acct.", "No.", ":"))
    if number:
        header["masked_number"] = number
    product = _label_text(words, ("Acct.", "Type", ":"))
    if product:
        header["product_name"] = product
    date = _iso(_label_value(words, ("Date", ":")))
    if date:
        header["statement_date"] = date
    run = _find_label(words, ("Period",))
    if run:
        tail = [w["text"] for w in _right_of(words, run)]
        dates = [_iso(t) for t in tail if _iso(t)]
        if len(dates) == 2:
            header["period_start"], header["period_end"] = dates


def _account_transactions(page, pageno, rows, summary, txns):
    table, extents = _header_row(rows, _ACCOUNT_TABLE)
    if table is None:
        return False
    header_top = min(w["top"] for w in table)
    bottom = _table_extent(page, header_top)
    body = [r for r in rows
            if header_top + TOL < min(w["top"] for w in r) <= bottom]
    if not body:
        return True
    edges, cells = _column_cells(page, table, extents, bottom)

    for row in body:
        buckets, _outside = _split_row(row, edges, cells)
        joined = _cell_text(row)
        lowered = joined.lower()
        if END_OF_STATEMENT in lowered or ITEM_COUNT in lowered:
            continue

        debit, _ = _cell_amount(buckets["debit"])
        credit, _ = _cell_amount(buckets["credit"])
        balance, _ = _cell_amount(buckets["balance"])

        if BROUGHT_FORWARD in lowered:
            if balance is None:
                raise CbdLayoutError("'Balance Brought FWD' row carries no balance")
            summary["opening_balance"] = balance
            summary["closing_balance"] = balance
            continue
        if TURN_OVER in lowered:
            if debit is None or credit is None:
                raise CbdLayoutError("'TURN OVER' row is missing a total")
            summary["purchases_debits"] = debit
            summary["payments_credits"] = credit
            continue

        date_text = _cell_text(buckets["txn_date"])
        if not date_text and debit is None and credit is None:
            continue  # a wrapped description line carries no money
        txn_date = _iso(date_text)
        if txn_date is None:
            raise CbdLayoutError(f"page {pageno}: unreadable account row: {joined!r}")
        if (debit is None) == (credit is None):
            raise CbdLayoutError(
                f"page {pageno}: account row is neither a debit nor a credit: {joined!r}")
        value_text = _cell_text(buckets["value_date"])
        value_date = _iso(value_text) if value_text else None
        txns.append({
            "page_number": pageno,
            "txn_date": txn_date,
            "posting_date": value_date,
            "raw_description": _cell_text(buckets["description"]),
            "currency": "AED",
            "amount_minor": -debit if debit is not None else credit,
            "raw_text": joined,
        })
        if balance is not None:
            summary["closing_balance"] = balance
    return True


def _parse_account(pdf, header, summary, txns):
    saw_table = False
    for pageno, page in enumerate(pdf.pages, start=1):
        words = _ascii_words(page)
        if not words:
            continue
        rows = _baselines(words)
        if "statement_date" not in header:
            _account_header(words, header)
        if _account_transactions(page, pageno, rows, summary, txns):
            saw_table = True
    if not saw_table:
        raise CbdLayoutError("account statement has no transaction table")
    for field in ("purchases_debits", "payments_credits"):
        if field not in summary:
            raise CbdLayoutError(f"account statement prints no {field} total")
    debits, credits = _totals(txns)
    if (debits, credits) != (summary["purchases_debits"], summary["payments_credits"]):
        raise CbdLayoutError(
            f"account rows {debits}/{credits} do not match the printed turnover "
            f"{summary['purchases_debits']}/{summary['payments_credits']}")
    return summary


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def _detect(pdf):
    head = (pdf.pages[0].extract_text() or "")
    return "Commercial Bank of Dubai" in head or "cbd.ae" in head


def _layout(pdf):
    text = " ".join(
        re.sub(r"\s+", " ", (page.extract_text() or "")) for page in pdf.pages[:1]
    ).lower()
    if "statement of account - credit card" in text or "card type" in text:
        return "card"
    if BROUGHT_FORWARD in text or "acct. type" in text:
        return "account"
    raise CbdLayoutError("unrecognised CBD layout: neither a card nor an account statement")


def parse(path):
    """Return (header, summary, transactions, rewards).

    Amounts are integer fils, signed: negative = money out / credit balance.
    """
    header, summary, txns, rewards = {}, {}, [], []

    with pdfplumber.open(path) as pdf:
        if not _detect(pdf):
            raise ValueError("not a CBD statement")
        header["page_count"] = len(pdf.pages)
        header["currency"] = "AED"
        layout = _layout(pdf)
        # CBD mails BOTH a credit-card statement and a current-account statement from
        # the same address. Declaring which this is keeps a deposit account from being
        # created as -- or merged into -- a card, which would fold salary and transfers
        # into card spending (D-028e, D-037).
        header["account_type"] = "CREDIT_CARD" if layout == "card" else "BANK"
        header["include_in_spending"] = 1 if layout == "card" else 0
        if layout == "card":
            summary = _parse_card(pdf, header, summary, txns)
        else:
            summary = _parse_account(pdf, header, summary, txns)

    return header, summary, txns, rewards
