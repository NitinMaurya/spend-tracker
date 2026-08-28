"""Mashreq noon parser — the hardest format: transaction dates carry NO year."""
import os
import pytest
from tests.conftest import require_samples, SAMPLES

pytestmark = pytest.mark.golden
PDF = os.path.join(SAMPLES, "Mashreq_noon_Aug_2026.pdf")


@pytest.fixture(scope="module")
def parsed():
    require_samples()
    if not os.path.exists(PDF):
        pytest.skip("Mashreq sample not present")
    from analyser.parsers.mashreq import parse
    return parse(PDF)


class TestHeader:
    def test_statement_dates(self, parsed):
        h, _, _, _ = parsed
        assert h["statement_date"] == "2026-08-06"
        assert h["payment_due_date"] == "2026-09-02"

    def test_product_and_masked_pan(self, parsed):
        h, _, _, _ = parsed
        assert "noon" in h["product_name"].lower()
        assert h["masked_number"].endswith("4286")


class TestYearInference:
    """Mashreq prints '21/07' with no year -- it must come from the statement date,
    never from the current clock (D-020c: dates are declared, never guessed)."""

    def test_year_is_inferred_from_the_statement_period(self, parsed):
        _, _, txns, _ = parsed
        assert txns[0]["txn_date"] == "2026-07-21"
        assert txns[0]["posting_date"] == "2026-07-23"

    def test_december_transaction_on_a_january_statement_wraps_back_a_year(self):
        """A 28/12 row on a 06/01/2027 statement is 2026, not 2027."""
        from analyser.parsers.mashreq import infer_year
        assert infer_year("28/12", statement_date="2027-01-06") == "2026-12-28"

    def test_same_month_does_not_wrap(self):
        from analyser.parsers.mashreq import infer_year
        assert infer_year("21/07", statement_date="2026-08-06") == "2026-07-21"


class TestReconciliation:
    def test_transactions_match_the_printed_subtotal(self, parsed):
        _, s, txns, _ = parsed
        assert sum(-t["amount_minor"] for t in txns if t["amount_minor"] < 0) == 3657

    def test_summary_closes(self, parsed):
        """previous -0.07 + new 36.57 = outstanding 36.50"""
        _, s, _, _ = parsed
        assert s["opening_balance"] == -7
        assert s["purchases_debits"] == 3657
        assert s["opening_balance"] + s["purchases_debits"] == s["total_payment_due"]


class TestTransactions:
    def test_single_transaction(self, parsed):
        assert len(parsed[2]) == 1

    def test_concatenated_merchant_is_preserved_raw(self, parsed):
        """'noondubai' has no separator; the parser must not invent one -- merchant
        splitting belongs to normalize (D-026b)."""
        assert parsed[2][0]["raw_description"].replace(" ", "").lower().startswith("noon")

    def test_spend_is_negative(self, parsed):
        assert parsed[2][0]["amount_minor"] == -3657

    def test_reference_number_captured(self, parsed):
        assert parsed[2][0].get("reference") == "74548996202202167787705"


class TestRewardBlock:
    """D-011: Mashreq prints the cashback it actually paid, per category."""

    def test_cashback_table_extracted(self, parsed):
        _, _, _, rewards = parsed
        assert len(rewards) == 1
        r = rewards[0]
        assert r["category_label"] == "Noon Spend"
        assert r["spend_minor"] == 3657
        assert r["rate_bps"] == 500
        assert r["earned"] == 183

    def test_reward_cycle_differs_from_the_statement_period(self, parsed):
        """T&C 3.1.4: posted 6th of previous month to 5th of current."""
        _, _, _, rewards = parsed
        assert rewards[0]["cycle_start"] == "2026-07-06"
        assert rewards[0]["cycle_end"] == "2026-08-05"
