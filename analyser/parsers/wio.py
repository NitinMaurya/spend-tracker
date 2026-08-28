"""Wio credit-facility statement parser (D-006, D-007).

Format notes observed in the sample:
  * Single date column, DD/MM/YYYY. There is no separate posting date, so the
    posting date mirrors the transaction date.
  * Columns are Date | Ref. Number | Description | Card Number | Amount, and the
    Amount column carries an EXPLICIT sign: '-4,000.00' money out,
    '+11,774.00' money in. Nothing is inferred from x-position for the sign,
    but x-bands are still used to keep an (often empty) Card Number column out
    of the description.
  * The sign convention INVERTS between sections: the 'Account summary' block
    prints the same money-out total as 'Purchases +11,774.00'. Summary figures
    are therefore stored as positive magnitudes (what `analyser.ingest.reconcile`
    compares against) while transaction amounts stay signed.
  * D-007: this is a settlement facility, not a spending card. Every row is a
    payment to another card, so the account is flagged
    account_type=CREDIT_FACILITY / include_in_spending=0.
"""
import re
import warnings

warnings.filterwarnings("ignore")
import pdfplumber

PARSER_NAME = "wio"
PARSER_VERSION = 1

# Page-1 content markers the registry can use to identify the format (D-006:
# detection is from content, never from the filename).
DETECT = ("wio", "credit statement")

DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
SIGNED_AMOUNT = re.compile(r"^[+-]?[\d,]+\.\d{2}$")
REF = re.compile(r"^[A-Z]\d{6,}$")

# x-band boundaries between Description / Card Number / Amount.
_CARD_X0 = 400.0
_AMOUNT_X0 = 540.0


def _iso(d):
    dd, mm, yyyy = d.split("/")
    return f"{yyyy}-{mm}-{dd}"


def _lines(page, tol=2.5):
    """Group words into visual lines, preserving x positions."""
    rows = {}
    for w in page.extract_words(use_text_flow=False, keep_blank_chars=False):
        rows.setdefault(round(w["top"] / tol), []).append(w)
    return [sorted(rows[k], key=lambda w: w["x0"]) for k in sorted(rows)]


def detect(text):
    """True if page-1 text looks like a Wio credit statement."""
    low = (text or "").lower()
    return all(marker in low for marker in DETECT)


def _detect(pdf):
    return detect(pdf.pages[0].extract_text() or "")


def _magnitude(to_minor, token):
    """Positive minor units for a possibly signed printed figure."""
    value = to_minor(token)
    return None if value is None else abs(value)


def parse(path):
    """Return (header, summary, transactions, rewards).

    Transaction amounts are integer fils, signed: negative = money out.
    Summary figures are positive magnitudes.
    """
    from analyser.money import to_minor

    header = {
        "issuer": "WIO",
        "currency": "AED",
        # D-007 -- a settlement facility, never counted as spending.
        "account_type": "CREDIT_FACILITY",
        "include_in_spending": 0,
    }
    summary, txns = {}, []

    with pdfplumber.open(path) as pdf:
        if not _detect(pdf):
            raise ValueError("not a Wio statement")
        header["page_count"] = len(pdf.pages)

        for pageno, page in enumerate(pdf.pages, start=1):
            for words in _lines(page):
                toks = [w["text"] for w in words]
                joined = " ".join(toks)
                label = joined.lower()

                # --- 'FROM 01/07/2026 TO 01/08/2026'
                if len(toks) == 4 and toks[0] == "FROM" and toks[2] == "TO":
                    header["period_start"] = _iso(toks[1])
                    header["period_end"] = _iso(toks[3])
                    header.setdefault("statement_date", _iso(toks[3]))
                    continue

                # --- 'ACCOUNT NUMBER 3688791844'
                if len(toks) == 3 and toks[0] == "ACCOUNT" and toks[1] == "NUMBER":
                    header["account_number"] = toks[2]
                    header.setdefault("masked_number", toks[2])
                    continue

                # --- 'AED 2.29% 27.48%'
                if len(toks) == 3 and toks[1].endswith("%") and toks[2].endswith("%"):
                    header["currency"] = toks[0]
                    header["monthly_interest_rate"] = toks[1]
                    header["annual_interest_rate"] = toks[2]
                    continue

                # --- '63,000.00 0.00'  (credit limit / total interest and fees)
                if (len(toks) == 2 and "credit_limit" not in header
                        and all(SIGNED_AMOUNT.match(t) for t in toks)
                        and "period_start" in header and "purchases_debits" not in summary):
                    header["credit_limit"] = to_minor(toks[0])
                    header["total_interest_and_fees"] = to_minor(toks[1])
                    continue

                # --- '01/08/2026 588.70 11,774.00'  (due date / min due / total)
                if (len(toks) == 3 and DATE.match(toks[0])
                        and all(SIGNED_AMOUNT.match(t) for t in toks[1:])):
                    header["payment_due_date"] = _iso(toks[0])
                    header["minimum_payment_due"] = to_minor(toks[1])
                    header["total_to_pay"] = to_minor(toks[2])
                    continue

                # --- 'Account summary' block: '<label> <signed amount>'
                if len(toks) >= 2 and SIGNED_AMOUNT.match(toks[-1]) and not DATE.match(toks[0]):
                    figure = _magnitude(to_minor, toks[-1])
                    if figure is None:
                        pass
                    elif label.startswith("balance from last statement"):
                        summary["opening_balance"] = figure
                    elif label.startswith("purchases"):
                        summary["purchases_debits"] = figure
                    elif label.startswith("interest"):
                        summary["finance_charges"] = figure
                    elif label.startswith("late payment fee"):
                        summary["late_payment_fee"] = figure
                    elif label.startswith("foreign exchange charges"):
                        summary["fx_charges"] = figure
                    elif label.startswith("payments and credits"):
                        summary["payments_credits"] = figure
                    elif label.startswith("closing balance"):
                        summary["closing_balance"] = figure
                        summary["total_payment_due"] = figure
                    continue

                # --- transaction row: '<date> <ref> <description...> [card] <amount>'
                if (len(toks) >= 3 and DATE.match(toks[0]) and REF.match(toks[1])
                        and SIGNED_AMOUNT.match(toks[-1])
                        and words[-1]["x0"] >= _AMOUNT_X0):
                    body = words[2:-1]
                    description = " ".join(
                        w["text"] for w in body if w["x0"] < _CARD_X0).strip()
                    card_number = " ".join(
                        w["text"] for w in body if _CARD_X0 <= w["x0"] < _AMOUNT_X0).strip()
                    amount = to_minor(toks[-1])
                    if not description or amount is None:
                        continue
                    txns.append({
                        "page_number": pageno,
                        "txn_date": _iso(toks[0]),
                        "posting_date": _iso(toks[0]),
                        "reference": toks[1],
                        "raw_description": description,
                        "card_number": card_number or None,
                        "currency": header.get("currency", "AED"),
                        # sign is printed on the figure: '-' out, '+' in
                        "amount_minor": amount,
                        "raw_text": joined,
                    })

    summary.setdefault("cash_advances", 0)
    return header, summary, txns, []
