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


# Account kinds. What a sign MEANS depends on which side of the balance sheet
# the account sits on, and that is the single most useful generic signal there
# is: on a liability, money-in reduces a debt; on an asset, money-in is a
# receipt. Nothing below needs to know which bank issued the statement.
LIABILITY_ACCOUNTS = frozenset({"CREDIT_CARD", "CREDIT_FACILITY", "LOAN"})
ASSET_ACCOUNTS = frozenset({"BANK", "CURRENT", "SAVINGS", "WALLET"})

# Vocabulary shared by retail bank statements generally, not by one issuer.
# Each entry is matched against the UPPERCASED description.
_LOAN_DRAWN = (
    "QUICK CASH BOOKING", "QUICK CASH", "CASH ON CALL", "LOAN ON CARD",
    "SMART CASH", "BALANCE TRANSFER", "LOAN DISBURSE", "DISBURSEMENT",
)
_LOAN_REPAID = (
    "EASY PAYMENT PLAN", "INSTALLMENT PLAN", "INSTALMENT PLAN",
    "INSTALLMENT", "INSTALMENT",
)
_TRANSFER_WORDS = (
    # Bare "TRANSFER"/"TRF" belong here: every compound form below is a special
    # case of them, and a statement line carrying the word is describing a
    # movement. Loan drawdowns ("BALANCE TRANSFER") and card settlements
    # ("TRANSFER PAYMENT RECEIVED") are both resolved above this point.
    "TRANSFER", "TRF", "TELEGRAPHIC", "TT REF", "REMITTANCE", "BANKNET",
    "FUND TRANSFER", "FUNDS TRANSFER", "OWN ACCOUNT", "ACCOUNT TRANSFER",
    "TRANSFER TO", "TRANSFER FROM", "OUTWARD TRF", "INWARD TRF",
    "TELEGRAPHIC TRF", "NEFT", "RTGS", "IMPS", "UPI", "SEPA", "SWIFT",
    "ACH ", "GIRO", "STANDING ORDER", "STANDING INSTRUCTION",
)
_ATM_WORDS = ("ATM", "CASH WITHDRAWAL", "CASH WDL", "CASH DISPENS")
_CHEQUE_WORDS = ("CHEQUE", "CHQ", "CLEARING CHEQUES", "CHECK DEPOSIT")
_SALARY_WORDS = ("SALARY", "PAYROLL", "WAGES")
_SETTLEMENT_WORDS = (
    "PAYMENT RECEIVED", "PAYMENTS RECEIVED", "CREDIT REPAYMENT", "REPAYMENT",
    "AUTOPAY", "AUTO PAY", "THANK YOU", "PAYMENT THRU", "ONLINE PAYMENT",
    "BILL PAYMENT RECEIVED", "CARD PAYMENT",
)


def _has(desc, words):
    return any(w in desc for w in words)


def _settles_another_provider(desc, known_issuers, own_issuer):
    """Does this line read as "<a bank you bank with> payment"?

    Two conditions, and both are load-bearing.

    The name is matched as a whole phrase on word boundaries, so "EMIRATES NBD"
    is found in "Emirates NBD payment" while "EMIRATES AIRLINE" matches nothing,
    and a single-token issuer like FAB is found in "Blu Fab payment" without
    also firing on "FABINDIA".

    The name must also sit NEXT TO the word payment, with at most one word
    between them. Short issuer acronyms are ordinary English -- CBD is a bank
    here and a product everywhere else -- so mere co-occurrence is not enough:
    "CBD OIL SHOP PAYMENT" is a purchase, and only adjacency separates it from
    "Dubai First payment". One intervening word is allowed because issuers put
    the product in the middle ("Mashreq Noon payment").
    """
    own = (own_issuer or "").upper().replace("_", " ").strip()
    for raw in known_issuers or ():
        name = (raw or "").upper().replace("_", " ").strip()
        if not name or name == own:
            continue
        n = re.escape(name)
        if (re.search(rf"\b{n}\b(?:\s+\w+)?\s+PAYMENT\b", desc)
                or re.search(rf"\bPAYMENT\b(?:\s+\w+)?\s+{n}\b", desc)):
            return True
    return False


def classify_txn_type(raw_description, amount_minor, issuer=None, account_type=None,
                      known_issuers=None):
    """Spec §F2: PURCHASE / REFUND / PAYMENT / FEE / INTEREST / ... never guess.

    Two signals decide a row, and neither is the issuer's name:

    THE SIGN, which is authoritative in one direction -- a positive (money-in)
    amount can never be a purchase, because inflating spend is the most damaging
    possible misclassification.

    THE ACCOUNT KIND, which is what makes the sign mean anything. Money arriving
    on a LIABILITY is a debt going down: a repayment or a refund, never earnings.
    Money leaving an ASSET is not automatically a purchase: a wire, a cheque and
    a cash withdrawal all leave an account without anything being bought. Reading
    every bank debit as a purchase is what makes a ledger claim you spent your
    rent at a merchant.

    `account_type` is optional and defaults to the older sign-only behaviour, so
    a caller that does not know the account still gets a defensible answer.
    """
    _desc = (raw_description or "").upper()
    text = (raw_description or "").lower()
    positive = amount_minor is not None and amount_minor > 0
    negative = amount_minor is not None and amount_minor < 0
    kind = (account_type or "").upper()
    is_liability = kind in LIABILITY_ACCOUNTS
    is_asset = kind in ASSET_ACCOUNTS

    # An internal adjustment posted as a matched +/- pair nets to zero. It is
    # bookkeeping, not money moving anywhere.
    if "INTERNAL ADJUSTMENT" in _desc or "REVERSAL PAIR" in _desc:
        return TxnType.ADJUSTMENT

    # Mashreq labels an inbound card payment "inward ipp cc - ln<number>".
    # Confirmed by the cardholder: payments made TO the card, not refunds and not
    # a loan disbursement. Typing matters -- a refund would reduce that month's
    # spend (D-016a), which would be wrong here.
    if "INWARD IPP" in _desc:
        return TxnType.PAYMENT

    # Salary. The statement NAMES it, so this is reading the page rather than
    # inferring intent from an amount that happens to recur monthly. The positive
    # guard matters: a row that merely mentions salary while money LEAVES (a
    # salary-advance repayment, a payroll fee) is not income, and typing it as
    # income would credit earnings that never arrived.
    if positive and _has(_desc, _SALARY_WORDS):
        return TxnType.SALARY

    # --- borrowing, and the servicing of it ---------------------------------
    # Split apart because they are opposite events that used to share one label.
    # A drawdown puts money in your hand and your debt up; an EMI takes money out
    # and your debt down. Calling both CASH_ADVANCE made a loan look like an
    # expense and its own disbursement look like income.
    fee_flavoured = "FEE" in _desc or "VAT" in _desc
    if _has(_desc, _LOAN_DRAWN) and not fee_flavoured:
        # The drawdown itself. On the card it is booked as a debit (the debt) and
        # on the receiving account as a credit (the cash) -- both are the same
        # event, and transfer matching pairs them.
        return TxnType.LOAN_DISBURSED
    if (re.search(r"\bEMI\b", _desc)
            or re.search(r"\bQC\s*\d+\s*M\b", _desc)
            or _has(_desc, _LOAN_REPAID)
            or _desc.startswith("LOC-")):
        return TxnType.LOAN_REPAYMENT
    if _has(_desc, _LOAN_DRAWN) and fee_flavoured:
        return TxnType.FEE

    # A settlement names WHAT the money was; a channel word names HOW it
    # travelled. "PAYMENT RECEIVED - FTS & SWIFT" is a card being paid off, and
    # reading the SWIFT in it as a transfer loses that. What outranks what has to
    # be decided here, because both vocabularies legitimately appear in one line.
    if positive and is_liability and _has(_desc, _SETTLEMENT_WORDS):
        return TxnType.PAYMENT

    # Money LEAVING that calls itself a payment and names one of your own
    # providers. "Dubai First payment" on a credit facility is that facility
    # settling a card you hold -- an internal movement, not a purchase.
    #
    # The provider name is what makes this safe. "Any debit containing PAYMENT is
    # a transfer" would swallow genuine purchases at merchants with the word in
    # their name; requiring the line to name a bank YOU HOLD AN ACCOUNT WITH is
    # evidence from your own account list rather than a guess about a word. The
    # account's own issuer is excluded, so a card is never read as paying itself.
    if negative and known_issuers and _settles_another_provider(
            _desc, known_issuers, issuer):
        return TxnType.TRANSFER

    # --- money that moves without being earned or spent ---------------------
    if _has(_desc, _CHEQUE_WORDS):
        return TxnType.CHEQUE
    if _has(_desc, _ATM_WORDS):
        # A withdrawal on a card is borrowing at cash-advance rates; on a current
        # account it is simply your own money in a different form.
        return TxnType.CASH_ADVANCE if is_liability else TxnType.CASH_WITHDRAWAL
    if _has(_desc, _TRANSFER_WORDS):
        return TxnType.TRANSFER

    # --- the original keyword table ----------------------------------------
    matched = None
    for txn_type, keywords in _TYPE_RULES:
        if any(k in text for k in keywords):
            matched = txn_type
            break

    if matched is not None:
        if positive and matched in (TxnType.PURCHASE, TxnType.CASH_ADVANCE):
            return TxnType.UNKNOWN
        # Deliberately NOT reclassifying an outbound "payment" on a liability as
        # a transfer on the strength of the word alone: that swallows real
        # merchants ("ONLINE PAYMENT SERVICES LLC"). The provider-name rule above
        # covers the genuine case with evidence from the account list instead.
        return matched

    # --- fallbacks, decided by which side of the balance sheet we are on ----
    if positive:
        # Money in that the statement never named, on either kind of account.
        #
        # It is tempting to call an unnamed card credit a repayment, since a
        # credit on a liability must reduce the debt somehow. But issuers label
        # real repayments -- that is what the line is for -- so an unlabelled
        # credit carrying a merchant name is far more often a refund, and typing
        # it as a repayment would leave that month's spending overstated. Neither
        # answer is supported by the page, so neither is asserted.
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
