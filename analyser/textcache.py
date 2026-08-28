"""Disk cache for extracted PDF text.

Terms documents (KFS, T&C) never change once downloaded, but pdfplumber costs ~0.5-1s
per document and the cards view reads every one of them. Caching the extracted text
turns a ~4.5s page into a ~0.02s one.

The cache key includes the file's size and modification time, so replacing a document
with a newer version invalidates its entry automatically -- there is no stale-cache
failure mode and no manual clearing step.
"""
import hashlib
import os

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache", "text")


def _key(path: str) -> str:
    st = os.stat(path)
    raw = f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def cached_text(path: str, extract):
    """Return the extracted text for `path`, computing it via `extract(path)` on a miss.

    A cache failure is never fatal: if the cache cannot be read or written we fall back
    to extracting directly, because a slow page is better than a broken one.
    """
    try:
        entry = os.path.join(CACHE_DIR, _key(path) + ".txt")
    except OSError:
        return extract(path)

    try:
        with open(entry, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        pass

    text = extract(path)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = entry + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, entry)          # atomic: never leaves a half-written entry
    except OSError:
        pass
    return text


def clear():
    """Drop every cached entry. Only needed if extraction logic itself changes."""
    removed = 0
    if not os.path.isdir(CACHE_DIR):
        return 0
    for name in os.listdir(CACHE_DIR):
        if name.endswith(".txt"):
            os.remove(os.path.join(CACHE_DIR, name))
            removed += 1
    return removed
