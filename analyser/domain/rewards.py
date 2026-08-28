"""Eligible spend, rounding, reward computation.
D-016a, D-023, D-024, D-025. Tests: tests/rewards/*"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

from .cycles import cycles_for
from .model import Money, RewardLine, RewardResult, TxnType

_BPS = Decimal(10000)


# --- exclusions (D-025) -------------------------------------------------------

def _exclusion_applies(exclusion, txn):
    """True when every criterion the exclusion *states* matches this transaction.

    An exclusion with no stated criterion (the noon "any other transactions
    determined by the Bank" clause) is UNKNOWABLE and can never be evaluated,
    so it excludes nothing. A channel criterion narrows the rule: it applies
    ONLY when the transaction's channel is known and matches (D-025) -- an
    unknown channel is treated as eligible.
    """
    criteria = (exclusion.txn_types, exclusion.categories, exclusion.channels)
    if not any(criteria):
        return False
    if exclusion.txn_types and txn.txn_type not in exclusion.txn_types:
        return False
    if exclusion.categories and txn.category not in exclusion.categories:
        return False
    if exclusion.channels and txn.channel not in exclusion.channels:
        return False
    return True


def is_excluded(txn, card):
    return any(_exclusion_applies(e, txn) for e in card.reward.exclusions)


def _nets_spend(txn):
    """Credits that cancel a charge (refunds, reversals).

    An exclusion can stop such a credit from *earning*, but it can never make
    the charge it reverses earn: the netting is applied regardless (D-016a).
    """
    return txn.txn_type in (TxnType.REFUND, TxnType.REVERSAL)


# --- helpers ------------------------------------------------------------------

def _currency(card, txns):
    for t in txns:
        return t.amount.currency, t.amount.exponent
    return card.annual_fee.currency, card.annual_fee.exponent


def _key_date(txn, spec):
    if spec.key == "POSTING":
        return txn.posting_date or txn.txn_date
    return txn.txn_date


def _in_cycle(txn, spec, cycle):
    d = _key_date(txn, spec)
    return cycle.start <= d <= cycle.end


def _spend_minor(txn):
    """Signed contribution to eligible spend, in minor units.

    Spend is money out (negative on the statement) and counts positively;
    refunds are money in and net it down (D-016a). PAYMENT is never spend
    -- a payment settles the balance, it does not undo a purchase.
    """
    if txn.txn_type == TxnType.PAYMENT:
        return 0
    if txn.txn_type in (TxnType.REFUND, TxnType.REVERSAL):
        # A reversal undoes the charge it mirrors, so it nets the spend down
        # exactly like a refund (the FAB CAREEM PLUS debit/credit pair).
        return -abs(txn.amount.minor)
    if txn.txn_type in TxnType.SPEND:
        return abs(txn.amount.minor)
    return 0


# --- public API ---------------------------------------------------------------

def eligible_spend(txns, card, cycle):
    """Spend assigned to `cycle`, net of refunds POSTING in it (D-016a).

    Floors at zero -- never negative -- and any excess refund is dropped rather
    than carried into the next cycle.
    """
    spec = card.reward.cycle
    currency, exponent = _currency(card, txns)
    total = 0
    for t in txns:
        if not _in_cycle(t, spec, cycle):
            continue
        if is_excluded(t, card) and not _nets_spend(t):
            continue
        total += _spend_minor(t)
    return Money(max(total, 0), currency, exponent)


def apply_rounding(amount, spec):
    """Round a Money reward per the card's contractual rounding rule (D-023).

    mode: HALF_UP | DOWN | UP.
    unit: MINOR (nearest minor unit, e.g. nearest fils) | MAJOR (nearest whole
    currency unit, e.g. AED 1.83 -> AED 1.00 when rounding DOWN).

    An exponent finer than the currency's own minor unit carries sub-minor
    working precision (1.8285 held as Money(18285, "AED", 4)); rounding
    collapses it back onto the minor unit.

    Decimal only -- float would reintroduce the bankers'-rounding bug the
    statement disproves (36.57 x 5% = 1.8285 -> 1.83, not 1.82).
    """
    rounding = {
        "HALF_UP": ROUND_HALF_UP,
        "DOWN": ROUND_FLOOR,
        "UP": ROUND_CEILING,
    }[spec.mode]
    target = 2 if amount.exponent > 2 else amount.exponent
    major = Decimal(amount.minor).scaleb(-amount.exponent)
    step = Decimal(1) if spec.unit == "MAJOR" else Decimal(1).scaleb(-target)
    rounded = major.quantize(step, rounding=rounding)
    return Money(int(rounded.scaleb(target).to_integral_value()), amount.currency, target)


def _round_scope(minor, currency, exponent, rounding_spec):
    """Round a possibly fractional minor-unit Decimal, keeping sub-minor precision
    until the contractual rule is applied."""
    sub = (minor * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return apply_rounding(Money(int(sub), currency, exponent + 2), rounding_spec)


def _tier_active(tier, on_date):
    if tier.valid_from and on_date < tier.valid_from:
        return False
    if tier.valid_to and on_date > tier.valid_to:
        return False
    return True


def _match_tier(tiers, txn, on_date):
    """Lowest priority number wins; `categories=None` is the catch-all.

    Ties keep declaration order, so a promotional tier declared ahead of the
    base tier at the same priority takes precedence while it is valid.
    """
    candidates = [
        (i, t) for i, t in enumerate(tiers)
        if _tier_active(t, on_date)
        and (t.categories is None or txn.category in t.categories)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda it: (it[1].priority, it[0]))[1]


def compute_rewards(txns, card, horizon):
    """Per-cycle reward accrual: minimum spend, tier allocation, caps, rounding."""
    program = card.reward
    spec = program.cycle
    rounding = program.rounding
    currency, exponent = _currency(card, txns)
    zero = Money(0, currency, exponent)

    cycles = cycles_for(spec, horizon)
    lines = []
    excluded_minor = 0
    missing_minimum = 0
    total_minor = Decimal(0)

    for cycle in cycles:
        in_cycle = [t for t in txns if _in_cycle(t, spec, cycle)]
        if not in_cycle:
            continue

        eligible, excluded = [], []
        for t in in_cycle:
            drop = is_excluded(t, card) and not _nets_spend(t)
            (excluded if drop else eligible).append(t)
        excluded_minor += sum(abs(t.amount.minor) for t in excluded
                              if t.txn_type in TxnType.SPEND)

        # D-016c/§F13: the minimum is tested against TOTAL spend in the cycle,
        # not only the spend that happens to sit in a rewarded category.
        cycle_spend = max(sum(_spend_minor(t) for t in eligible), 0)
        if card.min_spend_per_cycle is not None and cycle_spend < card.min_spend_per_cycle.minor:
            missing_minimum += 1
            lines.append(RewardLine(
                cycle=cycle.label, category=None,
                eligible_spend=Money(cycle_spend, currency, exponent),
                rate_bps=0, gross_reward=zero, capped_reward=zero,
                cap_applied=False, min_spend_met=False,
            ))
            continue

        # Allocate every transaction to exactly one tier, netting refunds
        # against the tier they belong to.
        buckets = {}
        for t in eligible:
            contribution = _spend_minor(t)
            if contribution == 0:
                continue
            tier = _match_tier(program.tiers, t, _key_date(t, spec))
            if tier is None:
                continue
            buckets.setdefault(id(tier), (tier, []))[1].append(contribution)

        cycle_reward = Decimal(0)
        for tier, contributions in buckets.values():
            spend_minor = max(sum(contributions), 0)   # a tier never earns on net refunds
            rate = Decimal(tier.rate_bps) / _BPS
            if rounding.scope == "TXN":
                gross = sum((_round_scope(Decimal(c) * rate, currency, exponent,
                                          rounding).minor for c in contributions),
                            Decimal(0))
                gross = max(Decimal(gross), Decimal(0))
            else:
                gross = Decimal(spend_minor) * rate
            capped, cap_applied = gross, False
            if tier.cap_per_cycle is not None and gross > tier.cap_per_cycle.minor:
                # Caps are per tier per cycle and never carry over (§F12).
                capped, cap_applied = Decimal(tier.cap_per_cycle.minor), True
            if rounding.scope == "CATEGORY":
                capped = Decimal(_round_scope(capped, currency, exponent, rounding).minor)
            cycle_reward += capped
            lines.append(RewardLine(
                cycle=cycle.label,
                category=None if tier.categories is None else ",".join(sorted(tier.categories)),
                eligible_spend=Money(spend_minor, currency, exponent),
                rate_bps=tier.rate_bps,
                gross_reward=Money(int(gross.to_integral_value(ROUND_HALF_UP)), currency, exponent),
                capped_reward=Money(int(capped.to_integral_value(ROUND_HALF_UP)), currency, exponent),
                cap_applied=cap_applied,
                min_spend_met=True,
            ))

        if rounding.scope == "CYCLE":
            cycle_reward = Decimal(_round_scope(cycle_reward, currency, exponent, rounding).minor)
        total_minor += cycle_reward

    total = Money(int(total_minor.to_integral_value(ROUND_HALF_UP)), currency, exponent)
    return RewardResult(
        total=total,
        lines=lines,
        excluded_spend=Money(excluded_minor, currency, exponent),
        cycles_missing_minimum=missing_minimum,
    )
