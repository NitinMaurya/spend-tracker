"""Spend routing — the primary output (D-027)."""
import pytest
from dataclasses import replace
from analyser.domain import route
from analyser.domain.model import (
    AnalysisHorizon, Routability, RewardTier, RewardProgram, CycleSpec, Card,
)
from tests.conftest import txn, aed

pytestmark = pytest.mark.red


@pytest.fixture
def incumbent():
    """Flat 1% on everything, AED 0 fee."""
    return Card(card_id="incumbent", issuer="TEST", annual_fee=aed(0),
                reward=RewardProgram(tiers=(RewardTier(categories=None, rate_bps=100),),
                                     cycle=CycleSpec(anchor_day=1)))


class TestRoutingPlan:
    def test_moves_only_categories_where_the_candidate_pays_more(self, incumbent, noon_card, horizon):
        txns = [
            txn(f"2026-{m:02d}-10", -1000, posting=f"2026-{m:02d}-11",
                category="NOON", account="incumbent") for m in range(1, 13)
        ] + [
            txn(f"2026-{m:02d}-12", -1000, posting=f"2026-{m:02d}-13",
                category="UTILITIES", account="incumbent") for m in range(1, 13)
        ]
        plan = route(txns, [incumbent, noon_card], horizon)
        moved = {m.category for m in plan.moves}
        assert "NOON" in moved          # 5% beats the incumbent's 1%
        assert "UTILITIES" not in moved # 0.33% is worse than 1% -- must stay

    def test_non_routable_spend_is_never_moved(self, incumbent, noon_card, horizon):
        txns = [txn(f"2026-{m:02d}-10", -1000, posting=f"2026-{m:02d}-11",
                    category="NOON", account="incumbent",
                    routability=Routability.DIRECT_DEBIT) for m in range(1, 13)]
        assert route(txns, [incumbent, noon_card], horizon).moves == []

    def test_reports_both_value_unchanged_and_value_if_routed(self, incumbent, noon_card, horizon):
        """D-027: collapsing these into one number overstates the card."""
        txns = [txn(f"2026-{m:02d}-10", -1000, posting=f"2026-{m:02d}-11",
                    category="NOON", account="incumbent") for m in range(1, 13)]
        plan = route(txns, [incumbent, noon_card], horizon)
        assert plan.value_unchanged is not None
        assert plan.value_if_routed is not None
        assert plan.annual_gain == plan.value_if_routed - plan.value_unchanged

    def test_allocation_is_cap_aware_and_splits_across_cards(self, incumbent, capped_card, horizon):
        """Once the 5%/AED-100 cap fills at 2,000/cycle, the marginal dirham is worth
        1% here but 1% on the incumbent too -- the surplus must not be double-counted."""
        card = replace(capped_card, min_spend_per_cycle=None, annual_fee=aed(0))
        txns = [txn(f"2026-{m:02d}-10", -4000, category="GROCERIES", account="incumbent")
                for m in range(1, 13)]
        plan = route(txns, [incumbent, card], horizon)
        # 2,000 at 5% = 100 (capped) vs 2,000 at 1% = 20 on the incumbent -> gain 80/cycle
        assert plan.annual_gain == aed(960)

    def test_minimum_spend_makes_greedy_allocation_suboptimal(self, incumbent, capped_card, horizon):
        """D-027: a card paying nothing below its threshold is non-convex. Spreading
        spend to chase headline rates can clear NO minimum and earn less than staying."""
        card = replace(capped_card, annual_fee=aed(0))   # min 5,000/cycle
        txns = [txn(f"2026-{m:02d}-10", -3000, category="GROCERIES", account="incumbent")
                for m in range(1, 13)]
        plan = route(txns, [incumbent, card], horizon)
        assert plan.annual_gain >= aed(0)   # never recommend a losing move
        assert plan.moves == []             # 3,000 cannot clear a 5,000 minimum

    def test_never_recommends_increasing_spend(self, incumbent, capped_card, horizon):
        """Guardrail G3: reallocate existing spend, never suggest spending more."""
        card = replace(capped_card, annual_fee=aed(0))
        txns = [txn(f"2026-{m:02d}-10", -4900, category="GROCERIES", account="incumbent")
                for m in range(1, 13)]
        plan = route(txns, [incumbent, card], horizon)
        total_moved = sum(m.monthly_spend.minor for m in plan.moves)
        assert total_moved <= 4900 * 100

    def test_moves_are_ranked_by_value(self, incumbent, noon_card, horizon):
        txns = (
            [txn(f"2026-{m:02d}-10", -2000, posting=f"2026-{m:02d}-11",
                 category="NOON", account="incumbent") for m in range(1, 13)]
            + [txn(f"2026-{m:02d}-12", -100, posting=f"2026-{m:02d}-13",
                   category="DINING", account="incumbent") for m in range(1, 13)]
        )
        plan = route(txns, [incumbent, noon_card], horizon)
        gains = [m.annual_gain.minor for m in plan.moves]
        assert gains == sorted(gains, reverse=True)
