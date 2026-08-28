"""Emirates NBD parser (D-006).

Emirates NBD sends THREE different documents from the same address, and they are
not variants of one layout -- they are different documents:

  1. ``Credit Card Statement``  -- the card statement the product analyses.
  2. ``Statement of Account``   -- a SAVINGS / CURRENT account e-statement.
     Parsed, but flagged ``account_type="BANK"`` / ``include_in_spending=0`` so a
     salary credit and a telegraphic transfer can never be counted as card spend.
  3. ``Repayment Schedule``     -- the installment (Loan on Card) booking advice.
     It has no transaction table and no statement totals, so it is REFUSED with a
     clear error rather than parsed into plausible-looking money (guardrail: a
     parser never guesses).

Which document it is, is decided from page-1 content, never from the file name.

Format notes -- credit card statement
-------------------------------------
* Dates are ``DD/MM/YYYY`` in the transaction table, ``DD-MMM-YY`` in the
  statement period. There is one Amount column, right-aligned, and the SIGN is
  carried by a glued-on ``CR`` suffix ("1,928.00CR" = money in). Anything without
  the suffix is a debit.
* The posting-date column is frequently EMPTY (installment rows carry only the
  transaction date), so the second token is only read as a posting date when it
  sits inside the posting-date column band.
* Both labelled blocks (the credit-limit strip and STATEMENT SUMMARY) are read by
  COLUMN GEOMETRY under the header labels, never by counting tokens: ENBD prints a
  small credit balance as ``-.18`` (no leading zero) and a credit as ``1,928.00CR``,
  neither of which is a bare number, and a count-based match silently loses the
  whole block.

The installment principal booking (D-004 hazard)
------------------------------------------------
When a Loan on Card is booked, the statement carries a row whose entire
description is the plan reference -- ``LOC-0215788936901  91,800.00``. That row is
NOT a spend: ENBD excludes it from both printed debit columns (Purchase / Cash
Advance and Interest/Other Charges), because the money is billed later as twelve
monthly ``INSTALLMENT PLAN EMI`` rows, each of which DOES appear in Purchase /
Cash Advance. Counting the booking as a debit would bill the same 91,800 twice.
It is therefore kept out of ``transactions`` and reported separately in
``header["installment_bookings"]`` so nothing is silently dropped, and the
evidence layer (D-018) still stores the line.

Format notes -- statement of account
-----------------------------------
* One date column, ``DDMMMYY`` ("01JUL26"), and SEPARATE Debit / Credit columns,
  so the sign comes from x-position; amounts are bound to a column by their right
  edge, since the figures are right-aligned and textually identical.
* An entry is a BLOCK, not a line: the date and the narrative are printed on
  several baselines, and the two templates in the sample put the figures on
  DIFFERENT lines of the block -- the first line in one, the last in the other.
  The block is therefore closed by the next dated row, not by the amount.
* There are no printed debit/credit totals to reconcile against, but there is a
  printed RUNNING BALANCE on every entry plus BROUGHT / CARRIED FORWARD. Those
  are checked instead, entry by entry, and any break raises: a figure bound to
  the wrong column cannot survive it.

Reconciliation
--------------
``analyser.ingest.reconcile`` compares the sum of debit rows against
``summary["purchases_debits"]``. ENBD splits its debits across TWO printed
columns, so ``purchases_debits`` is the sum of them both (Purchase / Cash Advance
+ Interest/Other Charges) -- the total the bank actually billed -- while
``finance_charges`` separately carries the Interest/Other Charges column.
``cash_advances`` is OMITTED: ENBD merges cash advances into the purchases
column, and a field that is absent must not be reported as zero.

The parser verifies that identity itself and RAISES on a mismatch rather than
emitting money that does not add up.

One consequence of the 2pt amount offset described below: a card payment row's
``raw_text`` spans two of the baselines that ``analyser.ingest`` groups into
lines, so that row does not bind to a single stored line in the evidence layer.
The evidence is still complete -- both baselines are stored -- and ``raw_text``
keeps the whole visual row rather than being trimmed to match.
"""
import re
import warnings

warnings.filterwarnings("ignore")
import pdfplumber

PARSER_NAME = "emirates_nbd"
PARSER_VERSION = 1

#: page-1 markers, matched against normalised (whitespace-collapsed) lower-case
#: text. Kept in sync with _SIGNATURES in analyser/parsers/__init__.py.
CARD_MARKERS = ("credit card statement", "emirates nbd bank")
ACCOUNT_MARKERS = ("statement of account", "emirates nbd")
INSTALLMENT_MARKERS = ("repayment schedule", "installment")

_DATE_SLASH = re.compile(r"^\d{2}/\d{2}/\d{4}$")           # 04/07/2026
_DATE_DASH_MON = re.compile(r"^\d{2}-[A-Za-z]{3}-\d{2}$")  # 03-Jul-26
_DATE_BANK = re.compile(r"^\d{2}[A-Z]{3}\d{2}$")           # 01JUL26

#: An amount as ENBD prints it: optional glued CR/Dr suffix, and a leading "-."
#: for balances under one dirham ("-.18").
_AMOUNT = re.compile(r"^-?(?:[\d,]*\.\d{2}|[\d,]+)(?:CR|DR|Cr|Dr)?$")
_STRICT_AMOUNT = re.compile(r"^-?[\d,]*\.\d{2}(?:CR|DR|Cr|Dr)?$")

#: The plan reference that identifies an installment principal booking.
_PLAN_REFERENCE = re.compile(r"^LOC-\d+$")

_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)}


class UnsupportedDocument(ValueError):
    """An Emirates NBD document this parser deliberately refuses to read."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _normalise(text):
    return re.sub(r"\s+", " ", text or "").lower()


#: Vertical clustering tolerances, in points. ENBD does NOT put a row's amount on
#: exactly the row's baseline -- "1,928.00CR" prints 2pt below the description it
#: belongs to -- so lines are built by CLUSTERING tops, not by bucketing them: a
#: bucket boundary happened to fall between the two and silently lost every
#: payment row. The Statement-of-Account detail block is looser still: its labels
#: and its values are printed ~1.5pt apart in two different columns.
_LINE_GAP = 3.0
_DETAIL_GAP = 5.0


def _cluster(words, gap):
    """Group words into visual lines by proximity of their tops."""
    out, current, base = [], [], None
    for w in sorted(words, key=lambda w: w["top"]):
        if base is not None and w["top"] - base > gap:
            out.append(sorted(current, key=lambda x: x["x0"]))
            current, base = [], None
        if base is None:
            base = w["top"]
        current.append(w)
    if current:
        out.append(sorted(current, key=lambda x: x["x0"]))
    return out


def _lines(page, gap=_LINE_GAP):
    return _cluster(page.extract_words(use_text_flow=False, keep_blank_chars=False), gap)


def _ascii_only(words):
    """Drop the Arabic half of a bilingual line; it shares the baseline."""
    return [w for w in words if w["text"].isascii()]


def _money(text):
    """Integer minor units for a figure as ENBD prints it. None if unparseable.

    Two ENBD-isms the shared ``to_minor`` does not know about:
      * a balance under one dirham loses its leading zero -- "-.18"
      * a deposit-account balance carries "Cr"/"Dr" rather than "CR"
    The sign convention is the one used throughout this codebase: POSITIVE means
    owed to the bank, so a credit ("Cr") balance is negative.
    """
    from analyser.money import to_minor

    s = str(text or "").strip()
    if not s:
        return None
    if s.upper().endswith("DR"):
        # Explicitly owed to the bank: strip the suffix, keep the sign positive.
        return to_minor(s[:-2].strip(), credit_suffix=False)
    s = re.sub(r"^(-?)\.", r"\g<1>0.", s)
    return to_minor(s)


def _magnitude(text):
    value = _money(text)
    return None if value is None else abs(value)


def _iso_slash(token):
    dd, mm, yyyy = token.split("/")
    return f"{yyyy}-{mm}-{dd}"


def _iso_dash_mon(token):
    dd, mon, yy = token.split("-")
    return f"20{yy}-{_MONTHS[mon.upper()]:02d}-{int(dd):02d}"


def _iso_bank(token):
    dd, mon, yy = token[:2], token[2:5], token[5:]
    return f"20{yy}-{_MONTHS[mon.upper()]:02d}-{int(dd):02d}"


def _columns(label_words, fields):
    """Resolve a labelled header row into per-field x-centres.

    `fields` is a sequence of (name, (label token, ...)) in PRINTED ORDER; the
    tokens are matched left-to-right and CONSUMED, which is what keeps "Credit
    Limit" from being found inside "Available Credit Limit (AED)".

    Returns None if the row is not the expected one -- callers raise rather than
    guess at an unfamiliar layout.
    """
    words = _ascii_only(label_words)
    index = 0
    centres = {}
    for name, labels in fields:
        while index < len(words) and words[index]["text"] != labels[0]:
            index += 1
        if index + len(labels) > len(words):
            return None
        span = words[index:index + len(labels)]
        if [w["text"] for w in span] != list(labels):
            return None
        centres[name] = (span[0]["x0"] + span[-1]["x1"]) / 2
        index += len(labels)
    return centres


def _values_by_column(value_words, centres, *, tolerance=30.0):
    """Bind each value on a row to the column it actually sits under."""
    out = {}
    for w in _ascii_only(value_words):
        centre = (w["x0"] + w["x1"]) / 2
        field = min(centres, key=lambda f: abs(centres[f] - centre))
        if abs(centres[field] - centre) <= tolerance and field not in out:
            out[field] = w["text"]
    return out


# ---------------------------------------------------------------------------
# credit card statement
# ---------------------------------------------------------------------------

_LIMIT_FIELDS = (
    ("credit_limit", ("Credit", "Limit")),
    ("available_limit", ("Available", "Credit", "Limit", "(AED)")),
    ("statement_date", ("Statement", "Date")),
    ("payment_due_date", ("Payment", "Due", "Date")),
    ("minimum_due", ("Minimum", "Payment", "Due")),
)

_SUMMARY_FIELDS = (
    ("opening_balance", ("Previous", "Statement")),
    ("purchase_cash", ("Purchase", "/", "Cash")),
    ("interest_other", ("Interest/Other",)),
    ("payments_credits", ("Payments/Credits", "(AED)")),
    ("total_payment_due", ("Total", "Payment", "Due", "(AED)")),
    ("closing_balance", ("Current", "Balance", "(AED)")),
)

_POINTS_FIELDS = (
    ("opening_balance", ("Plus", "Points", "Opening", "Balance")),
    ("earned", ("Plus", "Points", "Earned")),
    ("adjusted", ("Plus", "Points", "Adjusted")),
    ("redeemed", ("Plus", "Points", "Redeemed")),
    ("closing_balance", ("Plus", "Points", "Closing", "Balance")),
)

_TXN_HEADER = ("Transaction", "Date", "Posting", "Date", "Description", "Amount")


def _labelled_row(lines, index, fields, parse_value, required=None):
    """Read the value row that follows a label row, by column geometry.

    `required` names the columns that must be present for a row to BE the value
    row; the search skips the label block's continuation lines until it finds
    one. Columns outside `required` that do not print are simply absent from the
    result -- an absent figure is never reported as zero.
    """
    centres = _columns(lines[index], fields)
    if not centres:
        return None
    required = tuple(required) if required else tuple(name for name, _ in fields)
    for row in lines[index + 1:index + 4]:
        values = _values_by_column(row, centres)
        if any(name not in values for name in required):
            continue            # still inside the (two-line) label block
        parsed = {}
        for name, text in values.items():
            value = parse_value(name, text)
            if value is None:
                return None
            parsed[name] = value
        return parsed
    return None


def _card_header_row(lines, index):
    def value(name, text):
        if name in ("statement_date", "payment_due_date"):
            return _iso_slash(text) if _DATE_SLASH.match(text) else None
        return _magnitude(text)
    # The two dates identify the row; a limit that does not print stays absent.
    return _labelled_row(lines, index, _LIMIT_FIELDS, value,
                         required=("statement_date", "payment_due_date"))


def _card_summary_row(lines, index):
    def value(name, text):
        if not _AMOUNT.match(text):
            return None
        # Balances keep their printed sign; the flow columns are magnitudes,
        # which is what reconcile() compares against.
        return _money(text) if name.endswith("balance") else _magnitude(text)
    return _labelled_row(lines, index, _SUMMARY_FIELDS, value)


def _points_row(lines, index):
    def value(_name, text):
        return int(text.replace(",", "")) if text.replace(",", "").isdigit() else None
    return _labelled_row(lines, index, _POINTS_FIELDS, value)


def _parse_card(pdf):
    header = {"issuer": "EMIRATES_NBD", "currency": "AED",
              "account_type": "CREDIT_CARD", "include_in_spending": 1,
              "page_count": len(pdf.pages)}
    summary, txns, rewards = {}, [], []
    bookings = []
    printed = None

    for pageno, page in enumerate(pdf.pages, start=1):
        lines = _lines(page)
        posting_band = None
        in_table = False

        for index, words in enumerate(lines):
            ascii_words = _ascii_only(words)
            toks = [w["text"] for w in ascii_words]
            joined = " ".join(toks)

            # --- 'Card Number: 4XXX XXXX XXXX NNNN' and 'Card Type: VISA FLEXI'.
            # Read from the label token: the mailing address prints on the same
            # baseline, so the row does not begin with the label.
            if "Number:" in toks and "masked_number" not in header:
                header["masked_number"] = " ".join(toks[toks.index("Number:") + 1:])
                continue
            if "Type:" in toks and "product_name" not in header:
                header["product_name"] = " ".join(toks[toks.index("Type:") + 1:])
                continue

            # --- 'Statement Period: 03-Jul-26 to 02-Aug-26' (shares a baseline
            #     with 'Page 1 of 4', so read from the label, not the row)
            if "Period:" in toks and "period_start" not in header:
                at = toks.index("Period:")
                window = toks[at + 1:at + 4]
                if len(window) == 3 and all(_DATE_DASH_MON.match(t)
                                            for t in (window[0], window[2])):
                    header["period_start"] = _iso_dash_mon(window[0])
                    header["period_end"] = _iso_dash_mon(window[2])
                continue

            # --- credit-limit strip, by column geometry
            if toks[:2] == ["Credit", "Limit"] and "statement_date" not in header:
                row = _card_header_row(lines, index)
                if row is None:
                    raise ValueError(
                        "Emirates NBD: credit-limit block not recognised on "
                        f"page {pageno}")
                header["statement_date"] = row.pop("statement_date")
                header["payment_due_date"] = row.pop("payment_due_date")
                summary.update(row)   # only the limits that actually printed
                continue

            # --- transaction table header: fixes the posting-date column band
            if toks[:len(_TXN_HEADER)] == list(_TXN_HEADER):
                posting = ascii_words[2:4]
                posting_band = (posting[0]["x0"] - 10, posting[-1]["x1"] + 25)
                in_table = True
                continue

            if joined.startswith("STATEMENT SUMMARY"):
                in_table = False

            # --- STATEMENT SUMMARY block, by column geometry
            if toks[:2] == ["Previous", "Statement"] and printed is None:
                printed = _card_summary_row(lines, index)
                if printed is None:
                    raise ValueError(
                        "Emirates NBD: STATEMENT SUMMARY block not recognised on "
                        f"page {pageno}")
                continue

            # --- PLUS POINTS SUMMARY (D-011)
            if toks[:4] == ["Plus", "Points", "Opening", "Balance"] and not rewards:
                points = _points_row(lines, index)
                if points is not None:
                    points.update({"reward_unit": "PLUS_POINTS",
                                   "cycle_start": header.get("period_start"),
                                   "cycle_end": header.get("period_end"),
                                   "source_page": pageno})
                    rewards.append(points)
                continue

            if not in_table or not toks or not _DATE_SLASH.match(toks[0]):
                continue

            # --- transaction row: '<txn date> [<posting date>] <desc...> <amount>'
            amount_word = ascii_words[-1]
            if not _STRICT_AMOUNT.match(amount_word["text"]):
                continue
            rest = ascii_words[1:-1]
            posting_date = None
            if (rest and _DATE_SLASH.match(rest[0]["text"]) and posting_band
                    and posting_band[0] <= rest[0]["x0"] <= posting_band[1]):
                posting_date = _iso_slash(rest[0]["text"])
                rest = rest[1:]
            description = " ".join(w["text"] for w in rest).strip()
            if not description:
                continue

            magnitude = _magnitude(amount_word["text"])
            if magnitude is None:
                raise ValueError(
                    f"Emirates NBD: unreadable amount {amount_word['text']!r} "
                    f"on page {pageno}")
            is_credit = amount_word["text"].upper().endswith("CR")

            if _PLAN_REFERENCE.match(description):
                # Installment principal booking -- billed later as EMIs, and
                # excluded by the bank from both printed debit columns.
                bookings.append({
                    "reference": description,
                    "booking_date": _iso_slash(toks[0]),
                    "amount_minor": magnitude,
                    "page_number": pageno,
                    "raw_text": joined,
                })
                continue

            txns.append({
                "page_number": pageno,
                "txn_date": _iso_slash(toks[0]),
                "posting_date": posting_date,
                "raw_description": description,
                "currency": "AED",
                "amount_minor": magnitude if is_credit else -magnitude,
                "raw_text": joined,
            })

    if printed is None:
        raise ValueError("Emirates NBD: no STATEMENT SUMMARY block found")
    if bookings:
        header["installment_bookings"] = bookings

    summary["opening_balance"] = printed["opening_balance"]
    summary["closing_balance"] = printed["closing_balance"]
    summary["payments_credits"] = printed["payments_credits"]
    summary["total_payment_due"] = printed["total_payment_due"]
    summary["finance_charges"] = printed["interest_other"]
    # Both printed debit columns together: what reconcile() compares the rows
    # against. cash_advances is deliberately absent -- ENBD does not print it.
    summary["purchases_debits"] = printed["purchase_cash"] + printed["interest_other"]

    _verify(summary, txns, "credit card statement")
    return header, summary, txns, rewards


# ---------------------------------------------------------------------------
# statement of account (SAVINGS / CURRENT)
# ---------------------------------------------------------------------------

_BANK_HEADER = ("Date", "Details", "Debit", "Credit", "Balance")
#: A line further down the page than this, in points, is no longer part of the
#: transaction table -- ENBD prints its footer far below the last entry.
_BANK_MAX_GAP = 40.0
#: Details-column band: continuation lines are indented into it.
_BANK_DETAIL_BAND = (90.0, 300.0)


def _bank_amount(word, anchors):
    """Which printed column an amount sits in, by right edge."""
    field = min(anchors, key=lambda f: abs(anchors[f] - word["x1"]))
    if abs(anchors[field] - word["x1"]) > 60:
        return None
    return field


def _flush(block, txns):
    """Emit a finished ledger entry. An entry the printed running balance never
    accounted for is a parse failure, not a transaction."""
    if block is None:
        return
    if block["amount"] is None:
        raise ValueError("Emirates NBD: ledger entry with no debit or credit on "
                         f"page {block['page_number']}: {block['raw_text']!r}")
    if block["balance"] is None:
        raise ValueError("Emirates NBD: ledger entry with no running balance on "
                         f"page {block['page_number']}: {block['raw_text']!r}")
    txns.append({
        "page_number": block["page_number"],
        "txn_date": block["date"],
        "posting_date": block["date"],   # a bank ledger prints one date only
        "raw_description": " ".join(block["description"]).strip(),
        "currency": "AED",
        "amount_minor": block["amount"],
        "raw_text": block["raw_text"],
    })


def _read_account_details(header, words):
    """Read the 'Statement Details' block of a Statement of Account.

    Its labels and its values are printed as two separate columns whose baselines
    differ by a point or two, so this block is clustered more loosely than the
    ledger below it -- otherwise every label reads as a row with no value.
    """
    for row in _cluster(words, _DETAIL_GAP):
        toks = [w["text"] for w in _ascii_only(row)]
        if not toks:
            continue

        # 'Statement Date: 12 AUG, 2026'
        if toks[:2] == ["Statement", "Date:"] and "statement_date" not in header:
            rest = [t.strip(",") for t in toks[2:]]
            if len(rest) == 3 and rest[1].upper() in _MONTHS:
                header["statement_date"] = (
                    f"{rest[2]}-{_MONTHS[rest[1].upper()]:02d}-{int(rest[0]):02d}")
            continue

        # 'From 02/07/2026 to 01/08/2026'
        if toks[0] == "From" and "period_start" not in header:
            dates = [t for t in toks if _DATE_SLASH.match(t)]
            if len(dates) == 2:
                header["period_start"] = _iso_slash(dates[0])
                header["period_end"] = _iso_slash(dates[1])
            continue

        if toks[:2] == ["Account", "type"] and len(toks) > 2:
            header["product_name"] = " ".join(toks[2:])
            continue

        if toks[:2] == ["Account", "number"] and len(toks) > 2:
            header["account_number"] = toks[2]
            header.setdefault("masked_number", toks[2])
            continue

        if toks[0] == "IBAN" and len(toks) > 1:
            header["iban"] = "".join(toks[1:])


def _parse_account(pdf):
    header = {
        "issuer": "EMIRATES_NBD",
        "currency": "AED",
        # Not a spending card: its debits are transfers, and its credits are
        # salary. Counting them as card spend would be double counting (D-007).
        "account_type": "BANK",
        "include_in_spending": 0,
        "page_count": len(pdf.pages),
    }
    summary, txns = {}, []
    opening = closing = None
    running = None

    for pageno, page in enumerate(pdf.pages, start=1):
        words_on_page = page.extract_words(use_text_flow=False,
                                           keep_blank_chars=False)
        lines = _cluster(words_on_page, _LINE_GAP)
        ledger_at = next(
            (i for i, row in enumerate(lines)
             if [w["text"] for w in _ascii_only(row)][:len(_BANK_HEADER)]
             == list(_BANK_HEADER)),
            None)
        if ledger_at is None:
            raise ValueError(
                f"Emirates NBD: no Date/Details/Debit/Credit/Balance header on "
                f"page {pageno}")

        ledger_header = _ascii_only(lines[ledger_at])
        anchors = {"debit": ledger_header[2]["x1"],
                   "credit": ledger_header[3]["x1"],
                   "balance": ledger_header[4]["x1"]}
        _read_account_details(header,
                              [w for w in words_on_page
                               if w["top"] < ledger_header[0]["top"] - 1])

        block, checked = None, False
        previous_top = ledger_header[0]["top"]

        for words in lines[ledger_at + 1:]:
            ascii_words = _ascii_only(words)
            if not ascii_words:
                continue
            toks = [w["text"] for w in ascii_words]
            joined = " ".join(toks)
            top = ascii_words[0]["top"]
            if joined.startswith("Confirmation of the correctness"):
                break
            if previous_top is not None and top - previous_top > _BANK_MAX_GAP \
                    and not joined.startswith("CARRIED FORWARD"):
                break

            amounts = {}
            for w in ascii_words:
                if not _STRICT_AMOUNT.match(w["text"]):
                    continue
                field = _bank_amount(w, anchors)
                if field:
                    amounts[field] = w["text"]

            is_new_row = _DATE_BANK.match(toks[0]) is not None
            starts_carried = joined.startswith("CARRIED FORWARD")

            if is_new_row or starts_carried:
                _flush(block, txns)
                block, checked = None, False
                rest = toks[1:] if is_new_row else toks
                label = " ".join(rest)
                if label.startswith("BROUGHT FORWARD") or starts_carried:
                    balance = amounts.get("balance")
                    if balance is None:
                        raise ValueError(
                            "Emirates NBD: %s row without a balance on page %d"
                            % (label, pageno))
                    if label.startswith("BROUGHT FORWARD"):
                        if opening is None:
                            opening = _money(balance)
                            running = -opening
                        elif running != -_money(balance):
                            # A continuation page must carry forward what the
                            # previous page ended on.
                            raise ValueError(
                                "Emirates NBD: BROUGHT FORWARD on page %d does "
                                "not match the previous page" % pageno)
                    else:
                        closing = _money(balance)
                    previous_top = top
                    if starts_carried:
                        break
                    continue
                block = {
                    "page_number": pageno,
                    "date": _iso_bank(toks[0]),
                    "description": [t for t in rest
                                    if not _STRICT_AMOUNT.match(t)],
                    "raw_text": joined,
                    "amount": None,
                    "balance": None,
                }
            elif block is not None and _BANK_DETAIL_BAND[0] <= ascii_words[0]["x0"] \
                    <= _BANK_DETAIL_BAND[1]:
                block["description"].extend(
                    t for t in toks if not _STRICT_AMOUNT.match(t))
            else:
                previous_top = top
                continue

            previous_top = top
            if block is None:
                continue

            for field, text in amounts.items():
                if field == "balance":
                    block["balance"] = _money(text)
                    continue
                value = _magnitude(text)
                if value is None:
                    raise ValueError(
                        f"Emirates NBD: unreadable amount {text!r} on page {pageno}")
                if block["amount"] is not None:
                    raise ValueError(
                        "Emirates NBD: two amounts in one ledger entry on page "
                        f"{pageno}: {block['raw_text']!r}")
                block["amount"] = value if field == "credit" else -value

            if "balance" in amounts and not checked:
                if block["amount"] is None:
                    raise ValueError(
                        "Emirates NBD: ledger entry with a balance but no debit or "
                        f"credit on page {pageno}: {block['raw_text']!r}")
                if running is None:
                    raise ValueError(
                        "Emirates NBD: ledger entry before BROUGHT FORWARD on page "
                        f"{pageno}")
                # The printed running balance is the check: an entry bound to the
                # wrong column, or a row read twice, breaks it immediately.
                running += block["amount"]
                if running != -block["balance"]:
                    raise ValueError(
                        "Emirates NBD: running balance does not follow at "
                        f"{block['raw_text']!r} (computed {running}, "
                        f"printed {-block['balance']})")
                checked = True

        _flush(block, txns)

    if opening is None:
        raise ValueError("Emirates NBD: no BROUGHT FORWARD row found")
    if closing is None:
        if running is None:
            raise ValueError("Emirates NBD: no closing balance found")
        closing = -running

    debits = sum(-t["amount_minor"] for t in txns if t["amount_minor"] < 0)
    credits = sum(t["amount_minor"] for t in txns if t["amount_minor"] > 0)
    if -opening + credits - debits != -closing:
        raise ValueError(
            "Emirates NBD: ledger does not close: opening %d + credits %d - "
            "debits %d != closing %d" % (opening, credits, debits, closing))

    summary["opening_balance"] = opening
    summary["closing_balance"] = closing
    summary["purchases_debits"] = debits
    summary["payments_credits"] = credits

    _verify(summary, txns, "statement of account")
    return header, summary, txns, []


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def _verify(summary, txns, kind):
    """D-004, enforced inside the parser: rows must equal the printed totals."""
    from analyser.ingest import reconcile

    ok, why = reconcile(summary, txns)
    if not ok:
        raise ValueError(f"Emirates NBD {kind} does not reconcile: {why}")


def detect(text):
    """Which Emirates NBD document `text` (page-1 text) is, or None."""
    low = _normalise(text)
    if all(m in low for m in CARD_MARKERS):
        return "CARD"
    if all(m in low for m in ACCOUNT_MARKERS):
        return "ACCOUNT"
    if all(m in low for m in INSTALLMENT_MARKERS):
        return "INSTALLMENT"
    return None


def parse(path):
    """Return (header, summary, transactions, rewards).

    Transaction amounts are integer fils, signed: NEGATIVE = money out.
    Summary flow figures are positive magnitudes; balances keep their printed
    sign, where positive means owed to the bank.
    """
    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            raise ValueError("Emirates NBD: empty document")
        page_one = pdf.pages[0].extract_text() or ""
        if not page_one.strip():
            page_one = pdf.pages[0].extract_text(layout=True) or ""
        kind = detect(page_one)
        if kind == "CARD":
            return _parse_card(pdf)
        if kind == "ACCOUNT":
            return _parse_account(pdf)
        if kind == "INSTALLMENT":
            raise UnsupportedDocument(
                "Emirates NBD installment repayment schedule: a booking advice "
                "with no transaction table and no statement totals, not a "
                "statement. Refused rather than guessed at.")
        raise ValueError("not an Emirates NBD statement")
