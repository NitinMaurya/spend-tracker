"""Reward engine: rates, caps, minimums, rounding — spec §F11–13, D-016, D-023."""
import pytest
from analyser.domain import compute_rewards, apply_rounding
from analyser.domain.model import RoundingSpec, AnalysisHorizon, Money, TxnType
from tests.conftest import txn, aed

pytestmark = pytest.mark.red


class TestGroundTruth:
    """D-011: validate against what the bank actually paid, not our assumptions."""

    def test_mashreq_noon_july_2026_matches_the_printed_statement(self, noon_card):
        """Statement prints: Noon Spend | 36.57 | 5% | Cash Back Earned 1.83
        KFS confirms 5% on noon platforms. 36.57 x 5% = 1.8285 -> 1.83 (HALF_UP)."""
        h = AnalysisHorizon(start="2026-07-06", months=1)
        txns = [txn("2026-07-21", -36.57, posting="2026-07-23",
                    category="NOON", merchant="noon")]
        assert compute_rewards(txns, noon_card, h).total == aed("1.83")

    def test_tiered_rates_apply_per_category(self, noon_card):
        h = AnalysisHorizon(start="2026-07-06", months=1)
        txns = [
            txn("2026-07-10", -1000, posting="2026-07-11", category="NOON"),      # 5%  = 50
            txn("2026-07-11", -1000, posting="2026-07-12", category="DINING"),    # 1%  = 10
            txn("2026-07-12", -1000, posting="2026-07-13", category="UTILITIES"), # .33%= 3.30
        ]
        assert compute_rewards(txns, noon_card, h).total == aed("63.30")

    def test_lowest_priority_tier_is_the_catch_all(self, noon_card):
        h = AnalysisHorizon(start="2026-07-06", months=1)
        txns = [txn("2026-07-10", -500, posting="2026-07-11", category="SOMETHING_NEW")]
        assert compute_rewards(txns, noon_card, h).total == aed("5.00")


class TestCaps:
    """Spec §F12 and §14 example 1 — the engine must never exceed a contractual cap.

    The shared fixture also carries a 5,000/cycle minimum; these tests isolate cap
    behaviour, so the minimum is removed. Minimum-spend behaviour is covered by
    TestMinimumSpend and by adversarial example 5.
    """

    @pytest.fixture
    def capped_card(self, capped_card):
        from dataclasses import replace
        return replace(capped_card, min_spend_per_cycle=None)

    def test_cap_binds(self, capped_card):
        h = AnalysisHorizon(start="2026-01-01", months=1)
        txns = [txn("2026-01-10", -4000, category="GROCERIES")]   # 5% = 200, cap 100
        r = compute_rewards(txns, capped_card, h)
        assert r.total == aed(100)
        assert any(l.cap_applied for l in r.lines)

    def test_below_cap_is_untouched(self, capped_card):
        h = AnalysisHorizon(start="2026-01-01", months=1)
        txns = [txn("2026-01-10", -1000, category="GROCERIES")]   # 5% = 50
        r = compute_rewards(txns, capped_card, h)
        assert r.total == aed(50)
        assert not any(l.cap_applied for l in r.lines)

    def test_cap_resets_each_cycle_and_does_not_carry(self, capped_card):
        h = AnalysisHorizon(start="2026-01-01", months=2)
        txns = [
            txn("2026-01-10", -4000, category="GROCERIES"),   # capped at 100
            txn("2026-02-10", -1000, category="GROCERIES"),   # 50, cap not reached
        ]
        assert compute_rewards(txns, capped_card, h).total == aed(150)

    def test_uncapped_tier_still_earns_when_capped_tier_is_full(self, capped_card):
        h = AnalysisHorizon(start="2026-01-01", months=1)
        txns = [
            txn("2026-01-10", -4000, category="GROCERIES"),   # 5% capped -> 100
            txn("2026-01-11", -1000, category="DINING"),      # 1% uncapped -> 10
        ]
        assert compute_rewards(txns, capped_card, h).total == aed(110)


class TestMinimumSpend:
    """Spec §F13 and §14 example 5 — never assume the user will spend more."""

    def test_minimum_not_met_earns_nothing(self, capped_card):
        h = AnalysisHorizon(start="2026-01-01", months=1)
        txns = [txn("2026-01-10", -4900, category="GROCERIES")]   # min is 5,000
        r = compute_rewards(txns, capped_card, h)
        assert r.total == aed(0)
        assert r.cycles_missing_minimum == 1

    def test_minimum_exactly_met_earns(self, capped_card):
        h = AnalysisHorizon(start="2026-01-01", months=1)
        txns = [txn("2026-01-10", -5000, category="GROCERIES")]
        r = compute_rewards(txns, capped_card, h)
        assert r.total == aed(100)          # 5% = 250, capped at 100
        assert r.cycles_missing_minimum == 0

    def test_minimum_is_evaluated_per_cycle_not_on_the_average(self, capped_card):
        """Averaging 4,000 and 6,000 to 5,000 would wrongly qualify both cycles."""
        h = AnalysisHorizon(start="2026-01-01", months=2)
        txns = [
            txn("2026-01-10", -4000, category="GROCERIES"),   # misses
            txn("2026-02-10", -6000, category="GROCERIES"),   # meets -> capped 100
        ]
        r = compute_rewards(txns, capped_card, h)
        assert r.total == aed(100)
        assert r.cycles_missing_minimum == 1

    def test_minimum_counts_total_spend_not_only_rewarded_categories(self, capped_card):
        h = AnalysisHorizon(start="2026-01-01", months=1)
        txns = [
            txn("2026-01-10", -3000, category="GROCERIES"),
            txn("2026-01-11", -2500, category="DINING"),
        ]
        assert compute_rewards(txns, capped_card, h).cycles_missing_minimum == 0


class TestRounding:
    """D-023: rounding is contractual. Both readings of the noon conflict are covered."""

    def test_half_up_matches_the_statement(self):
        spec = RoundingSpec(mode="HALF_UP", unit="MINOR", scope="CYCLE")
        assert apply_rounding(Money(18285, "AED", 4), spec) == Money(183, "AED", 2) or \
               apply_rounding(aed("1.8285"), spec) == aed("1.83")

    def test_round_down_to_major_unit_matches_the_terms_and_conditions(self):
        """T&C: 'round down the total Cashback earned during a Billing Month to the
        nearest Dirham'. 1.83 -> 1.00. This is the conflicting reading (D-023)."""
        spec = RoundingSpec(mode="DOWN", unit="MAJOR", scope="CYCLE")
        assert apply_rounding(aed("1.83"), spec) == aed(1)

    def test_round_down_never_rounds_up(self):
        spec = RoundingSpec(mode="DOWN", unit="MAJOR", scope="CYCLE")
        assert apply_rounding(aed("99.99"), spec) == aed(99)

    def test_rounding_scope_cycle_differs_from_per_transaction(self):
        """Rounding each of three 0.4 rewards down gives 0; rounding the 1.2 total
        down gives 1. Scope is contractual and must not be assumed."""
        per_txn = RoundingSpec(mode="DOWN", unit="MAJOR", scope="TXN")
        per_cycle = RoundingSpec(mode="DOWN", unit="MAJOR", scope="CYCLE")
        assert apply_rounding(aed("0.40"), per_txn) == aed(0)
        assert apply_rounding(aed("1.20"), per_cycle) == aed(1)
