"""Reward cycles and refund netting — D-012, D-016a, D-020i."""
import pytest
from analyser.domain import cycles_for, assign_cycle, eligible_spend
from analyser.domain.model import CycleSpec, AnalysisHorizon, TxnType
from tests.conftest import txn, aed

pytestmark = pytest.mark.red


class TestCycleBoundaries:
    def test_anchored_cycle_is_not_a_calendar_month(self, horizon):
        """Mashreq noon: qualifying transactions posted 6th prev -> 5th current."""
        cycles = cycles_for(CycleSpec(anchor_day=6, key="POSTING"), horizon)
        first = cycles[0]
        assert first.start.endswith("-06")
        assert first.end.endswith("-05")

    def test_twelve_month_horizon_yields_twelve_cycles(self, horizon):
        assert len(cycles_for(CycleSpec(anchor_day=6), horizon)) == 12

    def test_cycle_assignment_uses_posting_not_transaction_date(self, horizon):
        """D-012: a purchase on the 4th posting on the 7th belongs to the LATER cycle."""
        cycles = cycles_for(CycleSpec(anchor_day=6, key="POSTING"), horizon)
        t = txn("2026-03-04", -100, posting="2026-03-07", category="NOON")
        assigned = assign_cycle(t, CycleSpec(anchor_day=6, key="POSTING"), cycles)
        assert assigned.start == "2026-03-06"

    def test_transaction_keyed_cycle_differs_from_posting_keyed(self, horizon):
        spec_p = CycleSpec(anchor_day=6, key="POSTING")
        spec_t = CycleSpec(anchor_day=6, key="TRANSACTION")
        cycles_p = cycles_for(spec_p, horizon)
        cycles_t = cycles_for(spec_t, horizon)
        t = txn("2026-03-04", -100, posting="2026-03-07", category="NOON")
        assert assign_cycle(t, spec_p, cycles_p).start != assign_cycle(t, spec_t, cycles_t).start

    def test_anchor_day_31_does_not_break_short_months(self, horizon):
        cycles = cycles_for(CycleSpec(anchor_day=31), horizon)
        assert len(cycles) == 12
        assert all(c.start < c.end for c in cycles)


class TestRefundNetting:
    """D-016a: refunds reduce the cycle they POST in. No retroactive clawback."""

    def test_refund_reduces_eligible_spend_in_its_posting_cycle(self, noon_card, horizon):
        cycles = cycles_for(noon_card.reward.cycle, horizon)
        c = cycles[2]
        txns = [
            txn("2026-03-10", -500, posting="2026-03-11", category="NOON"),
            txn("2026-03-12", 200, posting="2026-03-13", category="NOON", ttype=TxnType.REFUND),
        ]
        assert eligible_spend(txns, noon_card, c) == aed(300)

    def test_refund_posting_into_next_cycle_does_not_touch_the_earlier_one(self, noon_card, horizon):
        cycles = cycles_for(noon_card.reward.cycle, horizon)
        earlier, later = cycles[2], cycles[3]
        txns = [
            txn("2026-03-10", -500, posting="2026-03-11", category="NOON"),
            txn("2026-03-30", 200, posting="2026-04-08", category="NOON", ttype=TxnType.REFUND),
        ]
        assert eligible_spend(txns, noon_card, earlier) == aed(500)
        assert eligible_spend(txns, noon_card, later) == aed(-200) or \
               eligible_spend(txns, noon_card, later) == aed(0)

    def test_eligible_spend_floors_at_zero_never_negative(self, noon_card, horizon):
        cycles = cycles_for(noon_card.reward.cycle, horizon)
        c = cycles[2]
        txns = [
            txn("2026-03-10", -100, posting="2026-03-11", category="NOON"),
            txn("2026-03-12", 500, posting="2026-03-13", category="NOON", ttype=TxnType.REFUND),
        ]
        assert eligible_spend(txns, noon_card, c) == aed(0)

    def test_excess_refund_does_not_carry_into_next_cycle(self, noon_card, horizon):
        cycles = cycles_for(noon_card.reward.cycle, horizon)
        txns = [
            txn("2026-03-10", -100, posting="2026-03-11", category="NOON"),
            txn("2026-03-12", 500, posting="2026-03-13", category="NOON", ttype=TxnType.REFUND),
            txn("2026-04-10", -300, posting="2026-04-11", category="NOON"),
        ]
        assert eligible_spend(txns, noon_card, cycles[3]) == aed(300)

    def test_payment_is_never_spend(self, noon_card, horizon):
        """Spec §Feature 2 guardrail: FAB's 'PAYMENT RECEIVED' must not net spend."""
        cycles = cycles_for(noon_card.reward.cycle, horizon)
        txns = [
            txn("2026-03-10", -500, posting="2026-03-11", category="NOON"),
            txn("2026-03-12", 564, posting="2026-03-13", ttype=TxnType.PAYMENT),
        ]
        assert eligible_spend(txns, noon_card, cycles[2]) == aed(500)
