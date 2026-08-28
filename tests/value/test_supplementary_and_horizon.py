"""Supplementary cards and the analysis horizon — D-028d, D-016b."""
import pytest
from dataclasses import replace
from analyser.domain import compute_rewards, net_value
from analyser.domain.model import AnalysisHorizon
from tests.conftest import txn, aed

pytestmark = pytest.mark.red


class TestSupplementary:
    def test_supplementary_spend_accrues_to_the_primary(self, noon_card):
        """noon T&C 2.2: 'Cashback earned by a supplementary Cardholder(s) will
        accrue to the account of the primary Cardholder.'"""
        h = AnalysisHorizon(start="2026-07-06", months=1)
        txns = [
            txn("2026-07-10", -1000, posting="2026-07-11", category="NOON", account="noon-primary"),
            txn("2026-07-11", -1000, posting="2026-07-12", category="NOON", account="noon-supp"),
        ]
        assert compute_rewards(txns, noon_card, h).total == aed(100)

    def test_supplementary_fee_is_a_separate_cost_line(self, capped_card, horizon):
        card = replace(capped_card, min_spend_per_cycle=None, supplementary_fee=aed(150))
        txns = [txn(f"2026-{m:02d}-10", -1000, category="GROCERIES") for m in range(1, 13)]
        assert net_value(txns, card, horizon).supplementary_fee == aed(150)


class TestHorizon:
    """D-016b: value is computed FORWARD, over an explicit window."""

    def test_horizon_length_is_respected(self, capped_card):
        card = replace(capped_card, min_spend_per_cycle=None)
        txns = [txn(f"2026-{m:02d}-10", -1000, category="GROCERIES") for m in range(1, 13)]
        six = compute_rewards(txns, card, AnalysisHorizon("2026-01-01", 6))
        twelve = compute_rewards(txns, card, AnalysisHorizon("2026-01-01", 12))
        assert six.total < twelve.total

    def test_promotional_rate_is_time_weighted_across_the_horizon(self, capped_card):
        """A promo valid for 6 of 12 months contributes half a year, not a full one."""
        from analyser.domain.model import RewardTier
        promo = RewardTier(categories=frozenset({"GROCERIES"}), rate_bps=1000,
                           valid_from="2026-01-01", valid_to="2026-06-30", priority=0)
        card = replace(capped_card, min_spend_per_cycle=None,
                       reward=replace(capped_card.reward,
                                      tiers=(promo,) + capped_card.reward.tiers))
        txns = [txn(f"2026-{m:02d}-10", -1000, category="GROCERIES") for m in range(1, 13)]
        r = compute_rewards(txns, card, AnalysisHorizon("2026-01-01", 12))
        assert r.total == aed(900)   # 6 months at 10% (100) + 6 at 5% (50)

    def test_year_one_fee_waiver_does_not_leak_into_steady_state(self, capped_card, horizon):
        card = replace(capped_card, min_spend_per_cycle=None)
        txns = [txn(f"2026-{m:02d}-10", -6000, category="GROCERIES") for m in range(1, 13)]
        assert net_value(txns, card, horizon, year_one=False).annual_fee == aed(525)
