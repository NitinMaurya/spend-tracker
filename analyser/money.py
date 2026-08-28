"""Money and date helpers. Money is always INTEGER minor units."""
from decimal import Decimal, ROUND_HALF_UP
import re

# No sign in this pattern: sign handling happens before matching, so a
# residual sign (e.g. "--5") must be rejected rather than absorbed.
_NUM = re.compile(r"^[\d,]+(?:\.\d+)?$")


def to_minor(text, *, credit_suffix=True):
    """Parse '1,404.54' or '0.59 CR' -> integer fils. Returns None if unparseable.

    'CR' suffix (CBD/ENBD convention) flips the sign.
    """
    if text is None:
        return None
    s = str(text).strip().replace(" ", " ")
    negative = False
    if credit_suffix and s.upper().endswith("CR"):
        s = s[:-2].strip()
        negative = True
    if s.startswith("(") and s.endswith(")"):
        s, negative = s[1:-1].strip(), True
    if s.startswith("+"):
        s = s[1:].strip()
    if s.startswith("-"):
        s, negative = s[1:].strip(), True
    if not _NUM.match(s):
        return None
    val = (Decimal(s.replace(",", "")) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(-val if negative else val)


def fmt(minor, currency="AED"):
    if minor is None:
        return "—"
    return f"{currency} {minor / 100:,.2f}"
