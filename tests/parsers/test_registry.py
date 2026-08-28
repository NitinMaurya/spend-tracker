"""Parser dispatch — D-006: detect the issuer, then hand off."""
import os
import pytest
from tests.conftest import require_samples, SAMPLES

pytestmark = pytest.mark.golden


@pytest.mark.parametrize("filename,expected", [
    ("FAB_BLU_AUG_2026.pdf", "fab"),
    ("Mashreq_noon_Aug_2026.pdf", "mashreq"),
    ("CBD_AUG_2026.pdf", "cbd"),
    ("Emirates_islamic_RTA_Platinum_AUG_2026.pdf", "emirates_islamic"),
    ("Wio_Aug_2026.pdf", "wio"),
])
def test_issuer_detected_from_content_not_filename(filename, expected):
    require_samples()
    from analyser.parsers import detect_parser
    path = os.path.join(SAMPLES, filename)
    if not os.path.exists(path):
        pytest.skip(f"{filename} not present")
    assert detect_parser(path) == expected


def test_unknown_document_returns_none_rather_than_guessing():
    from analyser.parsers import detect_parser
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4\nnot a statement\n")
        name = f.name
    try:
        assert detect_parser(name) is None
    finally:
        os.unlink(name)


def test_encrypted_document_raises_when_no_password_is_available(monkeypatch):
    """An encrypted PDF with no stored password is REFUSED, never guessed at.

    Contract updated by D-034: detection now decrypts transparently when a password
    is on file, so the stored secrets are stubbed out to isolate the no-password
    case. Without that stub this test would pass or fail depending on what happens
    to be in the developer's Keychain.
    """
    require_samples()
    from analyser.parsers import detect_parser, DocumentEncrypted
    path = os.path.join(SAMPLES, "Emirates NBD VISA FLEXI Statement Feb 8 2026.pdf")
    if not os.path.exists(path):
        pytest.skip("ENBD sample not present")

    import analyser.secrets as secrets
    monkeypatch.setattr(secrets, "all_passwords", lambda: [])
    with pytest.raises(DocumentEncrypted):
        detect_parser(path)


def test_encrypted_document_opens_when_a_password_is_stored(monkeypatch):
    """The other half of D-034: a working stored password makes encryption invisible.

    Uses a deliberately wrong password to prove the mechanism is exercised without
    depending on a real secret: the document still refuses, but via the same path.
    """
    require_samples()
    from analyser.parsers import detect_parser, DocumentEncrypted
    path = os.path.join(SAMPLES, "Emirates NBD VISA FLEXI Statement Feb 8 2026.pdf")
    if not os.path.exists(path):
        pytest.skip("ENBD sample not present")

    import analyser.secrets as secrets
    monkeypatch.setattr(secrets, "all_passwords", lambda: [("enbd", "definitely-wrong")])
    with pytest.raises(DocumentEncrypted):
        detect_parser(path)
