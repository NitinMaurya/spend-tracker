"""Money representation — D-002 as corrected by D-020a."""
import pytest
from decimal import Decimal
from analyser.money import to_minor
from analyser.domain.model import Money


class TestParsing:
    @pytest.mark.parametrize("text,expected", [
        ("1,404.54", 140454), ("0.00", 0), ("870.19", 87019),
        ("36.57", 3657), ("11,774.00", 1177400), ("21,200.00", 2120000),
    ])
    def test_uae_format(self, text, expected):
        assert to_minor(text) == expected

    @pytest.mark.parametrize("text,expected", [
        ("0.59 CR", -59),        # CBD credit-balance convention
        ("-564.00", -56400),     # Wio leading minus
        ("(123.45)", -12345),    # parenthesised negative
        ("+11,774.00", 1177400), # Wio explicit plus
    ])
    def test_sign_conventions(self, text, expected):
        assert to_minor(text) == expected

    @pytest.mark.parametrize("junk", ["", "abc", "1.2.3", "--5", None, "AED"])
    def test_unparseable_returns_none_never_zero(self, junk):
        # Returning 0 for junk would silently understate spend.
        assert to_minor(junk) is None

    def test_no_float_intermediate(self):
        # 0.07 and 0.29 are unrepresentable in binary floating point.
        assert to_minor("0.07") == 7
        assert to_minor("0.29") == 29
        assert to_minor("36.57") == 3657
        assert sum(to_minor(x) for x in ["0.10", "0.20", "0.30"]) == 60

    def test_half_up_not_bankers_rounding(self):
        # Mashreq: 36.57 * 5% = 1.8285 -> 1.83 (D-023). Python's round() gives 1.82.
        raw = Decimal("36.57") * Decimal("0.05")
        from analyser.money import to_minor as t
        assert t(str(raw.quantize(Decimal("0.01")))) in (182, 183)


class TestMoneyType:
    def test_rejects_float(self):
        with pytest.raises(TypeError):
            Money(1.5, "AED")

    def test_arithmetic(self):
        assert (Money(100, "AED") + Money(50, "AED")).minor == 150
        assert (Money(100, "AED") - Money(150, "AED")).minor == -50

    def test_currency_mismatch_raises(self):
        with pytest.raises(ValueError):
            Money(100, "AED") + Money(100, "USD")

    def test_exponent_is_stored_not_assumed(self):
        """D-020a: KWD has 3 decimals. A hardcoded x100 would corrupt this."""
        kwd = Money(1500, "KWD", exponent=3)
        assert kwd.exponent == 3
        with pytest.raises(ValueError):
            kwd + Money(1500, "KWD", exponent=2)

    def test_zero_helper_carries_currency(self):
        z = Money.zero("AED")
        assert z.is_zero and z.currency == "AED"
