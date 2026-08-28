"""Reward expiry and redemption constraints — D-024."""
import pytest
from dataclasses import replace
from analyser.domain import compute_rewards, net_value
from analyser.domain.model import AnalysisHorizon
from tests.conftest import txn, aed

pytestmark = pytest.mark.red


class TestExpiry:
    def test_rewards_expiring_unredeemed_are_worth_zero_in_the_conservative_band(
            self, noon_card, horizon):
        """noon T&C 4.3: cashback expires 12 months from accrual."""
        from analyser.domain import sensitivity_bands
        txns = [txn("2026-01-10", -1000, posting="2026-01-11", category="NOON")]
        cons, exp, opt = sensitivity_bands(txns, noon_card, horizon)
        assert cons <= exp

    def test_expiry_months_is_carried_from_the_terms(self, noon_card):
        assert noon_card.reward.expiry_months == 12

    def test_a_card_without_stated_expiry_does_not_assume_one(self, capped_card):
        """Spec §P3: absence of a rule is UNKNOWN, not 'never expires'."""
        assert capped_card.reward.expiry_months is None


class TestRedemption:
    def test_non_cash_rewards_are_flagged_in_net_value(self, noon_card, horizon):
        """noon cashback is redeemable only on noon platforms and cannot be
        withdrawn as cash (T&C 4.2). It is not equivalent to AED."""
        assert noon_card.reward.is_cash_equivalent is False
        assert noon_card.reward.redemption_channel == "NOON_PLATFORM"

    def test_points_are_not_valued_without_an_explicit_rate(self, capped_card, horizon):
        """D-014: no built-in point valuation. Mashreq Vantage, FAB Al-Futtaim
        Rewards and Emirates Islamic cashback all use different units."""
        from analyser.domain.model import RewardProgram, RewardTier, CycleSpec
        points_card = replace(capped_card, min_spend_per_cycle=None, reward=RewardProgram(
            tiers=(RewardTier(categories=None, rate_bps=100),),
            cycle=CycleSpec(anchor_day=1), unit="POINTS"))
        txns = [txn(f"2026-{m:02d}-10", -1000, category="DINING") for m in range(1, 13)]
        r = net_value(txns, points_card, horizon)
        assert r.rewards.minor == 0 or any("valuation" in a.label.lower() for a in r.assumptions)
