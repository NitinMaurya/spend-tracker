"""FAB (First Abu Dhabi Bank) credit card statement parser.

Format notes observed in the samples:
  * Two date columns, both DD-MM-YYYY: transaction date then posting date.
  * Debit / Credit are SEPARATE columns -- the sign is carried by which column
    the number sits in, so this parser works on word x-coordinates, not text.
  * Descriptions are '<MERCHANT> <CITY> <COUNTRY> <CCY> <amount>'.
  * Rows may be followed by indented continuation lines (payment detail).
  * The Arabic font has no ToUnicode map and extracts as '(cid:NNN)'; some
    English is glyph-tripled. We only read the ASCII transaction band.
"""
import re
import warnings

warnings.filterwarnings("ignore")
import pdfplumber

PARSER_NAME = "fab"
PARSER_VERSION = 1

DATE = re.compile(r"^\d{2}-\d{2}-\d{4}$")
AMOUNT = re.compile(r"^[\d,]+\.\d{2}$")
CCY = re.compile(r"^[A-Z]{3}$")


def _iso(d):
    dd, mm, yyyy = d.split("-")
    return f"{yyyy}-{mm}-{dd}"


def _lines(page, tol=2.5):
    """Group words into visual lines, preserving x positions."""
    rows = {}
    for w in page.extract_words(use_text_flow=False, keep_blank_chars=False):
        key = round(w["top"] / tol)
        rows.setdefault(key, []).append(w)
    out = []
    for key in sorted(rows):
        out.append(sorted(rows[key], key=lambda w: w["x0"]))
    return out


#: The Summary Details header, in printed order. Values are matched to these by
#: x-position so a missing or oddly-formatted cell shifts nothing.
_SUMMARY_COLUMNS = (
    ("opening_balance", ("Previous", "Balance")),
    ("purchases_debits", ("Purchases/Debits",)),
    ("cash_advances", ("Cash", "Advances")),
    ("finance_charges", ("Finance", "Charges")),
    ("payments_credits", ("Payments/Credits",)),
    ("total_payment_due", ("Total", "Payment", "Due")),
)

#: An amount, optionally carrying FAB's CR suffix for a credit balance. The suffix
#: is glued on with no space ("0.66CR"), which a plain-number pattern silently skips.
_SUMMARY_AMOUNT = re.compile(r"^[\d,]+\.\d{2}(?:CR)?$", re.IGNORECASE)


def _read_summary(page):
    """Extract the Summary Details block by column geometry.

    Anchored on the header labels rather than on a token count: FAB prints a credit
    balance as "0.66CR", which is not a bare number, so a count-based match lost the
    whole block and the statement then failed reconciliation against zeros.
    """
    from analyser.money import to_minor

    words = page.extract_words()
    anchor = next((w for w in words if w["text"] == "Summary"), None)
    if anchor is None:
        return {}

    band = [w for w in words if anchor["top"] < w["top"] < anchor["top"] + 60]

    # x-centre of each header column, from its first label word
    centres = {}
    for field, labels in _SUMMARY_COLUMNS:
        hit = next((w for w in band if w["text"] == labels[0]), None)
        if hit is not None:
            centres[field] = (hit["x0"] + hit["x1"]) / 2

    values = [w for w in band if _SUMMARY_AMOUNT.match(w["text"])]
    if not centres or not values:
        return {}

    out = {}
    for w in values:
        centre = (w["x0"] + w["x1"]) / 2
        field = min(centres, key=lambda f: abs(centres[f] - centre))
        # A value must actually sit under its column, not merely be nearest.
        if abs(centres[field] - centre) < 70 and field not in out:
            out[field] = to_minor(w["text"])
    return out


def _find_columns(page):
    """Locate the x-centre of the Debit and Credit transaction-column headers.

    'Credit' also appears in 'Total Credit Limit' higher up the page, so we
    anchor on 'Debit' (which is unambiguous) and take the 'Credit' sitting on
    the nearest baseline to it.
    """
    words = page.extract_words()
    debits = [w for w in words if w["text"] == "Debit"]
    credits = [w for w in words if w["text"] == "Credit"]
    if not debits or not credits:
        return None
    d = debits[0]
    c = min(credits, key=lambda w: abs(w["top"] - d["top"]))
    if abs(c["top"] - d["top"]) > 5 or c["x0"] <= d["x0"]:
        return None
    return {"debit": (d["x0"] + d["x1"]) / 2, "credit": (c["x0"] + c["x1"]) / 2}


def _detect(pdf):
    head = (pdf.pages[0].extract_text() or "")
    return "bankfab.com" in head or "FAB" in head


def parse(path):
    """Return (header, summary, transactions). Amounts are integer fils,
    signed: negative = money out."""
    from analyser.money import to_minor

    header, summary, txns = {}, {}, []

    with pdfplumber.open(path) as pdf:
        if not _detect(pdf):
            raise ValueError("not a FAB statement")
        header["page_count"] = len(pdf.pages)

        for pageno, page in enumerate(pdf.pages, start=1):
            lines = _lines(page)
            cols = _find_columns(page)
            if not summary:
                summary = _read_summary(page)

            for words in lines:
                toks = [w["text"] for w in words]

                # --- header: '4XXX XX** **** NNNN 1,402.84 100.00'
                if len(toks) >= 6 and toks[0].isdigit() and "**" in "".join(toks[:4]):
                    header.setdefault("masked_number", " ".join(toks[:4]))

                # --- '... BLUE FAB SIGNAT 01-08-2026 26-08-2026'
                # The mailing address shares this baseline, so take only the
                # tokens immediately preceding the two dates as the product name.
                if "statement_date" not in header and len(toks) >= 3:
                    dates = [t for t in toks if DATE.match(t)]
                    if len(dates) == 2:
                        first_date_at = next(i for i, t in enumerate(toks) if DATE.match(t))
                        header["product_name"] = " ".join(toks[max(0, first_date_at - 3):first_date_at])
                        header["statement_date"] = _iso(dates[0])
                        header["payment_due_date"] = _iso(dates[1])

                # --- summary row (see _read_summary): resolved by COLUMN POSITION,
                # not by counting tokens. Counting broke the moment a balance printed
                # as "0.66CR" instead of a bare number.

                # --- transaction row: starts with two dates
                if len(toks) >= 4 and DATE.match(toks[0]) and DATE.match(toks[1]) and cols:
                    txn_date, post_date = _iso(toks[0]), _iso(toks[1])

                    # Parse from the RIGHT: the row ends with the amount in the
                    # transaction currency, then the same figure repeated in
                    # either the Debit or the Credit column.
                    #   <desc...> <CCY> <amount> [<amount>]
                    # Reading right-to-left avoids mistaking a description word
                    # for a currency code (e.g. 'YOU' in 'THANK YOU').
                    i = len(words) - 1
                    tail = []
                    while i >= 0 and AMOUNT.match(words[i]["text"]):
                        tail.append(words[i])
                        i -= 1
                    if not tail or i < 2 or not CCY.match(words[i]["text"]):
                        continue
                    currency = words[i]["text"]
                    description = " ".join(w["text"] for w in words[2:i]).strip()
                    if not description:
                        continue

                    column_word = tail[0]          # right-most figure
                    centre = (column_word["x0"] + column_word["x1"]) / 2
                    is_credit = abs(centre - cols["credit"]) < abs(centre - cols["debit"])
                    magnitude = to_minor(column_word["text"])

                    txns.append({
                        "page_number": pageno,
                        "txn_date": txn_date,
                        "posting_date": post_date,
                        "raw_description": description,
                        "currency": currency,
                        # credit column = money in (positive), debit = money out
                        "amount_minor": magnitude if is_credit else -magnitude,
                        "raw_text": " ".join(toks),
                    })

    return header, summary, txns
