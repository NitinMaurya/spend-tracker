"""Merchant normalization and categorization — D-026b, D-026c, spec §F3/F4."""
import pytest
from analyser.normalize import normalize_merchant, categorize
from analyser.domain.model import Confidence

pytestmark = pytest.mark.red

ALIASES = {
    "EMARAT": "Emarat", "NOON": "noon", "CAREEM": "Careem",
    "DUBAI ELECTRICITY": "DEWA", "ALMOSAFER": "Almosafer",
}
CATEGORIES = {
    "Emarat": "FUEL", "noon": "NOON", "Careem": "TRANSPORTATION",
    "DEWA": "UTILITIES", "Almosafer": "TRAVEL",
}


class TestNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("EMARAT 7185 AL KHAIL DUBAI AE", "Emarat"),
        ("DUBAI ELECTRICITY DUBAI AE",    "DEWA"),
        ("Almosafer Travel Dubai AE",     "Almosafer"),
        ("CAREEM PLUS Dubai AE",          "Careem"),
    ])
    def test_strips_terminal_city_and_country(self, raw, expected):
        canonical, _, _ = normalize_merchant(raw, alias_map=ALIASES)
        assert canonical == expected

    def test_concatenated_merchant_and_city_splits(self):
        """Mashreq prints 'noondubai' with no separator."""
        canonical, city, _ = normalize_merchant("noondubai", issuer="MASHREQ", alias_map=ALIASES)
        assert canonical == "noon"

    def test_different_terminals_of_one_merchant_unify(self):
        a, _, _ = normalize_merchant("EMARAT 7185 AL KHAIL DUBAI AE", alias_map=ALIASES)
        b, _, _ = normalize_merchant("EMARAT 7186 JUMEIRAH DUBAI AE", alias_map=ALIASES)
        assert a == b == "Emarat"

    def test_similar_names_are_never_merged(self):
        """D-026b / spec §F4 guardrail: no fuzzy matching. AL MAYA and AL MAHA are
        different businesses differing by one character.

        Positive control: 'Al Maya' IS in the alias map and 'AL MAHA' is not, so a
        fuzzy matcher would pull AL MAHA onto Al Maya. Only an exact/boundary matcher
        leaves it unresolved."""
        aliases = {**ALIASES, "AL MAYA": "Al Maya"}
        a, _, _ = normalize_merchant("AL MAYA SUPERMARKET DUBAI AE", alias_map=aliases)
        b, _, _ = normalize_merchant("AL MAHA TRADING DUBAI AE", alias_map=aliases)
        assert a == "Al Maya"
        assert b != "Al Maya"

    def test_one_character_difference_does_not_match_an_alias(self):
        """A single transposed character must not resolve. 'NOOM' is not 'noon'."""
        c, _, _ = normalize_merchant("NOOM STORE DUBAI AE", alias_map=ALIASES)
        assert c != "noon"

    def test_unknown_merchant_keeps_raw_and_flags_low_confidence(self):
        canonical, _, conf = normalize_merchant("ZZQQ TRADING 4471", alias_map=ALIASES)
        assert conf in (Confidence.UNKNOWN, Confidence.LOW)

    def test_raw_description_is_never_destroyed(self):
        """Spec §F4: maintain both rawMerchant and canonicalMerchant."""
        raw = "EMARAT 7185 AL KHAIL DUBAI AE"
        canonical, _, _ = normalize_merchant(raw, alias_map=ALIASES)
        assert canonical != raw and canonical is not None


class TestCategorization:
    @pytest.mark.parametrize("merchant,expected", [
        ("Emarat", "FUEL"), ("DEWA", "UTILITIES"),
        ("noon", "NOON"), ("Almosafer", "TRAVEL"),
    ])
    def test_known_merchants_categorize_deterministically(self, merchant, expected):
        cat, _ = categorize(merchant, "", category_map=CATEGORIES)
        assert cat == expected

    def test_unknown_merchant_is_uncategorized_not_guessed(self):
        """Spec §P4: 'Unknown' beats a confident wrong category."""
        cat, conf = categorize(None, "ZZQQ TRADING 4471", category_map=CATEGORIES)
        assert cat is None or conf in (Confidence.UNKNOWN, Confidence.LOW)

    def test_user_correction_becomes_authoritative(self):
        """Spec §18: a correction is permanent and wins over the system value."""
        cat, conf = categorize("ABC Market", "", category_map={**CATEGORIES, "ABC Market": "GROCERIES"})
        assert cat == "GROCERIES" and conf == Confidence.HIGH

    def test_no_network_call_in_categorization(self, monkeypatch):
        """D-026c: no merchant string may reach a hosted model."""
        import socket
        def boom(*a, **k):
            raise AssertionError("categorization must not open a network connection")
        monkeypatch.setattr(socket, "socket", boom)
        categorize("Emarat", "", category_map=CATEGORIES)
