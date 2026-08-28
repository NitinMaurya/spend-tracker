"""Emirates Islamic credit card statement parser (D-006).

Format notes observed in the sample:
  * Bilingual. Arabic and English share the SAME baseline all over the page
    (headers, warning blocks, the summary strip), so a text-line parser reads
    interleaved nonsense. Everything here is done with x-coordinate banding on
    `extract_words`, and Arabic tokens are dropped before any English field is
    built (D-006 hazard row: "Arabic on shared baselines").
  * Dates are ORDINAL: "From:11th Jul 2026" / "To:10th Aug 2026". The label is
    glued to the day token, so the colon is split off before parsing.
  * The payment-due date in the summary strip is DD/MM/YY.
  * The page-1 "Rewards Summary" block prints the cashback ledger
    (opening / earned / adjusted / redeemed / closing) in whole AED, NOT in
    minor units — these are the issuer's ground-truth reward figures (D-011).
  * A cycle with no activity prints no transaction rows at all; that is a valid
    statement, not a parse failure, so transactions come back as [].
"""
import re
import warnings

warnings.filterwarnings("ignore")
import pdfplumber

class UnsupportedDocument(ValueError):
    """Raised when the layout is recognised but cannot be parsed safely."""


PARSER_NAME = "emirates_islamic"
PARSER_VERSION = 1

# Everything below U+0600 is "not Arabic" for our purposes; the statement's
# English band is plain ASCII.
ARABIC_START = 0x0600

ORDINAL_DATE = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)\s+([A-Za-z]{3,9})\.?\s+(\d{4})", re.IGNORECASE
)
SHORT_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{2,4})$")
AMOUNT = re.compile(r"^-?[\d,]+\.\d{2}$")
INT = re.compile(r"^-?[\d,]+$")
MASK = re.compile(r"^[X\d]{4}$", re.IGNORECASE)

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# No product/card-type string is printed anywhere in the document (see the
# module docstring of the test): the only English title is "Statement of Card
# Account". Fall back to the issuer's generic product label so the field is
# always present and always ASCII.
DEFAULT_PRODUCT_NAME = "Emirates Islamic Credit Card"

REWARD_KEYS = {
    "OPENING": "opening_balance",
    "EARNED": "earned",
    "ADJUSTED": "adjusted",
    "REDEEMED": "redeemed",
    "CLOSING": "closing_balance",
}


def _is_english(text):
    return all(ord(c) < ARABIC_START for c in text)


def _ascii_words(page):
    """Words on the page with every Arabic token removed."""
    return [w for w in page.extract_words(use_text_flow=False, keep_blank_chars=False)
            if _is_english(w["text"])]


def _lines(words, tol=2.5):
    """Group words into visual lines, preserving x positions."""
    rows = {}
    for w in words:
        rows.setdefault(round(w["top"] / tol), []).append(w)
    return [sorted(rows[k], key=lambda w: w["x0"]) for k in sorted(rows)]


def _iso_ordinal(text):
    """'11th Jul 2026' -> '2026-07-11'."""
    m = ORDINAL_DATE.search(text)
    if not m:
        return None
    day, month_name, year = m.group(1), m.group(2).lower()[:4], m.group(3)
    month = MONTHS.get(month_name) or MONTHS.get(month_name[:3])
    if not month:
        return None
    return f"{year}-{month:02d}-{int(day):02d}"


def _iso_short(text):
    """'04/09/26' -> '2026-09-04'."""
    m = SHORT_DATE.match(text)
    if not m:
        return None
    dd, mm, yy = m.groups()
    year = int(yy) if len(yy) == 4 else 2000 + int(yy)
    return f"{year}-{int(mm):02d}-{int(dd):02d}"


def _to_int(text):
    if not INT.match(text or ""):
        return None
    return int(text.replace(",", ""))


def _detect(pdf):
    head = pdf.pages[0].extract_text() or ""
    if not _is_english(head):
        head = "".join(c for c in head if ord(c) < ARABIC_START)
    lowered = head.lower()
    return "emiratesislamic" in lowered or "emirates islamic" in lowered


def _period(lines):
    """Read the ordinal From:/To: pair out of the statement-period band."""
    start = end = None
    for words in lines:
        text = " ".join(w["text"] for w in words)
        if start is None and "From:" in text:
            start = _iso_ordinal(text.split("From:", 1)[1])
        if end is None and "To:" in text:
            end = _iso_ordinal(text.split("To:", 1)[1])
    return start, end


def _masked_number(lines):
    for words in lines:
        toks = [w["text"] for w in words]
        if "Number.:" not in toks and "Number:" not in toks:
            continue
        idx = toks.index("Number.:" if "Number.:" in toks else "Number:")
        tail = [t for t in toks[idx + 1:] if MASK.match(t)]
        if len(tail) >= 4:
            return " ".join(tail[:4])
    return None


def _summary(lines):
    """The single figures row under the Card Limit / Available Limit strip.

    Layout (x ascending):
      Card Limit | Available Limit | Min Payment Due | Due Date |
      Total Payment Due | Profit/Other Charges | Current Balance
    """
    from analyser.money import to_minor

    header_top = None
    for words in lines:
        toks = [w["text"] for w in words]
        if "Card" in toks and "Limit" in toks and "Available" in toks:
            header_top = words[0]["top"]
            break
    if header_top is None:
        return {}

    for words in lines:
        if words[0]["top"] <= header_top:
            continue
        toks = [w["text"] for w in words]
        amounts = [t for t in toks if AMOUNT.match(t)]
        dates = [t for t in toks if SHORT_DATE.match(t)]
        if len(amounts) < 6 or not dates:
            continue
        limit, available, minimum, total_due, charges, balance = (
            to_minor(a) for a in amounts[:6]
        )
        return {
            "credit_limit": limit,
            "available_limit": available,
            "minimum_payment_due": minimum,
            "payment_due_date": _iso_short(dates[0]),
            "total_payment_due": total_due,
            "finance_charges": charges,
            "closing_balance": balance,
            # Emirates Islamic prints NO purchases / cash-advance / payments
            # totals anywhere in the document -- the summary strip carries only
            # limits, dues, profit charges and the current balance. Those keys
            # are therefore OMITTED, not zeroed: missing must not mean zero.
        }
    return {}


def _rewards(lines):
    """Page-1 'Rewards Summary' cashback ledger -> at most one dict (D-011).

    Values are whole AED as printed by the issuer, not minor units.
    """
    seen = {}
    for words in lines:
        toks = [w["text"] for w in words]
        if not toks or toks[0].upper() != "CASHBACK":
            continue
        key = next((REWARD_KEYS[t.upper()] for t in toks[1:] if t.upper() in REWARD_KEYS), None)
        if key is None:
            continue
        value = next((_to_int(t) for t in reversed(toks) if _to_int(t) is not None), None)
        if value is None:
            continue
        seen.setdefault(key, value)

    if not seen:
        return []
    return [{
        "opening_balance": seen.get("opening_balance", 0),
        "earned": seen.get("earned", 0),
        "adjusted": seen.get("adjusted", 0),
        "redeemed": seen.get("redeemed", 0),
        "closing_balance": seen.get("closing_balance", 0),
        "reward_unit": "AED",
    }]


def _product_name(lines):
    """Any printed card-product line, else the issuer's generic label.

    Guaranteed ASCII: the candidate lines are drawn from the Arabic-stripped
    word list, and the fallback is a constant.
    """
    for words in lines:
        text = " ".join(w["text"] for w in words).strip()
        if re.search(r"(?i)\b(platinum|titanium|signature|infinite|world|classic|gold|"
                     r"skywards|emarati|flexi|business)\b", text) and len(text) <= 60:
            return text
    return DEFAULT_PRODUCT_NAME


def parse(path):
    """Return (header, summary, transactions, rewards).

    Amounts are integer fils, signed: negative = money out. A statement with no
    posted activity returns transactions == [].
    """
    header, summary, txns, rewards = {}, {}, [], []

    with pdfplumber.open(path) as pdf:
        if not _detect(pdf):
            raise ValueError("not an Emirates Islamic statement")
        header["page_count"] = len(pdf.pages)

        first_lines = _lines(_ascii_words(pdf.pages[0]))

        start, end = _period(first_lines)
        header["period_start"] = start
        header["period_end"] = end
        header["statement_date"] = end
        header["masked_number"] = _masked_number(first_lines)
        header["product_name"] = _product_name(first_lines)

        summary = _summary(first_lines)
        if summary.get("payment_due_date"):
            header["payment_due_date"] = summary["payment_due_date"]

        rewards = _rewards(first_lines)

        # Transaction band: rows sit under the Post Date / Trxn. Date header and
        # begin with two dates. This cycle has none -- the loop is what makes an
        # empty result a legitimate parse rather than a silent gap.
        for pageno, page in enumerate(pdf.pages, start=1):
            lines = first_lines if pageno == 1 else _lines(_ascii_words(page))
            for words in lines:
                toks = [w["text"] for w in words]
                if len(toks) < 4 or not SHORT_DATE.match(toks[0]) or not SHORT_DATE.match(toks[1]):
                    continue
                amounts = [w for w in words if AMOUNT.match(w["text"])]
                if not amounts:
                    continue
                # Every Emirates Islamic cycle sampled so far is dormant, so no
                # posted row has ever been seen and the issuer's DIRECTION
                # marker for this table is unknown: we cannot tell a purchase
                # from a payment, and the amount column prints an unsigned
                # magnitude. Emitting it would be plausible-but-wrong money in
                # an unknown direction, so refuse instead of guessing.
                raise UnsupportedDocument(
                    "Emirates Islamic transaction row found, but this issuer's "
                    "debit/credit marker has never been observed (every sampled "
                    "cycle is zero-activity). Refusing to emit an amount whose "
                    "sign cannot be established: "
                    + " ".join(toks)
                )

    return header, summary, txns, rewards
