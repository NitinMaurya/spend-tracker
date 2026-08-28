"""User correction files — the human-owned half of the data (D-001, D-026b/c, spec §18).

These are plain CSVs so they can be edited in any editor, diffed, and backed up.
A correction here is authoritative and permanent: it wins over whatever the system
inferred, and it applies to every future statement.
"""
import csv
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
MERCHANT_MAP = os.path.join(DATA_DIR, "merchant_map.csv")
CATEGORY_MAP = os.path.join(DATA_DIR, "category_overrides.csv")

MERCHANT_HEADER = ["match", "canonical"]
CATEGORY_HEADER = ["canonical", "category"]


def _load(path, key, value, *, upper_keys):
    """Read a two-column CSV into a dict. Missing file -> empty (not an error).

    `upper_keys` matters: the alias map is matched against RAW descriptions, which
    statements print in mixed case, so those keys are folded to upper. The category
    map is keyed on the CANONICAL merchant, which is looked up exactly as written
    ('Emarat', 'noon'), so folding those would silently miss every lookup.
    """
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            k = (row.get(key) or "").strip()
            v = (row.get(value) or "").strip()
            if not k or not v or k.startswith("#"):
                continue
            out[k.upper() if upper_keys else k] = v
            if not upper_keys:
                out.setdefault(k.upper(), v)   # tolerate either casing in the file
    return out


def load_alias_map(path=None):
    """match (uppercased substring of the raw description) -> canonical merchant."""
    return _load(path or MERCHANT_MAP, "match", "canonical", upper_keys=True)


def load_category_map(path=None):
    """canonical merchant -> category. Keyed as written, matched case-insensitively."""
    raw = _load(path or CATEGORY_MAP, "canonical", "category", upper_keys=False)
    return {k: v.upper() for k, v in raw.items()}


def ensure_files(data_dir=None):
    """Create the correction files with headers and a worked example if absent.

    Returns the list of paths created (empty when both already exist).
    """
    d = data_dir or DATA_DIR
    os.makedirs(d, exist_ok=True)
    created = []
    m = os.path.join(d, "merchant_map.csv")
    if not os.path.exists(m):
        with open(m, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(MERCHANT_HEADER)
            for row in [
                ("EMARAT", "Emarat"),
                ("DUBAI ELECTRICITY", "DEWA"),
                ("CAREEM", "Careem"),
                ("ALMOSAFER", "Almosafer"),
                ("NOON", "noon"),
            ]:
                w.writerow(row)
        created.append(m)
    c = os.path.join(d, "category_overrides.csv")
    if not os.path.exists(c):
        with open(c, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(CATEGORY_HEADER)
            for row in [
                ("Emarat", "FUEL"),
                ("DEWA", "UTILITIES"),
                ("Careem", "TRANSPORTATION"),
                ("Almosafer", "TRAVEL"),
                ("noon", "NOON"),
            ]:
                w.writerow(row)
        created.append(c)
    return created
