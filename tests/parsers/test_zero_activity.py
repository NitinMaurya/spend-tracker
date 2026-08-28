"""CBD and Emirates Islamic — bilingual statements with no transactions.

Both interleave Arabic and English on the same baseline, so line-based parsing
breaks; these parsers must work on x-coordinate bands (D-006).
"""
import os
import pytest
from tests.conftest import require_samples, SAMPLES

pytestmark = pytest.mark.golden


@pytest.fixture(scope="module")
def cbd():
    require_samples()
    p = os.path.join(SAMPLES, "CBD_AUG_2026.pdf")
    if not os.path.exists(p):
        pytest.skip("CBD sample not present")
    from analyser.parsers.cbd import parse
    return parse(p)


@pytest.fixture(scope="module")
def eislamic():
    require_samples()
    p = os.path.join(SAMPLES, "Emirates_islamic_RTA_Platinum_AUG_2026.pdf")
    if not os.path.exists(p):
        pytest.skip("Emirates Islamic sample not present")
    from analyser.parsers.emirates_islamic import parse
    return parse(p)


class TestCBD:
    def test_two_date_formats_in_one_document_both_parse(self, cbd):
        """CBD prints the period as YYYY-MM-DD and the statement date as DD-MM-YYYY."""
        h, _, _, _ = cbd
        assert h["statement_date"] == "2026-08-12"
        assert h["period_start"] == "2026-07-13"
        assert h["period_end"] == "2026-08-12"

    def test_cr_suffix_is_a_credit_balance(self, cbd):
        """'0.59 CR' means the bank owes the cardholder -- a NEGATIVE balance."""
        _, s, _, _ = cbd
        assert s["closing_balance"] == -59

    def test_zero_activity_is_not_a_parse_failure(self, cbd):
        """'No Transactions Available' is a valid statement, not an error."""
        _, _, txns, _ = cbd
        assert txns == []

    def test_zero_activity_reconciles(self, cbd):
        from analyser.ingest import reconcile
        _, s, txns, _ = cbd
        ok, _ = reconcile(s, txns)
        assert ok

    def test_product_name(self, cbd):
        assert cbd[0]["product_name"] == "CBD ONE"


class TestEmiratesIslamic:
    def test_ordinal_date_format_parses(self, eislamic):
        """Emirates Islamic prints '11th Jul 2026'."""
        h, _, _, _ = eislamic
        assert h["period_start"] == "2026-07-11"
        assert h["period_end"] == "2026-08-10"

    def test_zero_activity(self, eislamic):
        assert eislamic[2] == []

    def test_cashback_summary_extracted(self, eislamic):
        """D-011: opening 195, earned 0, adjusted 0, redeemed 0, closing 195."""
        _, _, _, rewards = eislamic
        assert len(rewards) == 1
        r = rewards[0]
        assert r["opening_balance"] == 195
        assert r["earned"] == 0
        assert r["redeemed"] == 0
        assert r["closing_balance"] == 195

    def test_arabic_text_does_not_leak_into_english_fields(self, eislamic):
        """The bilingual layout must not contaminate extracted values."""
        h, _, _, _ = eislamic
        assert all(ord(c) < 0x0600 for c in h["product_name"])
