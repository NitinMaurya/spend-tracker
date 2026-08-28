"""FAB parser — characterization against the real statement (D-004, D-026a)."""
import os
import pytest
from analyser.parsers.fab import parse
from tests.conftest import require_samples, SAMPLES

pytestmark = pytest.mark.golden
PDF = os.path.join(SAMPLES, "FAB_BLU_AUG_2026.pdf")


@pytest.fixture(scope="module")
def parsed():
    require_samples()
    if not os.path.exists(PDF):
        pytest.skip("FAB sample not present")
    return parse(PDF)


class TestHeader:
    def test_product_and_dates(self, parsed):
        h, _, _ = parsed
        assert h["product_name"] == "BLUE FAB SIGNAT"
        assert h["statement_date"] == "2026-08-01"
        assert h["payment_due_date"] == "2026-08-26"

    def test_pan_is_masked_in_the_source(self, parsed):
        h, _, _ = parsed
        assert "**" in h["masked_number"]


class TestReconciliation:
    """D-004: extraction is only trusted if it closes against the printed totals."""

    def test_debits_match_printed_purchases(self, parsed):
        _, s, t = parsed
        assert sum(-x["amount_minor"] for x in t if x["amount_minor"] < 0) == s["purchases_debits"]

    def test_credits_match_printed_payments(self, parsed):
        _, s, t = parsed
        assert sum(x["amount_minor"] for x in t if x["amount_minor"] > 0) == s["payments_credits"]

    def test_closing_balance_derives_from_the_summary(self, parsed):
        _, s, _ = parsed
        assert (s["opening_balance"] + s["purchases_debits"] + s["cash_advances"]
                + s["finance_charges"] - s["payments_credits"]) == s["total_payment_due"]


class TestTransactions:
    def test_expected_row_count(self, parsed):
        assert len(parsed[2]) == 6

    def test_both_dates_captured_and_iso(self, parsed):
        for x in parsed[2]:
            assert len(x["txn_date"]) == 10 and x["txn_date"][4] == "-"
            assert x["posting_date"] >= x["txn_date"]

    def test_payment_is_positive_debits_negative(self, parsed):
        rows = {x["raw_description"]: x["amount_minor"] for x in parsed[2]}
        assert rows["PAYMENT RECEIVED - THANK YOU"] > 0
        assert rows["Almosafer Travel Dubai AE"] < 0

    def test_charge_and_reversal_pair_survives_as_two_rows(self, parsed):
        """Both CAREEM PLUS AED 1.00 rows must be kept -- one debit, one credit."""
        careem = [x for x in parsed[2] if "CAREEM" in x["raw_description"]]
        assert len(careem) == 2
        assert sum(x["amount_minor"] for x in careem) == 0

    def test_description_is_not_truncated_at_a_three_letter_word(self, parsed):
        """Regression: 'YOU' in 'THANK YOU' once matched the currency pattern."""
        descs = [x["raw_description"] for x in parsed[2]]
        assert "PAYMENT RECEIVED - THANK YOU" in descs

    def test_currency_captured(self, parsed):
        assert all(x["currency"] == "AED" for x in parsed[2])
