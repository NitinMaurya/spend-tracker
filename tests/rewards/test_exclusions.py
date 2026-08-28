"""Exclusions and detectability — D-025, spec §F8, §14 example 3."""
import pytest
from analyser.domain import compute_rewards, eligible_spend, cycles_for
from analyser.domain.model import AnalysisHorizon, TxnType, Detectability
from tests.conftest import txn, aed

pytestmark = pytest.mark.red


class TestContractualExclusions:
    """Every exclusion below is quoted verbatim from the real noon T&C."""

    @pytest.mark.parametrize("ttype", [
        TxnType.CASH_ADVANCE, TxnType.FEE, TxnType.INTEREST, TxnType.REVERSAL,
    ])
    def test_excluded_transaction_types_earn_nothing(self, noon_card, ttype):
        h = AnalysisHorizon(start="2026-07-06", months=1)
        txns = [txn("2026-07-10", -1000, posting="2026-07-11",
                    category="NOON", ttype=ttype)]
        assert compute_rewards(txns, noon_card, h).total == aed(0)

    def test_channel_dependent_exclusion_applies_only_when_channel_is_known(self, noon_card):
        """D-025: DEWA paid by card at DEWA earns 0.33%; the same amount paid via
        Mashreq online banking earns nothing. The statement line looks identical."""
        h = AnalysisHorizon(start="2026-07-06", months=1)
        at_merchant = [txn("2026-07-10", -1000, posting="2026-07-11",
                           category="UTILITIES", channel="MERCHANT")]
        via_bank = [txn("2026-07-10", -1000, posting="2026-07-11",
                        category="UTILITIES", channel="BANK_CHANNEL")]
        assert compute_rewards(at_merchant, noon_card, h).total == aed("3.30")
        assert compute_rewards(via_bank, noon_card, h).total == aed(0)

    def test_unknown_channel_is_treated_as_eligible_but_flagged(self, noon_card):
        """Channel is usually unknown from a statement. The expected band assumes
        eligible; the conservative band (D-010) assumes not."""
        h = AnalysisHorizon(start="2026-07-06", months=1)
        txns = [txn("2026-07-10", -1000, posting="2026-07-11", category="UTILITIES")]
        assert compute_rewards(txns, noon_card, h).total == aed("3.30")

    def test_excluded_spend_is_reported_not_silently_dropped(self, noon_card):
        h = AnalysisHorizon(start="2026-07-06", months=1)
        txns = [
            txn("2026-07-10", -1000, posting="2026-07-11", category="NOON"),
            txn("2026-07-11", -500, posting="2026-07-12", category="NOON",
                ttype=TxnType.CASH_ADVANCE),
        ]
        r = compute_rewards(txns, noon_card, h)
        assert r.excluded_spend == aed(500)


class TestPromotionalPeriods:
    """Spec §14 example 3 — a benefit must not be applied past its expiry."""

    def test_expired_tier_does_not_apply(self, capped_card):
        from dataclasses import replace
        from analyser.domain.model import RewardTier, RewardProgram
        promo = RewardTier(categories=frozenset({"GROCERIES"}), rate_bps=1000,
                           valid_from="2026-01-01", valid_to="2026-06-30", priority=0)
        card = replace(capped_card, min_spend_per_cycle=None,
                       reward=replace(capped_card.reward, tiers=(promo,) + capped_card.reward.tiers))
        h = AnalysisHorizon(start="2026-07-01", months=1)
        txns = [txn("2026-07-10", -1000, category="GROCERIES")]
        # 10% promo expired; falls back to the 5% tier, capped at 100 -> 50
        assert compute_rewards(txns, card, h).total == aed(50)

    def test_active_promo_takes_precedence(self, capped_card):
        from dataclasses import replace
        from analyser.domain.model import RewardTier
        promo = RewardTier(categories=frozenset({"GROCERIES"}), rate_bps=1000,
                           valid_from="2026-01-01", valid_to="2026-12-31", priority=0)
        card = replace(capped_card, min_spend_per_cycle=None,
                       reward=replace(capped_card.reward, tiers=(promo,) + capped_card.reward.tiers))
        h = AnalysisHorizon(start="2026-03-01", months=1)
        txns = [txn("2026-03-10", -500, category="GROCERIES")]
        assert compute_rewards(txns, card, h).total == aed(50)   # 10% of 500
