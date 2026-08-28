"""Quality gates and the verdict — D-016c, D-016d, D-016e, D-025, spec §15."""
import pytest
from dataclasses import replace
from analyser.domain import quality_gates, recommend
from analyser.domain.model import AnalysisHorizon, Confidence, TxnType
from tests.conftest import txn, aed

pytestmark = pytest.mark.red


class TestQualityGates:
    """D-016d: gates are weighted by VALUE, never by transaction count."""

    def test_uncategorized_over_ten_percent_by_value_fails(self, noon_card):
        txns = [txn("2026-03-10", -9000, posting="2026-03-11", category="NOON"),
                txn("2026-03-11", -1500, posting="2026-03-12", category=None)]
        assert any(g.gate == "UNCATEGORIZED_SPEND" for g in quality_gates(txns, noon_card))

    def test_many_small_unknowns_do_not_fail_the_gate(self, noon_card):
        """40 x AED 20 unknown against AED 9,000 known is 8.2% by value -- passes."""
        txns = [txn("2026-03-10", -9000, posting="2026-03-11", category="NOON")]
        txns += [txn(f"2026-03-1{i%10}", -20, posting="2026-03-12", category=None,
                     tid=f"u{i}") for i in range(40)]
        assert not any(g.gate == "UNCATEGORIZED_SPEND" for g in quality_gates(txns, noon_card))

    def test_one_large_unknown_does_fail_the_gate(self, noon_card):
        """A single AED 5,000 unknown against AED 9,000 known is 35.7% -- fails."""
        txns = [txn("2026-03-10", -9000, posting="2026-03-11", category="NOON"),
                txn("2026-03-11", -5000, posting="2026-03-12", category=None)]
        assert any(g.gate == "UNCATEGORIZED_SPEND" for g in quality_gates(txns, noon_card))

    def test_insufficient_cycle_coverage_fails(self, noon_card):
        txns = [txn("2026-03-10", -1000, posting="2026-03-11", category="NOON")]
        assert any(g.gate == "COVERAGE" for g in quality_gates(txns, noon_card))

    def test_low_confidence_concentration_in_a_rewarded_category_fails(self, noon_card):
        txns = [txn(f"2026-{m:02d}-10", -1000, posting=f"2026-{m:02d}-11", category="NOON",
                    confidence=Confidence.LOW) for m in range(1, 13)]
        assert any(g.gate == "LOW_CONFIDENCE" for g in quality_gates(txns, noon_card))


class TestRecommendation:
    """D-016c: buckets are deterministic. The LLM never selects the verdict."""

    def _year(self, cat="NOON", amount=-2000):
        return [txn(f"2026-{m:02d}-10", amount, posting=f"2026-{m:02d}-11", category=cat)
                for m in range(1, 13)]

    def test_gate_failure_overrides_everything(self, noon_card, horizon):
        r = recommend([txn("2026-03-10", -100000, posting="2026-03-11", category="NOON")],
                      noon_card, horizon)
        assert r.verdict == "INSUFFICIENT_DATA"

    def test_strongly_beneficial_requires_high_confidence(self, capped_card, horizon):
        card = replace(capped_card, min_spend_per_cycle=None)
        txns = [txn(f"2026-{m:02d}-10", -6000, category="GROCERIES") for m in range(1, 13)]
        r = recommend(txns, card, horizon)
        # net 1,200 - 525 = 675 > 2 x 525? no -> BENEFICIAL, not STRONGLY
        assert r.verdict in ("BENEFICIAL", "MARGINALLY_BENEFICIAL")

    def test_negative_value_is_not_beneficial(self, capped_card, horizon):
        card = replace(capped_card, min_spend_per_cycle=None)
        txns = [txn(f"2026-{m:02d}-10", -200, category="GROCERIES") for m in range(1, 13)]
        assert recommend(txns, card, horizon).verdict == "NOT_BENEFICIAL"

    def test_confidence_caps_but_never_raises_the_verdict(self, capped_card, horizon):
        card = replace(capped_card, min_spend_per_cycle=None)
        txns = [txn(f"2026-{m:02d}-10", -6000, category="GROCERIES",
                    confidence=Confidence.MEDIUM) for m in range(1, 13)]
        assert recommend(txns, card, horizon).verdict != "STRONGLY_BENEFICIAL"

    def test_revolving_balance_caps_the_verdict(self, capped_card, horizon):
        """D-016e: at 46% APR, interest dwarfs any cashback."""
        card = replace(capped_card, min_spend_per_cycle=None)
        txns = [txn(f"2026-{m:02d}-10", -6000, category="GROCERIES") for m in range(1, 13)]
        txns += [txn("2026-06-28", -800, ttype=TxnType.INTEREST, tid="int1")]
        r = recommend(txns, card, horizon)
        assert r.verdict in ("MARGINALLY_BENEFICIAL", "NEUTRAL", "NOT_BENEFICIAL",
                             "INSUFFICIENT_DATA")
        assert any("REVOLVING" in w.upper() for w in r.warnings)

    def test_unknowable_exclusion_caps_confidence_at_medium(self, noon_card, horizon):
        """D-025: 'any other transactions determined by the Bank from time to time'."""
        txns = self._year()
        r = recommend(txns, noon_card, horizon)
        assert r.confidence in (Confidence.MEDIUM, Confidence.LOW, Confidence.UNKNOWN)

    def test_recommendation_carries_the_routing_plan(self, noon_card, horizon):
        """D-027: the plan is the primary output, not an afterthought."""
        r = recommend(self._year(), noon_card, horizon)
        assert r.plan is not None

    def test_assumptions_are_always_disclosed(self, noon_card, horizon):
        assert len(recommend(self._year(), noon_card, horizon).assumptions) > 0
