"""PDF passwords, stored in the macOS Keychain, keyed by issuer id.

Keyed by ISSUER, not by file: a bank issues one password per cardholder and reuses
it for every statement, so a per-file key would mean re-entering the same secret
dozens of times (D-034, D-036).

Passwords never reach the database, a config file, an environment variable, a log
line, or an API response (D-015).

Note on enumeration: an earlier version kept its own index of labels in a Keychain
entry. That was a mistake -- `security find-generic-password -w` returns HEX rather
than text whenever the stored value contains a newline, so a newline-joined index
came back as an unusable blob and every stored password looked missing. The issuer
registry already enumerates every valid key, so no index is needed.
"""
import subprocess

SERVICE = "credit-analyser-pdf"


def _run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


def get_password(issuer_id):
    r = _run(["security", "find-generic-password", "-s", SERVICE, "-a", issuer_id, "-w"])
    if not r or r.returncode != 0:
        return None
    return r.stdout.rstrip("\n") or None


def list_labels():
    """Issuer ids that currently have a stored password."""
    from analyser.issuers import all_issuers

    return [i.id for i in all_issuers() if get_password(i.id)]


def all_passwords():
    """(issuer_id, password) for every stored secret."""
    from analyser.issuers import all_issuers

    out = []
    for issuer in all_issuers():
        pw = get_password(issuer.id)
        if pw:
            out.append((issuer.id, pw))
    return out


def set_password(issuer_id, password) -> bool:
    r = _run(["security", "add-generic-password", "-U", "-s", SERVICE,
              "-a", issuer_id, "-w", password])
    return bool(r and r.returncode == 0)


def delete_password(issuer_id) -> bool:
    r = _run(["security", "delete-generic-password", "-s", SERVICE, "-a", issuer_id])
    return bool(r and r.returncode == 0)
