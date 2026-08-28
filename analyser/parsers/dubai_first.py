"""Dubai First credit card statement parser (D-004, D-006).

Dubai First was acquired by FAB, so these statements are mailed from the same
address as the FAB ones (estatement@bankfab.com). The DOCUMENT, however, is a
completely different template and is routed by content: the Dubai First card is
masked as ``524204XXXXXX7264`` (six digits, X's, four digits) where FAB prints
``4XXX XX** **** NNNN``.

Format notes observed across the real statements (Mar-Jul 2026):
  * The entire chrome of the statement -- every column heading, every label, in
    English and Arabic -- is a full-page BACKGROUND IMAGE. ``extract_text`` sees
    only the values: bare dates, bare numbers, and merchant names. There is no
    "Previous Balance" string to anchor on the way ``fab._read_summary`` does.
    Column identity therefore comes from x-GEOMETRY against the fixed template
    (the bands below), read off the rendered background, and every band is
    checked: a value that lands outside one is an unrecognised layout and
    raises rather than being filed under its nearest neighbour.
  * Dates are DD-Mon-YYYY, two columns: transaction date then posting date.
  * Debit and Credit are SEPARATE columns holding textually identical numbers,
    so the sign lives in the x position, not in the text. Both columns are
    LEFT-aligned (debit at x=438, credit at x=511), which is why the bands are
    generous on the right.
  * A balance carries a ``Dr`` / ``Cr`` suffix as its own word -- the mirror of
    FAB's glued-on "CR". ``Dr`` is the normal case (money owed).
  * Payment rows are followed by indented continuation lines ("Payment of AED
    ... towards Principle: ..."). They carry no column amount and are skipped.
  * The rewards footer is a points ledger, not money.

Reconciliation (D-004) closes exactly on all five statements: the debit column
sums to the printed "+ Purchases/Debits" cell and the credit column to
"- Payments/Credits" -- including the two refunds (a 16.00 Amazon Prime reversal
and an 8.93 Lulu return) that print in the credit column with no other marking.
"""
import re
import re as _re
import warnings

warnings.filterwarnings("ignore")
import pdfplumber

PARSER_NAME = "dubai_first"
PARSER_VERSION = 1

DATE = re.compile(r"^\d{2}-[A-Za-z]{3}-\d{4}$")
AMOUNT = re.compile(r"^[\d,]+\.\d{2}$")
COUNT = re.compile(r"^\d{1,3}(?:,\d{3})*$")
#: The masked PAN as Dubai First prints it: 524204XXXXXX7264.
CARD = re.compile(r"\b\d{6}X{4,}\d{4}\b")
BALANCE_MARKER = ("Dr", "Cr")

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

# ---------------------------------------------------------------------------
# Column geometry of the fixed template, in PDF points on the A4 page.
# Each band is (x_low, x_high) and is matched against a word's CENTRE.
# ---------------------------------------------------------------------------

#: Summary Details, row 1. Printed order, verified against the rendered
#: background image: Previous Balance | + Purchases/Debits | + Cash Advances |
#: + Finance Charges | - Payments/Credits | Total Payment Due.
_SUMMARY_BANDS = (
    ("opening_balance", (33.0, 119.0)),
    ("purchases_debits", (119.0, 201.0)),
    ("cash_advances", (201.0, 288.0)),
    ("finance_charges", (288.0, 366.0)),
    ("payments_credits", (366.0, 454.0)),
    ("total_payment_due", (454.0, 566.0)),
)

#: Summary Details, row 2: Total Credit Limit | Available Credit Limit.
_LIMIT_BANDS = (
    ("credit_limit", (33.0, 119.0)),
    ("available_limit", (119.0, 201.0)),
)

#: The card strip above the summary: Main Card Number | Current Balance |
#: Minimum Payment Due.
_CARD_BANDS = (
    ("masked_number", (250.0, 390.0)),
    ("closing_balance", (390.0, 477.0)),
    ("minimum_due", (477.0, 566.0)),
)

#: The strip above that: Main Card Product | Statement Date | Payment Due Date.
_PRODUCT_BANDS = (
    ("product_name", (250.0, 390.0)),
    ("statement_date", (390.0, 477.0)),
    ("payment_due_date", (477.0, 566.0)),
)

#: Transaction table. Anything left of ORIGINAL_CURRENCY is description text.
_TXN_BANDS = (
    ("original_currency", (330.0, 403.0)),
    ("debit", (403.0, 477.0)),
    ("credit", (477.0, 570.0)),
)

#: Rewards Summary footer: Starting Balance | Earned | Adjustment | Redeemed |
#: Rewards expiring | Expired | Closing Balance. The expiring cell holds a
#: points figure plus an expiry date and has no column in reward_statements.
_REWARD_BANDS = (
    ("opening_balance", (90.0, 140.0)),
    ("earned", (140.0, 205.0)),
    ("adjusted", (205.0, 275.0)),
    ("redeemed", (275.0, 345.0)),
    ("expiring", (345.0, 415.0)),
    ("expired", (415.0, 490.0)),
    ("closing_balance", (490.0, 560.0)),
)

#: y below which the page is the rewards footer rather than the transaction table.
_FOOTER_TOP = 650.0


def _iso(d):
    dd, mon, yyyy = d.split("-")
    month = _MONTHS.get(mon.lower())
    if month is None:
        raise ValueError(f"unrecognised month in date {d!r}")
    return f"{yyyy}-{month:02d}-{int(dd):02d}"


def _lines(page, tol=2.5):
    """Group words into visual lines, preserving x positions."""
    rows = {}
    for w in page.extract_words(use_text_flow=False, keep_blank_chars=False):
        rows.setdefault(round(w["top"] / tol), []).append(w)
    return [sorted(rows[k], key=lambda w: w["x0"]) for k in sorted(rows)]


def _centre(word):
    return (word["x0"] + word["x1"]) / 2


def _band(word, bands):
    """Name of the column `word` sits in, or None when it sits in no column.

    Deliberately not a nearest-match: a value that falls between two columns
    means the template moved, and filing it under whichever column happens to
    be closest is exactly the plausible-but-wrong output D-004 exists to stop.
    """
    x = _centre(word)
    for name, (low, high) in bands:
        if low <= x < high:
            return name
    return None


def _signed(word, marker):
    """Integer minor units for a balance cell, honouring its Dr/Cr suffix.

    Dubai First prints the amount owed as '32,924.01 Dr'. 'Cr' is the credit
    balance -- the bank owing the cardholder -- and flips the sign, matching the
    convention `analyser.money.to_minor` applies to FAB's "0.66CR".
    """
    from analyser.money import to_minor

    value = to_minor(word["text"], credit_suffix=False)
    if value is None:
        raise ValueError(f"unparseable amount {word['text']!r}")
    if marker == "Cr":
        return -value
    return value


def _marker_for(word, words):
    """The Dr/Cr word immediately following `word` on the same baseline."""
    for other in words:
        if other["text"] in BALANCE_MARKER and 0 <= other["x0"] - word["x1"] < 15:
            return other["text"]
    return None


def _detect(pdf):
    """Content detection (D-006): the Dubai First PAN mask plus its card header.

    FAB masks with asterisks and groups in fours, so the two templates cannot
    both match even though they arrive from the same sender.
    """
    head = pdf.pages[0].extract_text() or ""
    return bool(CARD.search(head)) and "Main Card" in head


def _read_product(words, header):
    """Main Card Product / Statement Date / Payment Due Date strip."""
    fields = {}
    for w in words:
        name = _band(w, _PRODUCT_BANDS)
        if name is None:
            continue
        if name == "product_name":
            fields.setdefault(name, []).append(w["text"])
        elif DATE.match(w["text"]):
            fields[name] = _iso(w["text"])
    if "statement_date" not in fields or "payment_due_date" not in fields:
        return False
    header["statement_date"] = fields["statement_date"]
    header["payment_due_date"] = fields["payment_due_date"]
    if fields.get("product_name"):
        header["product_name"] = " ".join(fields["product_name"])
    return True


def _read_card_strip(words, header, summary):
    """Main Card Number / Current Balance / Minimum Payment Due strip."""
    found = False
    for w in words:
        name = _band(w, _CARD_BANDS)
        if name is None:
            continue
        if name == "masked_number":
            if CARD.match(w["text"]):
                header.setdefault("masked_number", w["text"])
                found = True
        elif AMOUNT.match(w["text"]):
            summary.setdefault(name, _signed(w, _marker_for(w, words)))
    return found


def _read_amount_row(words, bands):
    """Map a row of bare amounts onto `bands`; None if it is not that row.

    Every band must be filled exactly once, which is also what keeps the two
    stacked rows of the Summary block apart: the Total/Available Credit Limit
    row sits under the first two summary columns and would otherwise be read as
    a Previous Balance and a Purchases total.
    """
    values = [w for w in words if AMOUNT.match(w["text"])]
    if len(values) != len(words) or len(values) != len(bands):
        return None
    out = {}
    for w in values:
        name = _band(w, bands)
        if name is None or name in out:
            return None
        out[name] = _signed(w, None)
    return out


def _read_rewards(words, page_number):
    """The points ledger in the footer, or None when this is not that row."""
    counts = [w for w in words if COUNT.match(w["text"])]
    if len(counts) != len(words) or len(counts) < 6:
        return None
    row = {}
    for w in counts:
        name = _band(w, _REWARD_BANDS)
        if name is None or name in row:
            return None
        row[name] = int(w["text"].replace(",", ""))
    if not {"opening_balance", "earned", "redeemed", "closing_balance"} <= set(row):
        return None
    # Keep the expiry: points that lapse unredeemed are worth nothing, so the
    # figure and its date belong in the reward record (D-024). The date sits on the
    # line below the count ("37 / by 31-AUG-2026") and is picked up by the caller.
    row.setdefault("expiring", None)
    row.pop("expired", None)
    row["reward_unit"] = "POINTS"
    row["source_page"] = page_number
    return row


_EXPIRY = _re.compile(r"by\s+(\d{1,2})[-\s]([A-Za-z]{3})[-\s](\d{4})", _re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _read_expiring_count(page):
    """The expiring-points figure, which prints on its OWN line above the ledger row.

    Dubai First stacks the cell as "37" / "by 31-AUG-2026", so the main reward row
    carries only six numbers and the seventh has to be found by x-band.
    """
    lo, hi = dict(_REWARD_BANDS)["expiring"]
    for w in page.extract_words():
        if w["top"] > _FOOTER_TOP and COUNT.match(w["text"]):
            centre = (w["x0"] + w["x1"]) / 2
            if lo <= centre < hi:
                return int(w["text"].replace(",", ""))
    return None


def _read_expiry(page_text):
    """'Rewards expiring 37 by 31-AUG-2026' -> ISO date, or None."""
    m = _EXPIRY.search(page_text or "")
    if not m:
        return None
    day, mon, year = m.group(1), m.group(2).lower()[:3], m.group(3)
    if mon not in _MONTHS:
        return None
    return f"{year}-{_MONTHS[mon]:02d}-{int(day):02d}"


def _read_transaction(words, page_number):
    """One transaction row, or None if this line is not one.

    A row is recognised by its two leading dates. The amount is then resolved by
    COLUMN, not by position in the token list: the Debit and Credit cells hold
    identical text and the row may or may not also carry an original-currency
    amount, so counting tokens from either end gets the sign wrong sooner or
    later.
    """
    if len(words) < 3 or not DATE.match(words[0]["text"]) or not DATE.match(words[1]["text"]):
        return None

    columns = {}
    for w in words[2:]:
        if not AMOUNT.match(w["text"]):
            continue
        if _centre(w) < _TXN_BANDS[0][1][0]:
            continue          # a figure inside the description, e.g. 'DUBAI 784'
        name = _band(w, _TXN_BANDS)
        if name is None or name in columns:
            raise ValueError(
                f"amount {w['text']!r} at x={_centre(w):.1f} is in no known "
                f"transaction column: {' '.join(x['text'] for x in words)!r}"
            )
        columns[name] = w

    if "original_currency" in columns:
        # Never seen in a real statement; the currency code is not in the text
        # layer, so emitting a currency here would be a guess.
        raise ValueError(
            "original-currency column is populated and this parser has no "
            f"verified layout for it: {' '.join(x['text'] for x in words)!r}"
        )
    if ("debit" in columns) == ("credit" in columns):
        raise ValueError(
            "transaction row must carry exactly one of Debit/Credit: "
            f"{' '.join(x['text'] for x in words)!r}"
        )

    amount_word = columns.get("debit") or columns["credit"]
    magnitude = _signed(amount_word, None)
    description = " ".join(
        w["text"] for w in words[2:] if w is not amount_word and _centre(w) < _TXN_BANDS[0][1][0]
    ).strip()
    if not description:
        raise ValueError(
            f"transaction row has no description: {' '.join(x['text'] for x in words)!r}"
        )

    return {
        "page_number": page_number,
        "txn_date": _iso(words[0]["text"]),
        "posting_date": _iso(words[1]["text"]),
        "raw_description": description,
        "currency": "AED",
        # Debit column = money out (negative), Credit column = money in.
        "amount_minor": magnitude if "credit" in columns else -magnitude,
        "raw_text": " ".join(w["text"] for w in words),
    }


def parse(path):
    """Return (header, summary, transactions, rewards).

    Amounts are integer fils, signed: negative = money out.
    """
    header, summary, txns, rewards = {}, {}, [], []
    # Say what this document IS. Nothing downstream may assume from the sender --
    # bankfab.com mails both FAB and Dubai First statements (D-039).
    header["account_type"] = "CREDIT_CARD"
    header["include_in_spending"] = 1

    with pdfplumber.open(path) as pdf:
        if not _detect(pdf):
            raise ValueError("not a Dubai First statement")
        header["page_count"] = len(pdf.pages)

        for pageno, page in enumerate(pdf.pages, start=1):
            in_table = False
            for words in _lines(page):
                txn = _read_transaction(words, pageno)
                if txn is not None:
                    txns.append(txn)
                    in_table = True
                    continue

                texts = [w["text"] for w in words]
                if "Main" in texts and any(CARD.match(t) for t in texts):
                    in_table = True          # 'Main Card : 524204XXXXXX7264'
                    continue

                if pageno != 1:
                    continue

                if not in_table:
                    # The header strips and the Summary Details block, all of
                    # which sit above the transaction table.
                    if "statement_date" not in header and _read_product(words, header):
                        continue
                    if "masked_number" not in header and _read_card_strip(words, header, summary):
                        continue
                    if "purchases_debits" not in summary:
                        row = _read_amount_row(words, _SUMMARY_BANDS)
                        if row is not None:
                            summary.update(row)
                            continue
                    elif "credit_limit" not in summary:
                        row = _read_amount_row(words, _LIMIT_BANDS)
                        if row is not None:
                            summary.update(row)
                            continue
                elif not rewards and words[0]["top"] > _FOOTER_TOP:
                    row = _read_rewards(words, pageno)
                    if row is not None:
                        # The expiry date sits on its own line under the count, so
                        # it is read from the page text rather than the row bands.
                        row["expiring"] = _read_expiring_count(page)
                        row["expiring_by"] = _read_expiry(page.extract_text() or "")
                        rewards.append(row)

    if "purchases_debits" not in summary or "payments_credits" not in summary:
        raise ValueError(f"Summary Details block not found in {path}")
    if "statement_date" not in header:
        raise ValueError(f"statement header not found in {path}")

    return header, summary, txns, rewards
