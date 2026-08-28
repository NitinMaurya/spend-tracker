"""Card terms extraction, provenance, conflicts, effective dating.

Deterministic text parsing only (no model, no network): every value emitted here
must be locatable verbatim in the source document (D-028h), which is what makes an
injected "10% cashback" line inert rather than merely discouraged.

D-013, D-022, D-023, D-025, D-028a, D-028h.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re

from analyser.money import to_minor

# KFS > T&C > product page > third party (D-022 / spec §Feature 7).
SOURCE_PRECEDENCE = {
    "KFS": 0,
    "TC": 1,
    "T&C": 1,
    "TERMS": 1,
    "PRODUCT_PAGE": 2,
    "THIRD_PARTY": 3,
}
_LOWEST_PRECEDENCE = 99

# "5% cashback on noon, noon Food and noon Minutes" -- the rate must lead the line,
# so a sentence that merely mentions a percentage cannot become a tier.
_TIER = re.compile(r"^(\d+(?:\.\d+)?)\s*%\s+cash\s?back\s+on\s+(.+?)\s*$", re.IGNORECASE)
_CAP = re.compile(
    r"(?:capped at|up to|maximum of)\s*(?:AED|SAR)?\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE
)
_FX_SPREAD = re.compile(
    r"spread on international transactions[^\n:]*:\s*(\d+(?:\.\d+)?)\s*%", re.IGNORECASE
)
# The scheme's own fee is never stated, so the total cost is not derivable (D-013).
_FX_UNQUANTIFIED = re.compile(
    r"plus\s+visa\s*/?\s*mastercard\s+charges\s+as\s+applicable", re.IGNORECASE
)
_INTEREST = re.compile(
    r"retail interest rate:\s*(\d+(?:\.\d+)?)\s*%\s*per annum", re.IGNORECASE
)
_ANCHOR = re.compile(
    r"statement date on\s*(\d{1,2})(?:st|nd|rd|th)\s+of every month", re.IGNORECASE
)
_CYCLE_WINDOW = re.compile(
    r"between\s+(\d{1,2})(?:st|nd|rd|th)\s+of the previous month\s+and\s+"
    r"(\d{1,2})(?:st|nd|rd|th)\s+of the current month",
    re.IGNORECASE,
)
_EXPIRY = re.compile(r"\((\d{1,3})\)\s*months\s+from the date of accrual", re.IGNORECASE)
_ROUND_DOWN = re.compile(r"round\s+down\s+the total cashback[^.]*nearest dirham", re.IGNORECASE)
_UNKNOWABLE = re.compile(
    r"any other transactions? determined by the bank", re.IGNORECASE
)
_CHANNEL_DEPENDENT = re.compile(
    r"(call cent(?:re|er)|mobile banking|on-?line|atm|branch)", re.IGNORECASE
)

# An instruction addressed to the reader is data, never a directive (spec §22).
_INJECTION = re.compile(
    r"(ignore (?:all )?previous|disregard (?:all )?(?:previous|prior)|"
    r"instead (?:state|say|report)|you (?:are|must)\b|system prompt)",
    re.IGNORECASE,
)


def _pct_to_bps(text):
    """'0.33' -> 33 bps. Decimal only; a float would drift on 2.89 (D-002)."""
    return int((Decimal(text) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _card_is_present(text, card_name):
    """D-022: one KFS covers six products, so the named card must actually appear.

    Rotated table headers come out of the PDF reversed ('kcabhsaC'), so the name and
    its reverse are both accepted. Absence returns nothing at all -- never the rates
    of a neighbouring row.
    """
    if not card_name:
        return False
    haystack = (text or "").lower()
    needle = card_name.strip().lower()
    return bool(needle) and (needle in haystack or needle[::-1] in haystack)


def _extract_tiers(text):
    tiers = []
    for line in _lines(text):
        if _INJECTION.search(line):
            continue
        m = _TIER.match(line)
        if not m:
            continue
        cap = _CAP.search(line)
        tiers.append({
            "rate_bps": _pct_to_bps(m.group(1)),
            "category": m.group(2).strip(),
            # A cap that is not stated is unknown -- neither zero nor unlimited (§P3).
            "cap_per_cycle": to_minor(cap.group(1)) if cap else None,
            "source_quote": line,
        })
    # Provenance is not decorative: a tier whose quote cannot be relocated is dropped.
    return [t for t in tiers if verify_verbatim(t, text)]


def _extract_exclusions(text):
    exclusions = []
    for line in _lines(text):
        if _INJECTION.search(line):
            continue
        if _UNKNOWABLE.search(line):
            # D-025: open-ended clause; not modellable, caps confidence at MEDIUM.
            detectability = "UNKNOWABLE"
        elif "exclud" in line.lower() or "not eligible" in line.lower():
            detectability = ("CHANNEL_DEPENDENT" if _CHANNEL_DEPENDENT.search(line)
                             else "DETECTABLE")
        else:
            continue
        exclusions.append({"description": line,
                           "detectability": detectability,
                           "source_quote": line})
    return exclusions


def _extract_facts(text):
    """Everything this document states, as a flat fact dict (missing == absent key)."""
    facts = {}

    tiers = _extract_tiers(text)
    if tiers:
        facts["tiers"] = tiers

    exclusions = _extract_exclusions(text)
    if exclusions:
        facts["exclusions"] = exclusions

    fx = _FX_SPREAD.search(text or "")
    if fx:
        facts["fx_spread_bps"] = _pct_to_bps(fx.group(1))
        # D-013: the scheme fee is stated nowhere, so the total stays UNKNOWN.
        facts["fx_total_bps"] = (None if _FX_UNQUANTIFIED.search(text)
                                 else facts["fx_spread_bps"])

    interest = _INTEREST.search(text or "")
    if interest:
        facts["retail_interest_bps"] = _pct_to_bps(interest.group(1))

    if re.search(r"free for life", text or "", re.IGNORECASE):
        facts["annual_fee_minor"] = 0

    cycle = {}
    anchor = _ANCHOR.search(text or "")
    if anchor:
        cycle["anchor_day"] = int(anchor.group(1))
    window = _CYCLE_WINDOW.search(text or "")
    if window:
        cycle["window_start_day"] = int(window.group(1))
        cycle["window_end_day"] = int(window.group(2))
    if cycle:
        facts["cycle"] = cycle

    expiry = _EXPIRY.search(text or "")
    if expiry:
        facts["expiry_months"] = int(expiry.group(1))

    if _ROUND_DOWN.search(text or ""):
        # D-023: contractual and per-cycle; never a default.
        facts["rounding"] = {"mode": "DOWN", "unit": "MAJOR", "scope": "CYCLE"}

    return facts


def extract_rules(document_text, *, card_name):
    """D-022: one document may describe many cards; resolve the right one.

    Returns None when the named card is not in the document, because silently
    returning a neighbouring product's rates is the worst failure available here.
    """
    if not _card_is_present(document_text, card_name):
        return None

    rules = _extract_facts(document_text)
    rules["card_name"] = card_name
    rules.setdefault("tiers", [])
    rules.setdefault("exclusions", [])
    rules.setdefault("fx_spread_bps", None)
    rules.setdefault("fx_total_bps", None)
    return rules


def verify_verbatim(rule, source_text):
    """D-028h: a value that cannot be located verbatim in the source is rejected."""
    quote = (rule or {}).get("source_quote")
    if not quote or not source_text:
        return False
    return _flatten(quote) in _flatten(source_text)


def _flatten(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def _precedence(source):
    return SOURCE_PRECEDENCE.get(str(source or "").strip().upper(), _LOWEST_PRECEDENCE)


def merge_sources(rule_sets):
    """D-022: KFS > T&C > product page > third party, preserving provenance.

    Union of facts: the cycle and expiry come from the T&C, the rates from the KFS.
    Where two documents state the same fact the higher-precedence one wins.
    """
    merged = {"tiers": [], "exclusions": [], "sources": []}
    tiers_by_category = {}
    tier_provenance = {}

    # Weakest first, so a stronger document overwrites what it also states.
    for rule_set in sorted(rule_sets or [], key=lambda rs: -_precedence(rs.get("source"))):
        source = rule_set.get("source")
        facts = rule_set.get("facts") or _extract_facts(rule_set.get("text", ""))
        merged["sources"].append(source)

        for tier in facts.get("tiers", []):
            key = tier["category"].strip().lower()
            tiers_by_category[key] = dict(tier, source=source)
            tier_provenance[key] = source

        for exclusion in facts.get("exclusions", []):
            if not any(e["description"] == exclusion["description"]
                       for e in merged["exclusions"]):
                merged["exclusions"].append(dict(exclusion, source=source))

        for key, value in facts.items():
            if key in ("tiers", "exclusions"):
                continue
            merged[key] = value
            merged.setdefault("provenance", {})[key] = source

    merged["tiers"] = list(tiers_by_category.values())
    merged.setdefault("fx_spread_bps", None)
    merged.setdefault("fx_total_bps", None)
    return merged


def detect_conflicts(rule_sets):
    """D-023 / spec §F10: never silently pick a winner.

    Two authoritative documents stating different values for the same rule is a
    conflict to surface to the user, not something to resolve by precedence.
    """
    by_rule = {}
    for entry in rule_sets or []:
        by_rule.setdefault(entry.get("rule"), []).append(entry)

    conflicts = []
    for rule_name, entries in by_rule.items():
        values = {str(e.get("value")) for e in entries}
        sources = {str(e.get("source")) for e in entries}
        if len(values) > 1 and len(sources) > 1:
            conflicts.append({
                "rule": rule_name,
                "values": sorted(values),
                "sources": sorted(sources),
                "claims": entries,
                "resolution": "UNRESOLVED",
            })
    return conflicts


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def active_rules_at(rules, on_date):
    """D-028a: effective-dated rules ('Effective 8 July 2026, ...').

    Inclusive of valid_from and of valid_to; a rule is dead the day after valid_to.
    """
    when = _as_date(on_date)
    active = []
    for rule in rules or []:
        valid_from = _as_date(rule.get("valid_from"))
        valid_to = _as_date(rule.get("valid_to"))
        if valid_from and when < valid_from:
            continue
        if valid_to and when > valid_to:
            continue
        active.append(rule)
    return active
