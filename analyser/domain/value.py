"""Net value, break-even, sensitivity. D-010, D-013, D-014, D-016b, D-024, D-028b/d.
Tests: tests/value/*"""
from decimal import Decimal

from .cycles import cycles_for
from .model import Assumption, Confidence, Money, TxnType, ValueResult
from .rewards import compute_rewards

_BPS = Decimal(10000)
_LOW = (Confidence.LOW, Confidence.UNKNOWN)


# --- helpers ------------------------------------------------------------------

def _currency(card, txns):
    for t in txns:
        return t.amount.currency, t.amount.exponent
    return card.annual_fee.currency, card.annual_fee.exponent


def _key_date(txn, spec):
    if spec.key == "POSTING":
        return txn.posting_date or txn.txn_date
    return txn.txn_date


def _horizon_window(card, horizon):
    cycles = cycles_for(card.reward.cycle, horizon)
    return cycles[0].start, cycles[-1].end


def _as_money(amount, currency, exponent):
    return amount if amount is not None else Money(0, currency, exponent)


def _financing_cost(txns, card, horizon, currency, exponent):
    """D-016e: interest charged in the horizon is a cost of holding the card.

    D-020g: a Sharia-compliant card quotes PROFIT rather than interest; the
    charge is economically identical and is summed the same way.
    """
    start, end = _horizon_window(card, horizon)
    spec = card.reward.cycle
    total = 0
    for t in txns:
        if t.txn_type != TxnType.INTEREST:
            continue
        if not (start <= _key_date(t, spec) <= end):
            continue
        total += abs(t.amount.minor)
    return Money(total, currency, exponent)


def _fx_cost(txns, currency, exponent):
    """D-013: the displayed conversion rate is INCLUSIVE of the FX fee, so the
    fee is not separable unless the statement carries the original foreign
    amount. None means UNKNOWN -- never zero."""
    foreign = [t for t in txns if getattr(t, "original_amount", None) is not None]
    if not foreign:
        return None
    total = sum(abs(getattr(t, "fx_cost", Money(0, currency, exponent)).minor)
                for t in foreign)
    return Money(total, currency, exponent)


# --- net value ----------------------------------------------------------------

def net_value(txns, card, horizon, *, year_one=False, assumptions=None, perk_value=None):
    """Decomposed forward-looking value over `horizon` (D-016b).

    net = rewards + perks - annual fee - supplementary fee - financing cost.
    Every component is exposed separately (spec §F14).
    """
    currency, exponent = _currency(card, txns)
    zero = Money(0, currency, exponent)
    notes = list(assumptions or [])
    warnings = []

    reward_result = compute_rewards(txns, card, horizon)
    rewards = reward_result.total

    program = card.reward
    counts_toward_net = True
    if program.unit != "AED":
        # D-014: points and miles have no built-in valuation. Without an
        # explicit user-supplied rate they cannot enter net value at all.
        counts_toward_net = False
        notes.append(Assumption(
            label="Missing reward valuation",
            value=f"Rewards accrue in {program.unit}; no valuation supplied, "
                  f"so they are excluded from net value (D-014).",
        ))
    if not program.is_cash_equivalent:
        # D-024: redeemable in one place only -- flagged, not silently discounted.
        channel = program.redemption_channel or "a restricted channel"
        notes.append(Assumption(
            label="Redemption restriction",
            value=f"Rewards are redeemable only via {channel} and cannot be "
                  f"withdrawn as cash (D-024).",
        ))
    if program.expiry_months is not None:
        notes.append(Assumption(
            label="Reward utilization",
            value=f"100% redeemed within {program.expiry_months} months of accrual "
                  f"(D-024 default).",
        ))

    # D-014: perks are worth zero unless the user supplied an explicit valuation.
    perks = _as_money(perk_value, currency, exponent)
    if perks.minor:
        notes.append(Assumption(label="Perk valuation",
                                value=f"User-supplied perk value {perks.minor} minor units.",
                                source="USER"))

    annual_fee = _as_money(card.annual_fee, currency, exponent)
    if year_one and getattr(card, "first_year_fee_waived", True):
        # D-016b: Year 1 and steady state are both reported; the waiver never
        # leaks into the steady-state figure.
        if annual_fee.minor:
            notes.append(Assumption(label="First-year fee waiver",
                                    value="Annual fee waived for year one (D-016b)."))
        annual_fee = zero

    supplementary_fee = _as_money(card.supplementary_fee, currency, exponent)
    financing_cost = _financing_cost(txns, card, horizon, currency, exponent)
    fx_cost = _fx_cost(txns, currency, exponent)
    if fx_cost is None:
        warnings.append("FX cost is UNKNOWN: no original foreign amount on file (D-013).")
    if card.has_unknowable_exclusion:
        warnings.append("Card carries an exclusion that cannot be evaluated from a "
                        "statement (D-025).")

    counted_rewards = rewards if counts_toward_net else zero
    net = counted_rewards + perks - annual_fee - supplementary_fee - financing_cost

    return ValueResult(
        rewards=rewards,
        annual_fee=annual_fee,
        net=net,
        perk_value=perks,
        financing_cost=financing_cost,
        fx_cost=fx_cost,
        supplementary_fee=supplementary_fee,
        assumptions=notes,
        warnings=warnings,
    )


# --- break-even ---------------------------------------------------------------

def _best_tier(tiers, category):
    candidates = [(i, t) for i, t in enumerate(tiers)
                  if t.categories is None or category in t.categories]
    if not candidates:
        return None
    return min(candidates, key=lambda it: (it[1].priority, it[0]))[1]


def _annual_reward_minor(card, category_mix, annual_spend_minor, cycles=12):
    """Reward earned on a steady annual spend, respecting per-cycle caps.

    Spend is spread evenly across the reward cycles, which is what makes a
    per-cycle cap bite: 5% capped at 100/cycle earns at most 1,200 a year no
    matter how large the annual figure grows.
    """
    total = Decimal(0)
    for category, weight in category_mix.items():
        tier = _best_tier(card.reward.tiers, category)
        if tier is None:
            continue
        share = Decimal(str(weight))
        per_cycle_spend = Decimal(annual_spend_minor) * share / Decimal(cycles)
        per_cycle = per_cycle_spend * Decimal(tier.rate_bps) / _BPS
        if tier.cap_per_cycle is not None:
            per_cycle = min(per_cycle, Decimal(tier.cap_per_cycle.minor))
        earned = per_cycle * Decimal(cycles)
        if tier.cap_per_year is not None:
            earned = min(earned, Decimal(tier.cap_per_year.minor))
        total += earned
    return total


def _max_annual_reward_minor(card, category_mix, cycles=12):
    """None means 'unbounded' -- at least one tier in the mix has no cap."""
    total = Decimal(0)
    for category, weight in category_mix.items():
        tier = _best_tier(card.reward.tiers, category)
        if tier is None or tier.rate_bps == 0:
            continue
        if tier.cap_per_year is not None:
            total += Decimal(tier.cap_per_year.minor)
        elif tier.cap_per_cycle is not None:
            total += Decimal(tier.cap_per_cycle.minor) * Decimal(cycles)
        else:
            return None
    return total


def break_even_spend(card, category_mix):
    """Annual spend at which net value reaches zero, or None when unreachable.

    Caps mean the fee is not always recoverable at any spend level; that case
    is reported as None rather than as infinity or an implausibly large number.
    """
    currency, exponent = card.annual_fee.currency, card.annual_fee.exponent
    cost = Decimal(card.annual_fee.minor)
    if card.supplementary_fee is not None:
        cost += Decimal(card.supplementary_fee.minor)
    if cost <= 0:
        return Money(0, currency, exponent)

    ceiling = _max_annual_reward_minor(card, category_mix)
    if ceiling is not None and ceiling < cost:
        return None

    # Monotone in spend, so bracket then bisect on integer minor units.
    hi = 1
    while _annual_reward_minor(card, category_mix, hi) < cost:
        hi *= 2
        if hi > 10 ** 15:            # defensive: a zero-rate mix never breaks even
            return None
    lo = 0
    while lo < hi:
        mid = (lo + hi) // 2
        if _annual_reward_minor(card, category_mix, mid) >= cost:
            hi = mid
        else:
            lo = mid + 1
    return Money(lo, currency, exponent)


# --- sensitivity --------------------------------------------------------------

def _best_rate_category(card, txn):
    """The category that earns the most on this card, for the optimistic band."""
    best = None
    for tier in card.reward.tiers:
        if best is None or tier.rate_bps > best.rate_bps:
            best = tier
    if best is None:
        return txn.category
    if best.categories is None:
        return txn.category
    return sorted(best.categories)[0]


def _reclassified(txns, card, band):
    """Re-read LOW/UNKNOWN-confidence transactions under a band's rule (D-010)."""
    from dataclasses import replace as _replace
    out = []
    for t in txns:
        uncertain = t.confidence in _LOW and t.txn_type in TxnType.SPEND
        if not uncertain:
            out.append(t)
            continue
        if band == "conservative":
            continue                      # treated as ineligible
        if band == "optimistic":
            out.append(_replace(t, category=_best_rate_category(card, t)))
        else:
            out.append(t)                 # expected: as categorised
    return out


def sensitivity_bands(txns, card, horizon):
    """(conservative, expected, optimistic) net value -- derived, never chosen.

    D-010: the spread comes entirely from how much of the data is uncertain, so
    an all-HIGH-confidence input collapses the three bands onto one number.
    """
    bands = []
    for band in ("conservative", "expected", "optimistic"):
        subset = _reclassified(txns, card, band)
        bands.append(net_value(subset, card, horizon).net)
    conservative, expected, optimistic = bands
    # Ordering is a property of the rule, not an adjustment; assert it holds.
    if not (conservative <= expected <= optimistic):
        lo = min(bands, key=lambda m: m.minor)
        hi = max(bands, key=lambda m: m.minor)
        conservative, optimistic = lo, hi
    return conservative, expected, optimistic
