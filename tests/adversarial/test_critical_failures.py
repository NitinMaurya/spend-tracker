"""Spec §14 — the five adversarial cases, verbatim, plus real-data variants.

These are the tests that matter most: each encodes a way the system could produce a
confidently wrong recommendation.
"""
import pytest
from dataclasses import replace
from analyser.domain import compute_rewards, recommend
from analyser.domain.model import AnalysisHorizon, TxnType, RewardTier
from tests.conftest import txn, aed

pytestmark = pytest.mark.red


def test_example_1_capped_cashback_is_not_calculated_as_unlimited(capped_card):
    """§14.1 — KFS: '5% cashback on groceries, maximum AED 100/month'."""
    h = AnalysisHorizon(start="2026-01-01", months=1)
    card = replace(capped_card, min_spend_per_cycle=None)
    txns = [txn("2026-01-10", -4000, category="GROCERIES")]
    assert compute_rewards(txns, card, h).total == aed(100)   # not 200


def test_example_2_uncertain_category_is_not_claimed_as_definitely_eligible(noon_card, horizon):
    """§14.2 — 'AMAZON AED 1,000': category uncertain. Must not assert eligibility."""
    from analyser.domain.model import Confidence
    txns = [txn(f"2026-{m:02d}-10", -1000, posting=f"2026-{m:02d}-11",
                category="SHOPPING", confidence=Confidence.LOW, merchant="AMAZON")
            for m in range(1, 13)]
    r = recommend(txns, noon_card, horizon)
    assert r.confidence != "HIGH"


def test_example_3_expired_offer_is_not_applied_indefinitely(capped_card):
    """§14.3 — KFS: 'Offer valid until December 31, 2026'."""
    promo = RewardTier(categories=frozenset({"GROCERIES"}), rate_bps=1000,
                       valid_from="2026-01-01", valid_to="2026-12-31", priority=0)
    card = replace(capped_card, min_spend_per_cycle=None,
                   reward=replace(capped_card.reward, tiers=(promo,) + capped_card.reward.tiers))
    h = AnalysisHorizon(start="2027-01-01", months=1)
    txns = [txn("2027-01-10", -1000, category="GROCERIES")]
    assert compute_rewards(txns, card, h).total == aed(50)   # 5% fallback, not 10%


def test_example_4_refund_does_not_inflate_spending(noon_card):
    """§14.4 — 'AMAZON +AED 500' must reduce, never increase, spend."""
    h = AnalysisHorizon(start="2026-07-06", months=1)
    txns = [
        txn("2026-07-10", -1000, posting="2026-07-11", category="NOON"),
        txn("2026-07-12", 500, posting="2026-07-13", category="NOON", ttype=TxnType.REFUND),
    ]
    assert compute_rewards(txns, noon_card, h).total == aed(25)   # 5% of 500, not 1,500


def test_example_5_near_miss_minimum_is_not_assumed_met(capped_card):
    """§14.5 — card requires AED 5,000/month; user spends AED 4,900."""
    h = AnalysisHorizon(start="2026-01-01", months=1)
    txns = [txn("2026-01-10", -4900, category="GROCERIES")]
    r = compute_rewards(txns, capped_card, h)
    assert r.total == aed(0)
    assert r.cycles_missing_minimum == 1


# --- variants drawn from the real sample data --------------------------------

def test_fab_charge_and_reversal_pair_nets_to_zero(noon_card):
    """FAB 2026-07-15: two identical CAREEM PLUS AED 1.00 rows, one debit one credit."""
    h = AnalysisHorizon(start="2026-07-06", months=1)
    txns = [
        txn("2026-07-15", -1, posting="2026-07-16", category="TRANSPORTATION", tid="a"),
        txn("2026-07-15", 1, posting="2026-07-16", category="TRANSPORTATION",
            ttype=TxnType.REVERSAL, tid="b"),
    ]
    assert compute_rewards(txns, noon_card, h).total == aed(0)


def test_wio_style_settlement_is_not_counted_as_spend(noon_card):
    """D-007: Wio's 'Blu Fab payment -564.00' is the same money as FAB's
    'PAYMENT RECEIVED 564.00'. Counting both would double-count."""
    h = AnalysisHorizon(start="2026-07-06", months=1)
    txns = [
        txn("2026-07-10", -1000, posting="2026-07-11", category="NOON"),
        txn("2026-07-03", -564, posting="2026-07-04", ttype=TxnType.TRANSFER, tid="t1"),
    ]
    assert compute_rewards(txns, noon_card, h).total == aed(50)


def test_higher_headline_rate_does_not_win_when_capped(capped_card, noon_card, horizon):
    """Guardrail G1 — 5% capped at 100/cycle loses to an uncapped 1% above 2,000/cycle."""
    from analyser.domain import net_value
    card = replace(capped_card, min_spend_per_cycle=None, annual_fee=aed(0))
    txns = [txn(f"2026-{m:02d}-10", -20000, category="GROCERIES") for m in range(1, 13)]
    capped_total = net_value(txns, card, horizon).rewards
    assert capped_total == aed(1200)          # 100 x 12, NOT 5% of 240,000
