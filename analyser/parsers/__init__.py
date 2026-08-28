"""Parser registry and issuer detection (D-006).

One hand-written parser per issuer; this module decides *which* one a document
belongs to. Detection reads the CONTENT of page 1 only -- never the filename,
which is user-supplied and routinely wrong ("statement (3).pdf").

Design notes
------------
* Encryption is checked FIRST. A password-protected document has no readable
  page 1, so guessing at its issuer is meaningless; ``DocumentEncrypted`` is
  raised before any detection work happens. The Emirates NBD sample is the real
  case: pypdf reports ``is_encrypted`` and an empty-password ``decrypt("")``
  returns 0 (failure), i.e. a *user* password is required.
* Each issuer declares a set of SIGNATURES. A signature is a tuple of literal
  markers that must ALL appear in the normalised page-1 text; an issuer matches
  if any one of its signatures matches. Multi-marker signatures exist because
  single brand words collide across documents: the Wio statement contains the
  rows "Emirates NBD payment" and "Blu Fab payment", so a bare "fab" or "nbd"
  marker would mis-route it. No marker below is a bare issuer nickname.
* An unrecognised document returns ``None``. There is no nearest-match
  fallback: routing a statement to the wrong parser produces plausible-looking
  but wrong money, which is worse than refusing to parse.
* Import-time side effects are avoided -- the issuer modules (each of which
  imports pdfplumber) are only imported inside ``get_parser``.
"""
import re
import warnings

__all__ = [
    "DocumentEncrypted",
    "PARSERS",
    "detect_parser",
    "get_parser",
]


# The canonical definition lives in analyser.pdfaccess, which owns decryption.
# Re-exported here so `from analyser.parsers import DocumentEncrypted` keeps working.
from analyser.pdfaccess import DocumentEncrypted  # noqa: E402,F401


#: Registry order. Detection is signature-based and the signatures are
#: mutually exclusive, but the order is still fixed so behaviour is
#: deterministic if a future statement ever satisfies two of them.
PARSERS = ("fab", "dubai_first", "mashreq", "cbd", "emirates_islamic", "wio",
           "emirates_nbd")

# Markers verified against the real sample statements. Lower-case; matched
# against page-1 text whose runs of whitespace have been collapsed to one
# space, because the extractors split words unpredictably across columns.
_SIGNATURES = {
    "mashreq": (
        ("mashreqbank",),
        ("noon vip credit card",),
    ),
    "cbd": (
        ("commercial bank of dubai",),
        ("customercare@cbd.ae",),
        ("card type cbd",),
    ),
    "emirates_islamic": (
        ("emirates islamic",),
        ("statement of card account", "cashback closing balance"),
    ),
    "wio": (
        ("wio bank",),
        ("wio, pjsc",),
        ("wio pjsc",),
    ),
    # Emirates NBD sends three different documents from one address. Every
    # marker below is a PAIR, because each half collides on its own:
    # "statement of account" also appears on CBD and Mashreq page 1, and
    # "emirates nbd" appears on the Wio statement as the row "Emirates NBD
    # payment". No other sampled issuer prints both halves.
    "emirates_nbd": (
        ("credit card statement", "emirates nbd bank"),
        ("statement of account", "emirates nbd"),
        # The installment booking advice, so the parser can refuse it by name
        # rather than leaving it unidentified.
        ("repayment schedule", "emirates nbd credit card"),
    ),
    "fab": (
        ("first abu dhabi bank",),
        ("fab mobile banking",),
        ("main card number", "main card product"),
    ),
    # FAB acquired Dubai First, so both issuers mail from estatement@bankfab.com
    # and share a sender domain. The documents do not collide: Dubai First's
    # template is a background image whose only readable text is the values, and
    # it masks the PAN as 524204XXXXXX7264 -- the Visa BIN Dubai First issues on,
    # in a mask style FAB never prints (FAB uses "4XXX XX** **** NNNN"). None of
    # the other sampled statements, the Wio settlement rows included, mention it.
    "dubai_first": (
        ("524204",),
    ),
}


def _normalise(text):
    return re.sub(r"\s+", " ", text).lower()


def _raise_if_encrypted(path):
    """Raise DocumentEncrypted when the file needs a user password.

    Anything else that goes wrong here (a truncated file, not a PDF at all) is
    left alone -- that is detection's problem, and detection answers None.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        if not reader.is_encrypted:
            return
        # decrypt() returns 0 / PasswordType.NOT_DECRYPTED when the empty
        # password does not open the document.
        opened = reader.decrypt("")
    except DocumentEncrypted:
        raise
    except Exception:
        return
    if not opened:
        raise DocumentEncrypted(f"{path} is password-protected")


def _page_one_text(path):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                if not pdf.pages:
                    return None
                page = pdf.pages[0]
                text = page.extract_text() or ""
                if not text.strip():
                    # Some issuers lay the header out in columns that
                    # extract_text() drops; the layout mode keeps them.
                    text = page.extract_text(layout=True) or ""
    except Exception:
        return None
    return _normalise(text)


def detect_parser(path):
    """Return the issuer key for `path`, or None if nothing matches.

    Raises DocumentEncrypted if the document is password-protected.
    """
    from analyser.pdfaccess import readable

    # readable() yields a decrypted temp copy when a password is stored, and
    # raises DocumentEncrypted when one is needed but absent. Detection itself
    # stays unaware that encryption exists.
    with readable(path) as usable:
        text = _page_one_text(usable)
    if not text:
        return None
    for name in PARSERS:
        for signature in _SIGNATURES[name]:
            if all(marker in text for marker in signature):
                return name
    return None


def get_parser(name):
    """Import and return an issuer parser module by key (lazy, D-006)."""
    if name not in PARSERS:
        raise KeyError(name)
    import importlib

    return importlib.import_module(f"{__name__}.{name}")
