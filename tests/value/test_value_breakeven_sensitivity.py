"""Net value, break-even, sensitivity — spec §F14/16/17, D-010, D-016b, D-024."""
import pytest
from analyser.domain import net_value, break_even_spend, sensitivity_bands
from analyser.domain.model import AnalysisHorizon, Confidence, TxnType
from tests.conftest import txn, aed

pytestmark = pytest.mark.red


class TestNetValue:
    def test_components_are_exposed_not_just_the_total(self, capped_card, horizon):
        txns = [txn(f"2026-{m:02d}-10", -6000, category="GROCERIES") for m in range(1, 13)]
        r = net_value(txns, capped_card, horizon)
        assert r.rewards == aed(1200)          # 100/cycle capped x 12
        assert r.annual_fee == aed(525)
        assert r.net == aed(675)

    def test_year_one_and_steady_state_are_both_reported(self, capped_card, horizon):
        """D-016b: a waived first-year fee often flips the decision."""
        from dataclasses import replace
        card = replace(capped_card, annual_fee=aed(525))
        txns = [txn(f"2026-{m:02d}-10", -6000, category="GROCERIES") for m in range(1, 13)]
        y1 = net_value(txns, card, horizon, year_one=True)
        ss = net_value(txns, card, horizon, year_one=False)
        assert y1.net >= ss.net

    def test_perks_contribute_zero_without_an_explicit_assumption(self, noon_card, horizon):
        """D-014: no auto-valued perks."""
        txns = [txn("2026-03-10", -1000, posting="2026-03-11", category="NOON")]
        r = net_value(txns, noon_card, horizon)
        assert r.perk_value == aed(0)

    def test_non_cash_equivalent_rewards_are_not_added_at_face_value(self, noon_card, horizon):
        """D-024: noon cashback is redeemable only on noon platforms."""
        txns = [txn("2026-03-10", -10000, posting="2026-03-11", category="NOON")]
        r = net_value(txns, noon_card, horizon)
        assert any("redemption" in a.label.lower() or "noon" in a.value.lower()
                   for a in r.assumptions)

    def test_financing_charge_is_a_cost_line(self, noon_card, horizon):
        """D-016e / D-020g: charge_basis may be INTEREST or PROFIT."""
        txns = [
            txn("2026-03-10", -1000, posting="2026-03-11", category="NOON"),
            txn("2026-03-28", -250, posting="2026-03-29", ttype=TxnType.INTEREST),
        ]
        r = net_value(txns, noon_card, horizon)
        assert r.financing_cost == aed(250)


class TestBreakEven:
    def test_simple_break_even(self, capped_card):
        """525 annual fee at an effective 1% -> 52,500 of spend."""
        assert break_even_spend(capped_card, {"DINING": 1.0}) == aed(52500)

    def test_break_even_respects_caps(self, capped_card):
        """At 5% capped to 100/cycle, grocery spend cannot alone clear a 525 fee:
        max grocery reward is 1,200/yr, so break-even exists but is cap-bounded."""
        be = break_even_spend(capped_card, {"GROCERIES": 1.0})
        assert be <= aed(126000)

    def test_unreachable_break_even_is_reported_not_infinite(self, capped_card):
        """If caps make the fee unrecoverable, return None rather than a huge number."""
        from dataclasses import replace
        card = replace(capped_card, annual_fee=aed(100000))
        assert break_even_spend(card, {"GROCERIES": 1.0}) is None


class TestSensitivity:
    """D-010: bands are DERIVED from confidence, never chosen."""

    def test_low_confidence_is_ineligible_in_the_conservative_band(self, noon_card, horizon):
        txns = [
            txn("2026-03-10", -1000, posting="2026-03-11", category="NOON",
                confidence=Confidence.HIGH),
            txn("2026-03-11", -1000, posting="2026-03-12", category="NOON",
                confidence=Confidence.LOW),
        ]
        cons, exp, opt = sensitivity_bands(txns, noon_card, horizon)
        assert cons == aed(50)      # only the HIGH-confidence 1,000 at 5%
        assert exp == aed(100)
        assert cons < exp

    def test_bands_are_ordered(self, noon_card, horizon):
        txns = [txn("2026-03-10", -1000, posting="2026-03-11", category="NOON",
                    confidence=Confidence.LOW)]
        cons, exp, opt = sensitivity_bands(txns, noon_card, horizon)
        assert cons <= exp <= opt

    def test_all_high_confidence_collapses_the_band(self, noon_card, horizon):
        txns = [txn("2026-03-10", -1000, posting="2026-03-11", category="NOON",
                    confidence=Confidence.HIGH)]
        cons, exp, opt = sensitivity_bands(txns, noon_card, horizon)
        assert cons == exp == opt
