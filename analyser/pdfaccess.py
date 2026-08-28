"""Open a statement PDF, decrypting it if a password is stored.

Encryption is an access detail, not a parsing concern. Every reader goes through
`readable()`, so parsers, the registry and ingestion all stay unaware of it.

A decrypted copy exists only for the life of the context manager and is deleted
immediately -- an unlocked statement is never left on disk.
"""
import contextlib
import os
import tempfile
import warnings


class DocumentEncrypted(Exception):
    """The PDF needs a user password and none is stored."""

    def __init__(self, file_name, message=None):
        self.file_name = file_name
        super().__init__(message or f"{file_name} needs a password")


def is_encrypted(path) -> bool:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pypdf
        try:
            return bool(pypdf.PdfReader(path).is_encrypted)
        except Exception:                                     # noqa: BLE001
            return False


def try_password(path, password) -> bool:
    """Does this password open the document? Used to validate before storing."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pypdf
        try:
            r = pypdf.PdfReader(path)
            if not r.is_encrypted:
                return True
            return bool(r.decrypt(password)) and len(r.pages) > 0
        except Exception:                                     # noqa: BLE001
            return False


@contextlib.contextmanager
def readable(path, password=None):
    """Yield a path that can be opened normally.

    Unencrypted files yield unchanged. Encrypted ones are decrypted to a temporary
    file which is removed on exit. Raises DocumentEncrypted when no working
    password is available.
    """
    if not is_encrypted(path):
        yield path
        return

    from analyser.secrets import all_passwords
    file_name = os.path.basename(path)

    # Try the caller's password first, then every stored one. Banks reuse a single
    # password across all of a cardholder's statements, so one stored secret
    # typically unlocks an entire issuer's history (D-034).
    candidates = ([password] if password is not None
                  else [pw for _label, pw in all_passwords()])
    pw = next((c for c in candidates if try_password(path, c)), None)
    if pw is None:
        raise DocumentEncrypted(file_name)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pypdf
        reader = pypdf.PdfReader(path)
        if not reader.decrypt(pw):
            raise DocumentEncrypted(file_name, f"password no longer opens {file_name}")
        writer = pypdf.PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        writer.write(tmp)
        tmp.close()
        yield tmp.name
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp.name)                               # never left unlocked
