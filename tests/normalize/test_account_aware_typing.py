"""Typing by which side of the balance sheet an account sits on.

The rules under test are deliberately issuer-agnostic: nothing here names a
bank. A statement from any retail lender should type correctly on the vocabulary
alone. All amounts invented — this repository is public.
"""
import pytest
from analyser.normalize import classify_txn_type as c
from analyser.domain.model import TxnType

pytestmark = pytest.mark.red

CARD = "CREDIT_CARD"
BANK = "BANK"


class TestMoneyInOnALiabilityIsNeverIncome:
    """The single rule that removes the largest class of confusion.

    Paying your own card bill puts money INTO the card account. Read as a
    ledger, that is an inbound amount; read economically it is a debt going
    down. Counting it as income inflates earnings by whatever you happen to
    repay each month.
    """

    @pytest.mark.parametrize("desc", [
        "PAYMENT RECEIVED - THANK YOU",
        "PAYMENT RECEIVED - FTS & SWIFT",
        "payments received thru someclearing 000000",
        "Credit Repayment Autopay",
        "CARD PAYMENT",
    ])
    def test_a_settlement_is_a_repayment(self, desc):
        assert c(desc, 5_000_00, None, CARD) == TxnType.PAYMENT

    def test_a_settlement_beats_the_channel_it_arrived_on(self):
        """A channel word says HOW the money travelled, not WHAT it was.

        "PAYMENT RECEIVED - FTS & SWIFT" is a card being paid off. Letting the
        SWIFT in it win would file a repayment as an internal movement.
        """
        assert c("PAYMENT RECEIVED - FTS & SWIFT", 7_050_00, None, CARD) == TxnType.PAYMENT
        assert c("TRANSFER PAYMENT RECEIVED THANK YOU", 1_928_00, None, CARD) == TxnType.PAYMENT

    def test_an_unnamed_card_credit_is_refused_not_assumed(self):
        """A credit on a card must reduce the debt somehow, which tempts a guess
        of "repayment". But issuers label real repayments — that is what the
        line is for — so an unlabelled credit carrying a merchant name is far
        more often a refund. Typing it as a repayment leaves the month's
        spending overstated, so neither answer is asserted."""
        assert c("SOME MERCHANT LLC DUBAI UAE", 8_93, None, CARD) == TxnType.UNKNOWN

    def test_no_credit_anywhere_becomes_a_purchase(self):
        for kind in (CARD, BANK, None):
            assert c("ANYTHING AT ALL", 1_000_00, None, kind) != TxnType.PURCHASE


class TestMoneyOutOfABankIsNotAutomaticallySpending:
    """The other half. A wire, a cheque and a cash withdrawal all leave an
    account without anything being bought."""

    @pytest.mark.parametrize("desc", [
        "TELEGRAPHIC TRF RMA TT REF: 000000",
        "OUTWARD TRF TO BENEFICIARY",
        "NEFT DR 000000",
        "RTGS TRANSFER",
        "STANDING ORDER TO 000000",
        "FUNDS TRANSFER TO 000000",
    ])
    def test_named_movements_are_transfers(self, desc):
        assert c(desc, -2_500_00, None, BANK) == TxnType.TRANSFER

    def test_cheques_are_cheques(self):
        assert c("CLEARING CHEQUES IN-HOUSE CHEQUE TRANSFER CHQ. NO: 0", -530_00,
                 None, BANK) == TxnType.CHEQUE

    def test_a_bank_cash_withdrawal_is_not_a_card_cash_advance(self):
        """Same act, different cost. Cash off a current account is your own
        money; cash off a card is borrowing at cash-advance rates."""
        assert c("DR ATM TRANSACTION CARD NO. 000000", -1_000_00, None, BANK) \
            == TxnType.CASH_WITHDRAWAL
        assert c("ATM CASH WITHDRAWAL", -1_000_00, None, CARD) == TxnType.CASH_ADVANCE

    def test_an_unnamed_bank_debit_still_reads_as_spending(self):
        """A direct debit to a utility is a genuine expense. Only NAMED
        movements are lifted out of spending."""
        assert c("SOME UTILITY COMPANY", -330_00, None, BANK) == TxnType.PURCHASE


class TestBorrowingIsNotSpendingAndNotIncome:
    def test_a_drawdown_and_its_repayment_are_different_events(self):
        """These shared one label before. A drawdown puts money in your hand and
        your debt up; an EMI takes money out and your debt down. One label made
        a loan look like an expense and its own disbursement look like income."""
        assert c("QUICK CASH BOOKING", -35_900_00, None, CARD) == TxnType.LOAN_DISBURSED
        assert c("CASH ON CALL", -10_000_00, None, CARD) == TxnType.LOAN_DISBURSED
        assert c("INSTALLMENT PLAN EMI (07/12)", -6_900_04, None, CARD) == TxnType.LOAN_REPAYMENT
        assert c("QC 12 M @ 0% + 4% PF", -2_991_67, None, CARD) == TxnType.LOAN_REPAYMENT

    def test_the_fee_on_a_loan_is_a_fee_not_the_loan(self):
        assert c("LOAN ON CARD PROCESSING FEE", -1_836_00, None, CARD) == TxnType.FEE

    def test_emi_is_matched_as_a_word_not_a_substring(self):
        """REMITTANCE and EMIRATES both contain "EMI". Matching it loose typed an
        arriving wire as a loan instalment."""
        assert c("INWARD REMITTANCE TT REF: 000000", 5_000_00, None, BANK) \
            != TxnType.LOAN_REPAYMENT
        assert c("EMIRATES SOMETHING LLC", -100_00, None, CARD) == TxnType.PURCHASE


class TestBackwardCompatibility:
    def test_omitting_the_account_kind_still_answers(self):
        """A caller that does not know the account gets the older sign-only
        behaviour rather than an exception."""
        assert c("SOME MERCHANT", -100_00) == TxnType.PURCHASE
        assert c("SOME CREDIT", 100_00) == TxnType.UNKNOWN


class TestSettlingAnotherAccountYouHold:
    """The last confusion: "Dubai First payment" leaving a credit facility.

    It is not a purchase — it is that facility settling a card the same person
    holds. What makes this safe to decide automatically is the ACCOUNT LIST:
    the line has to name a bank they actually bank with. Invented issuer names
    throughout.
    """

    HELD = ["ACME_BANK", "BRIGHTPAY", "NCB", "FIRST_UNION"]

    def test_a_payment_naming_a_bank_you_hold_is_a_movement(self):
        for desc in ("First Union payment",
                     "Acme Bank payment",
                     "First Union Rewards payment",  # the product sits in the middle
                     "PAYMENT TO FIRST UNION"):
            assert c(desc, -5_060_00, "BRIGHTPAY", "CREDIT_FACILITY", self.HELD) \
                == TxnType.TRANSFER, desc

    def test_a_merchant_that_merely_contains_the_word_payment_is_not(self):
        """"Any debit saying PAYMENT is a transfer" would swallow real purchases."""
        for desc in ("SOME MERCHANT PAYMENT GATEWAY",
                     "ONLINE PAYMENT SERVICES LLC"):
            assert c(desc, -50_00, "ACME_BANK", "CREDIT_CARD", self.HELD) \
                != TxnType.TRANSFER, desc

    def test_a_short_issuer_acronym_does_not_hijack_ordinary_english(self):
        """NCB is a bank here and an ordinary word elsewhere. Co-occurrence is
        not enough — the name has to sit NEXT TO the word payment, which is what
        separates "NCB OIL SHOP PAYMENT" from "Acme Bank payment"."""
        assert c("NCB OIL SHOP PAYMENT", -90_00, "ACME_BANK", "CREDIT_CARD", self.HELD) \
            == TxnType.PURCHASE

    def test_a_lookalike_merchant_is_not_the_bank(self):
        """Whole-phrase, word-boundary matching: an airline sharing a word with
        an issuer, and a shop whose name merely starts with one."""
        assert c("ACME AIRLINE TICKET PAYMENT", -3_500_00, "NCB", "CREDIT_CARD",
                 self.HELD) == TxnType.PURCHASE
        assert c("NCBINDIA STORE DUBAI", -120_00, "ACME_BANK", "CREDIT_CARD",
                 self.HELD) == TxnType.PURCHASE

    def test_an_account_is_never_read_as_paying_itself(self):
        assert c("Acme Bank payment", -100_00, "ACME_BANK", "CREDIT_CARD", self.HELD) \
            != TxnType.TRANSFER

    def test_without_an_account_list_nothing_changes(self):
        """The rule is evidence-driven: no account list, no inference."""
        assert c("First Union payment", -5_060_00, "BRIGHTPAY", "CREDIT_FACILITY") \
            == TxnType.PURCHASE
