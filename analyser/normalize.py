"""Merchant normalization, categorization, transaction typing.

Everything here is deterministic (D-026b) and local (D-026c): an explicit alias
dictionary plus regex cleanup. No fuzzy/similarity matching -- `AL MAYA` and
`AL MAHA` are unrelated businesses that differ by one character -- and no
merchant string ever leaves the machine.
"""
import re

from analyser.domain.model import Confidence, TxnType

# --- transaction typing (spec §F2) -------------------------------------------

# Checked in order; the first hit wins. FEE precedes PAYMENT because
# "LATE PAYMENT FEE" contains both words.
_TYPE_RULES = (
    (TxnType.FEE, (
        "annual fee", "late payment fee", "over limit fee", "overlimit fee",
        "membership fee", "service fee", "processing fee", "card fee",
        "replacement fee", " fee", "fee ", "charge fee", "vat",
    )),
    (TxnType.INTEREST, (
        "finance charge", "financial charge", "interest", "profit",
        "murabaha", "retail profit", "cash profit",
    )),
    (TxnType.CASH_ADVANCE, ("cash advance", "cash withdrawal", "atm withdrawal")),
    (TxnType.PAYMENT, (
        "payment received", "credit repayment", "repayment", "autopay",
        "auto pay", "payment - thank you", "thank you", "payment thru",
        "online payment", "bill payment received",
    )),
    (TxnType.REVERSAL, ("reversal", "reversed")),
    (TxnType.REFUND, ("refund", "return", "chargeback")),
)


def classify_txn_type(raw_description, amount_minor, issuer=None):
    """Spec §F2: PURCHASE / REFUND / PAYMENT / FEE / INTEREST / ... never guess.

    The SIGN is authoritative in one direction: a positive (money-in) amount can
    never be a purchase, because inflating spend is the most damaging possible
    misclassification.
    """

    # Credit-card loans and their repayments are FINANCING, not spending (D-028b).
    # "QC 12 M @ 0% + 4% PF" is Quick Cash over 12 months; the monthly EMI that
    # repays it is debt service. Counting either as a purchase double-counts money
    # the cardholder never spent at a merchant.
    _desc = (raw_description or "").upper()
    import re as _re

    # An internal adjustment posted as a matched +/- pair nets to zero. It is
    # bookkeeping, not money moving anywhere.
    if "INTERNAL ADJUSTMENT" in _desc or "REVERSAL PAIR" in _desc:
        return TxnType.ADJUSTMENT

    # Mashreq labels an inbound card payment "inward ipp cc - ln<number>". Confirmed
    # by the cardholder: these are payments made TO the card, not refunds and not a
    # loan disbursement. Typing matters -- a refund would reduce that month's spend
    # (D-016a), which would be wrong here.
    if "INWARD IPP" in _desc:
        return TxnType.PAYMENT
    if (_re.search(r"\bQC\s*\d+\s*M\b", _desc)
            or "QUICK CASH" in _desc          # the loan BOOKING, not just its EMIs
            or "CASH ON CALL" in _desc
            or "LOAN ON CARD" in _desc
            or "SMART CASH" in _desc
            or "EMI" in _desc
            or "INSTALLMENT" in _desc or "INSTALMENT" in _desc
            or _desc.startswith("LOC-")
            or "EASY PAYMENT PLAN" in _desc
            or "BALANCE TRANSFER" in _desc):
        return TxnType.CASH_ADVANCE
    text = (raw_description or "").lower()

    matched = None
    for txn_type, keywords in _TYPE_RULES:
        if any(k in text for k in keywords):
            matched = txn_type
            break

    positive = amount_minor is not None and amount_minor > 0

    if matched is not None:
        if positive and matched in (TxnType.PURCHASE, TxnType.CASH_ADVANCE):
            return TxnType.UNKNOWN
        return matched

    if positive:
        # Money in, nothing recognised: UNKNOWN beats a confident wrong answer.
        return TxnType.UNKNOWN
    if amount_minor is None:
        return TxnType.UNKNOWN
    return TxnType.PURCHASE


# --- merchant normalization (D-026b) -----------------------------------------

_COUNTRY_TOKENS = {
    "AE", "UAE", "ARE", "US", "USA", "GB", "UK", "IN", "SA", "KSA", "QA",
    "OM", "BH", "KW", "EG", "TR", "NL", "DE", "FR", "SG",
}

# Longest-first so "ABU DHABI" wins over "DHABI"-style partial suffixes.
_CITIES = (
    "RAS AL KHAIMAH", "UMM AL QUWAIN", "ABU DHABI", "AL AIN", "DUBAI",
    "SHARJAH", "AJMAN", "FUJAIRAH", "DXB", "AUH",
)

_TERMINAL_ID = re.compile(r"\b\d{3,}\b")
_MULTISPACE = re.compile(r"\s+")


def _strip_suffixes(text):
    """Strip trailing country code and city name. Only ever from the END, so
    'DUBAI ELECTRICITY DUBAI AE' keeps its leading 'DUBAI'."""
    city = None
    changed = True
    while changed:
        changed = False
        tokens = text.split()
        if tokens and tokens[-1] in _COUNTRY_TOKENS:
            text = " ".join(tokens[:-1])
            changed = True
            continue
        for candidate in _CITIES:
            if text.endswith(" " + candidate) or text == candidate:
                stripped = text[: len(text) - len(candidate)].strip()
                if stripped:                      # never strip away the whole name
                    city = city or candidate.title()
                    text = stripped
                    changed = True
                break
    return text, city


def normalize_merchant(raw_description, issuer=None, alias_map=None):
    """D-026b: deterministic only. Returns (canonical|None, city|None, confidence)."""
    if not raw_description or not raw_description.strip():
        return None, None, Confidence.UNKNOWN

    aliases = alias_map or {}
    upper = _MULTISPACE.sub(" ", raw_description.strip().upper())

    cleaned, city = _strip_suffixes(upper)
    cleaned = _MULTISPACE.sub(" ", _TERMINAL_ID.sub(" ", cleaned)).strip() or cleaned

    # 1. Exact alias, then longest alias appearing at a word boundary.
    for candidate in (cleaned, upper):
        if candidate in aliases:
            return aliases[candidate], city, Confidence.HIGH

    for key in sorted(aliases, key=len, reverse=True):
        if re.search(r"(?<![A-Z0-9])" + re.escape(key) + r"(?![A-Z0-9])", cleaned):
            return aliases[key], city, Confidence.HIGH

    # 2. Concatenated merchant+city with no separator (Mashreq prints "noondubai").
    squashed = re.sub(r"[^A-Z0-9]", "", upper)
    for key in sorted(aliases, key=len, reverse=True):
        squashed_key = re.sub(r"[^A-Z0-9]", "", key)
        if not squashed_key or not squashed.startswith(squashed_key):
            continue
        remainder = squashed[len(squashed_key):]
        if not remainder:
            return aliases[key], city, Confidence.HIGH
        for candidate_city in _CITIES:
            if remainder == re.sub(r"[^A-Z0-9]", "", candidate_city):
                return aliases[key], candidate_city.title(), Confidence.HIGH

    # 3. Unmatched: keep the cleaned raw string, flag it for the correction queue.
    #    NO similarity matching -- AL MAYA and AL MAHA must stay distinct.
    return (cleaned or upper), city, Confidence.UNKNOWN


# --- categorization (D-026c) --------------------------------------------------

def categorize(canonical_merchant, raw_description, category_map=None):
    """D-026c: rules + user corrections only. Never a hosted model, never a
    network call. Returns (category|None, confidence)."""
    mapping = category_map or {}

    if canonical_merchant and canonical_merchant in mapping:
        return mapping[canonical_merchant], Confidence.HIGH

    raw = (raw_description or "").strip()
    if raw and raw in mapping:
        return mapping[raw], Confidence.HIGH

    # Unknown beats a confident wrong category (spec §P4).
    return None, Confidence.UNKNOWN
