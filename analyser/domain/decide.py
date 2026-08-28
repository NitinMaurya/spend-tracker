"""Quality gates and the deterministic verdict. D-016c/d/e, D-025. Tests: tests/decide/*

The verdict is a table lookup, never a judgement call: the engine picks the
bucket, the LLM only ever narrates it (D-008).
"""
from decimal import Decimal

from .model import (
    Assumption, Confidence, GateFailure, Money, Recommendation, TxnType,
)
from .routing import route
from .value import net_value, sensitivity_bands

# D-016d thresholds. Named so they can be flipped without touching the logic.
UNCATEGORIZED_MAX = Decimal("0.10")
LOW_CONFIDENCE_MAX = Decimal("0.25")
MIN_CYCLES = 6

# D-016c buckets, weakest first -- the index is the cap ordering.
NOT_BENEFICIAL = "NOT_BENEFICIAL"
NEUTRAL = "NEUTRAL"
MARGINALLY_BENEFICIAL = "MARGINALLY_BENEFICIAL"
BENEFICIAL = "BENEFICIAL"
STRONGLY_BENEFICIAL = "STRONGLY_BENEFICIAL"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

_RANK = [NOT_BENEFICIAL, NEUTRAL, MARGINALLY_BENEFICIAL, BENEFICIAL,
         STRONGLY_BENEFICIAL]

_UNSURE = (Confidence.LOW, Confidence.UNKNOWN)

# D-016c: a fee-free card still needs a scale to measure value against.
_ZERO_FEE_DIVISOR_MAJOR = 100


# --- helpers ------------------------------------------------------------------

def _key_date(txn, spec):
    if spec.key == "POSTING":
        return txn.posting_date or txn.txn_date
    return txn.txn_date


def _spend_value(txn):
    """Dirham weight of a transaction for gate purposes.

    Gates are weighted by value, not by count (D-016d): one AED 5,000 unknown
    matters more than forty AED 20 unknowns. Only purchase-side spend carries
    weight -- an interest or fee line has no category to get wrong.
    """
    return abs(txn.amount.minor) if txn.txn_type in TxnType.SPEND else 0


def _cycle_index(txn, spec):
    """Ordinal of the reward cycle a transaction posts into.

    A cycle runs anchor-day to anchor-day (D-012), so a posting before the
    anchor belongs to the cycle opened in the previous month.
    """
    iso = _key_date(txn, spec)
    year, month, day = (int(p) for p in iso.split("-"))
    index = year * 12 + (month - 1)
    if day < spec.anchor_day:
        index -= 1
    return index


def _rewarded_categories(card):
    """Categories that actually earn something on this card."""
    named = set()
    for tier in card.reward.tiers:
        if tier.rate_bps <= 0 or tier.categories is None:
            continue
        named |= set(tier.categories)
    return named


def _catch_all_rate(card):
    for tier in card.reward.tiers:
        if tier.categories is None and tier.rate_bps > 0:
            return True
    return False


# --- quality gates (D-016d) ---------------------------------------------------

def quality_gates(txns, card, documents=()):
    """Reasons a recommendation must be withheld. Empty list means pass."""
    failures = []
    spec = card.reward.cycle

    total = sum(_spend_value(t) for t in txns)

    # 1. Uncategorized spend, by value.
    if total > 0:
        unknown = sum(_spend_value(t) for t in txns if not t.category)
        share = Decimal(unknown) / Decimal(total)
        if share > UNCATEGORIZED_MAX:
            failures.append(GateFailure(
                gate="UNCATEGORIZED_SPEND",
                detail=f"{share:.1%} of spend by value is uncategorized "
                       f"(limit {UNCATEGORIZED_MAX:.0%}, D-016d).",
            ))

    # 2. LOW-confidence concentration inside a category that earns a reward.
    rewarded = _rewarded_categories(card)
    catch_all = _catch_all_rate(card)
    by_category = {}
    for t in txns:
        value = _spend_value(t)
        if not value or not t.category:
            continue
        if t.category not in rewarded and not catch_all:
            continue
        seen, unsure = by_category.get(t.category, (0, 0))
        by_category[t.category] = (seen + value,
                                   unsure + (value if t.confidence in _UNSURE else 0))
    for category, (seen, unsure) in sorted(by_category.items()):
        share = Decimal(unsure) / Decimal(seen)
        if share > LOW_CONFIDENCE_MAX:
            failures.append(GateFailure(
                gate="LOW_CONFIDENCE",
                detail=f"{share:.1%} of {category} spend by value is LOW confidence "
                       f"(limit {LOW_CONFIDENCE_MAX:.0%}, D-016d).",
            ))

    # 3. Statement coverage: enough cycles, and no hole in the run.
    indices = sorted({_cycle_index(t, spec) for t in txns
                      if t.txn_type != TxnType.PAYMENT})
    if len(indices) < MIN_CYCLES:
        failures.append(GateFailure(
            gate="COVERAGE",
            detail=f"only {len(indices)} distinct reward cycle(s) present; "
                   f"{MIN_CYCLES} required (D-016d).",
        ))
    elif len(indices) != indices[-1] - indices[0] + 1:
        missing = sorted(set(range(indices[0], indices[-1] + 1)) - set(indices))
        failures.append(GateFailure(
            gate="COVERAGE",
            detail=f"{len(missing)} reward cycle(s) missing from the sequence "
                   f"(D-016d).",
        ))

    # 4. Documents that have not been reconciled against the statement.
    for doc in documents or ():
        status = getattr(doc, "status", None)
        if status is None and isinstance(doc, dict):
            status = doc.get("status")
        if status != "RECONCILED":
            name = getattr(doc, "name", None) or getattr(doc, "doc_id", None) or str(doc)
            failures.append(GateFailure(
                gate="UNRECONCILED_DOCUMENT",
                detail=f"{name} has status {status!r}, expected 'RECONCILED' (D-016d).",
            ))

    return failures


# --- confidence ---------------------------------------------------------------

def _cap(level, ceiling):
    return ceiling if Confidence.ORDER[level] > Confidence.ORDER[ceiling] else level


def _evidence_confidence(txns):
    """Value-weighted confidence in the categorisation of the evidence."""
    total = sum(_spend_value(t) for t in txns)
    if total <= 0:
        return Confidence.UNKNOWN
    high = sum(_spend_value(t) for t in txns if t.confidence == Confidence.HIGH)
    known = high + sum(_spend_value(t) for t in txns
                       if t.confidence == Confidence.MEDIUM)
    if Decimal(high) / Decimal(total) >= Decimal("0.9"):
        return Confidence.HIGH
    if Decimal(known) / Decimal(total) >= Decimal("0.75"):
        return Confidence.MEDIUM
    return Confidence.LOW


def _spread_caps(bands, confidence):
    """A wide conservative/optimistic spread is itself a lack of confidence (D-010)."""
    conservative, expected, optimistic = bands
    spread = optimistic.minor - conservative.minor
    scale = max(abs(expected.minor), 1)
    if spread == 0:
        return confidence
    if Decimal(spread) / Decimal(scale) > Decimal("0.5"):
        return _cap(confidence, Confidence.LOW)
    return _cap(confidence, Confidence.MEDIUM)


# --- recommendation (D-016c) --------------------------------------------------

def _bucket(net_minor, fee_minor, exponent, confidence):
    fee = Decimal(fee_minor)
    if fee <= 0:
        fee = Decimal(_ZERO_FEE_DIVISOR_MAJOR) * (Decimal(10) ** exponent)
    net = Decimal(net_minor)
    if net > 2 * fee and confidence == Confidence.HIGH:
        return STRONGLY_BENEFICIAL
    if net > fee / 2:
        return BENEFICIAL
    if net > 0:
        return MARGINALLY_BENEFICIAL
    if net >= -fee / 10:
        return NEUTRAL
    return NOT_BENEFICIAL


def _cap_verdict(verdict, ceiling):
    return _RANK[min(_RANK.index(verdict), _RANK.index(ceiling))]


def recommend(txns, card, horizon, incumbent=None):
    """The verdict, the value behind it, and the plan that acts on it.

    Order matters: gates are checked first and override everything (D-016c),
    then value picks a bucket, then confidence and a revolving balance may only
    ever cap that bucket -- never raise it.
    """
    txns = list(txns)
    gates = quality_gates(txns, card)

    value = net_value(txns, card, horizon)                 # steady state (D-016b)
    year_one = net_value(txns, card, horizon, year_one=True)
    bands = sensitivity_bands(txns, card, horizon)

    confidence = _evidence_confidence(txns)
    confidence = _spread_caps(bands, confidence)
    if card.has_unknowable_exclusion:
        # D-025: "any other transactions determined by the Bank from time to time"
        # cannot be modelled, so certainty is not available at any spend level.
        confidence = _cap(confidence, Confidence.MEDIUM)

    warnings = list(value.warnings)
    assumptions = list(value.assumptions)
    assumptions.append(Assumption(
        label="Analysis horizon",
        value=f"Value computed forward over {horizon.months} month(s) from "
              f"{horizon.start} (D-016b).",
    ))
    assumptions.append(Assumption(
        label="Year one vs steady state",
        value=f"Year one net {year_one.net.minor}; steady state net "
              f"{value.net.minor} minor units. The verdict uses steady state "
              f"(D-016b).",
    ))
    conservative, expected, optimistic = bands
    assumptions.append(Assumption(
        label="Sensitivity band",
        value=f"Net value ranges {conservative.minor}..{optimistic.minor} minor "
              f"units around {expected.minor} (D-010).",
    ))

    verdict = _bucket(value.net.minor, card.annual_fee.minor,
                      card.annual_fee.exponent, confidence)

    # Confidence caps but never raises (D-016c).
    if confidence == Confidence.MEDIUM:
        verdict = _cap_verdict(verdict, BENEFICIAL)
    elif confidence in _UNSURE:
        verdict = _cap_verdict(verdict, MARGINALLY_BENEFICIAL)

    # D-016e: a carried balance at 39-46% APR dwarfs any cashback.
    if any(t.txn_type == TxnType.INTEREST for t in txns):
        verdict = _cap_verdict(verdict, MARGINALLY_BENEFICIAL)
        warnings.append(
            "REVOLVING_BALANCE: interest was charged in the observed window. "
            "Financing cost dominates reward value, so the verdict is capped at "
            f"{MARGINALLY_BENEFICIAL} (D-016e)."
        )

    # D-016d: withheld data beats any computed value.
    if gates:
        verdict = INSUFFICIENT_DATA
        warnings.extend(f"Quality gate {g.gate}: {g.detail}" for g in gates)

    # D-027: the plan is the primary output, not an afterthought.
    wallet = [card] if incumbent is None else [card, incumbent]
    plan = route(txns, wallet, horizon)

    return Recommendation(
        verdict=verdict,
        net_annual_value=value.net,
        confidence=confidence,
        plan=plan,
        assumptions=assumptions,
        gate_failures=gates,
        warnings=warnings,
    )
