"""Reward cycle enumeration and assignment. D-012, D-020i. Tests: tests/rewards/test_cycles_and_netting.py"""
from calendar import monthrange
from datetime import date, timedelta

from .model import Cycle


def _parse(iso):
    y, m, d = (int(p) for p in iso.split("-"))
    return date(y, m, d)


def _add_months(d, n):
    """Shift a (year, month) pair by n months. Day is handled by the caller."""
    total = (d.year * 12 + (d.month - 1)) + n
    return total // 12, total % 12 + 1


def _anchor(year, month, anchor_day):
    """The anchor date in a given month, clamped to the last valid day (D-020i:
    a day-of-month anchor must survive February and the 30-day months)."""
    last = monthrange(year, month)[1]
    return date(year, month, min(anchor_day, last))


def cycles_for(spec, horizon):
    """Enumerate exactly horizon.months cycles for a card's reward calendar.

    A cycle runs from the anchor day of one month to the day before the anchor
    day of the next (anchor_day=6 -> 6th .. 5th), never a calendar month (D-012).
    """
    start_ref = _parse(horizon.start)
    cycles = []
    for i in range(horizon.months):
        y, m = _add_months(start_ref, i)
        start = _anchor(y, m, spec.anchor_day)
        ny, nm = _add_months(start_ref, i + 1)
        end = _anchor(ny, nm, spec.anchor_day) - timedelta(days=1)
        s, e = start.isoformat(), end.isoformat()
        cycles.append(Cycle(start=s, end=e, label=f"{s}..{e}"))
    return cycles


def _key_date(txn, spec):
    """D-012: reward cycles key on the POSTING date unless the card says otherwise."""
    if spec.key == "POSTING":
        return txn.posting_date or txn.txn_date
    return txn.txn_date


def assign_cycle(txn, spec, cycles):
    """Return the cycle a transaction falls in, or None if outside the horizon."""
    d = _key_date(txn, spec)
    for cycle in cycles:
        if cycle.start <= d <= cycle.end:   # ISO-8601 sorts chronologically
            return cycle
    return None
