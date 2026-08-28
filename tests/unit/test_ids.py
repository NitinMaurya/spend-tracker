"""Deterministic identifiers — D-003."""
from analyser.ids import raw_id, document_id


class TestIdempotency:
    def test_same_input_same_id(self):
        a = raw_id("fab", "2026-07-05", "2026-07-07", -87019, "Almosafer Travel Dubai AE", 1)
        b = raw_id("fab", "2026-07-05", "2026-07-07", -87019, "Almosafer Travel Dubai AE", 1)
        assert a == b

    def test_whitespace_and_case_normalised(self):
        a = raw_id("fab", "2026-07-05", None, -100, "CAREEM  PLUS", 1)
        b = raw_id("fab", "2026-07-05", None, -100, "careem plus", 1)
        assert a == b

    def test_sequence_separates_genuine_duplicates(self):
        """FAB has two identical CAREEM PLUS 1.00 rows on 2026-07-15 (a charge and
        its reversal). Both must survive; only the sequence distinguishes them."""
        a = raw_id("fab", "2026-07-15", "2026-07-16", -100, "CAREEM PLUS Dubai AE", 3)
        b = raw_id("fab", "2026-07-15", "2026-07-16", 100, "CAREEM PLUS Dubai AE", 4)
        assert a != b

    def test_amount_change_changes_id(self):
        a = raw_id("fab", "2026-07-05", None, -87019, "X", 1)
        b = raw_id("fab", "2026-07-05", None, -87020, "X", 1)
        assert a != b

    def test_account_scoped(self):
        a = raw_id("fab", "2026-07-05", None, -100, "X", 1)
        b = raw_id("enbd", "2026-07-05", None, -100, "X", 1)
        assert a != b

    def test_document_id_is_content_hash(self):
        assert document_id(b"abc") == document_id(b"abc")
        assert document_id(b"abc") != document_id(b"abd")
