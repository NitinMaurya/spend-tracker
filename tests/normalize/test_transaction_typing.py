"""Transaction typing — spec §F2. A payment must never read as spending."""
import pytest
from analyser.normalize import classify_txn_type
from analyser.domain.model import TxnType

pytestmark = pytest.mark.red


class TestFromRealStatements:
    @pytest.mark.parametrize("desc,amount,expected", [
        ("PAYMENT RECEIVED - THANK YOU",      56400,  TxnType.PAYMENT),
        ("Credit Repayment Autopay",         1177400, TxnType.PAYMENT),
        ("Almosafer Travel Dubai AE",         -87019, TxnType.PURCHASE),
        ("EMARAT 7185 AL KHAIL DUBAI AE",     -20214, TxnType.PURCHASE),
        ("DUBAI ELECTRICITY DUBAI AE",        -33121, TxnType.PURCHASE),
        ("noondubai",                          -3657, TxnType.PURCHASE),
    ])
    def test_real_rows_type_correctly(self, desc, amount, expected):
        assert classify_txn_type(desc, amount) == expected

    def test_positive_amount_is_never_a_purchase(self):
        """The single most damaging misclassification: inflating spend."""
        assert classify_txn_type("SOME UNKNOWN CREDIT", 50000) != TxnType.PURCHASE

    def test_unrecognised_money_in_is_unknown_not_guessed(self):
        """Spec §P4: prefer UNKNOWN over a confident wrong answer.

        Only asserted for money IN. An unrecognised money-OUT row must type as
        PURCHASE -- the parametrised real rows above ('noondubai', -3657) require it,
        since most genuine merchant strings are unknown to any keyword table."""
        t = classify_txn_type("ZZQQ 4471", 1000)
        assert t == TxnType.UNKNOWN
        assert t not in (TxnType.PURCHASE, TxnType.PAYMENT, TxnType.REFUND)

    def test_unrecognised_money_out_defaults_to_purchase(self):
        assert classify_txn_type("ZZQQ 4471", -1000) == TxnType.PURCHASE

    @pytest.mark.parametrize("desc", ["ANNUAL FEE", "LATE PAYMENT FEE", "OVER LIMIT FEE"])
    def test_fees_are_typed_as_fees(self, desc):
        assert classify_txn_type(desc, -10500) == TxnType.FEE

    @pytest.mark.parametrize("desc", ["FINANCE CHARGE", "RETAIL PROFIT", "INTEREST CHARGED"])
    def test_interest_and_profit_both_type_as_interest(self, desc):
        """D-020g: Emirates Islamic says 'profit', not 'interest'."""
        assert classify_txn_type(desc, -25000) == TxnType.INTEREST

    def test_cash_advance_detected(self):
        assert classify_txn_type("CASH ADVANCE ATM DUBAI", -100000) in (
            TxnType.CASH_ADVANCE, TxnType.CASH_WITHDRAWAL)
