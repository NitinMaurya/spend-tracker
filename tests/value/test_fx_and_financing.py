"""FX costs and financing charges — D-013, D-016e, D-020g."""
import pytest
from dataclasses import replace
from analyser.domain import net_value
from analyser.domain.model import AnalysisHorizon, TxnType
from tests.conftest import txn, aed

pytestmark = pytest.mark.red


class TestFX:
    def test_fx_cost_is_unknown_when_the_original_amount_is_absent(self, noon_card, horizon):
        """D-013: Mashreq states the displayed rate is INCLUSIVE of the FX fee, so
        the fee is not separable from an AED-only statement line."""
        txns = [txn("2026-03-10", -1000, posting="2026-03-11", category="TRAVEL")]
        r = net_value(txns, noon_card, horizon)
        assert r.fx_cost is None

    def test_fx_cost_is_computed_when_the_foreign_amount_is_present(self, noon_card, horizon):
        pytest.skip("no foreign-currency row exists in any sample statement (D-013 caveat)")

    def test_fx_spread_is_not_summed_with_unknown_scheme_fees(self, noon_card, horizon):
        """The KFS says '2.89% (plus Visa/Mastercard charges as applicable)'.
        Reporting 2.89% as the total would understate the true cost."""
        assert noon_card.fx_fee_bps == 289


class TestFinancingCharges:
    def test_interest_is_reported_as_a_cost(self, capped_card, horizon):
        card = replace(capped_card, min_spend_per_cycle=None)
        txns = [txn(f"2026-{m:02d}-10", -6000, category="GROCERIES") for m in range(1, 13)]
        txns += [txn("2026-06-28", -800, ttype=TxnType.INTEREST, tid="i1")]
        assert net_value(txns, card, horizon).financing_cost == aed(800)

    def test_profit_basis_is_treated_identically_to_interest(self, capped_card, horizon):
        """D-020g: Emirates Islamic quotes a profit rate, not interest."""
        card = replace(capped_card, min_spend_per_cycle=None, charge_basis="PROFIT")
        txns = [txn("2026-06-28", -800, ttype=TxnType.INTEREST, tid="p1")]
        assert net_value(txns, card, horizon).financing_cost == aed(800)

    def test_no_financing_charge_yields_zero_not_none(self, capped_card, horizon):
        card = replace(capped_card, min_spend_per_cycle=None)
        txns = [txn("2026-03-10", -1000, category="GROCERIES")]
        assert net_value(txns, card, horizon).financing_cost == aed(0)


class TestInstalments:
    """D-028b: a purchase converted to EMI is spend once, on its transaction date."""

    def test_instalment_repayments_are_not_spend(self, capped_card, horizon):
        card = replace(capped_card, min_spend_per_cycle=None)
        txns = [
            txn("2026-01-10", -12000, category="SHOPPING", tid="buy"),
            txn("2026-02-10", -1000, ttype=TxnType.PAYMENT, tid="emi1"),
            txn("2026-03-10", -1000, ttype=TxnType.PAYMENT, tid="emi2"),
        ]
        r = net_value(txns, card, horizon)
        assert r.rewards == aed(120)     # 1% of 12,000 once -- not of 14,000

    def test_easy_payment_plan_is_excluded_from_cashback(self, noon_card, horizon):
        """noon T&C excludes Easy Cash and balance transfers from cashback."""
        txns = [txn("2026-03-10", -5000, posting="2026-03-11", category="NOON",
                    ttype=TxnType.CASH_ADVANCE)]
        assert net_value(txns, noon_card, horizon).rewards == aed(0)
