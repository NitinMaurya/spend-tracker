"""Deterministic identifiers. These make re-ingesting a statement a no-op."""
import hashlib


def document_id(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def raw_id(account_id, txn_date, posting_date, amount_minor, raw_description, seq) -> str:
    """Stable across re-parses of the same statement.

    `seq` is the ordinal within the statement and is what disambiguates a
    genuine same-day duplicate (e.g. FAB's two CAREEM PLUS 1.00 rows) from a
    double-insert of the same row.
    """
    key = "|".join([
        account_id,
        txn_date or "",
        posting_date or "",
        str(amount_minor),
        " ".join((raw_description or "").split()).upper(),
        str(seq),
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
