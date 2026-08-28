"""Gmail intake — find statement emails and download their PDF attachments.

Phase 2 of the intake design (D-003): `DocumentSource` was always meant to have a
Gmail implementation alongside the local folder, which is why ingestion is keyed on
a content hash. Re-running this over the same mailbox re-downloads nothing new and
re-ingests nothing.

Scope is READ-ONLY (`gmail.readonly`). This code cannot send, delete, or modify
anything in the mailbox, and the scope string is the enforcement -- Google rejects
any write call made with it.

Credentials live under data/gmail/ (gitignored). The token is the user's own OAuth
token for their own mailbox; nothing is transmitted anywhere except to Google.
"""
import base64
import os
import re

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GMAIL_DIR = os.path.join(ROOT, "data", "gmail")
CLIENT_SECRET = os.path.join(GMAIL_DIR, "client_secret.json")
TOKEN_PATH = os.path.join(GMAIL_DIR, "token.json")
STATEMENT_DIR = os.path.join(ROOT, "data", "statements")

# Deliberately broad: banks phrase these wildly differently, and a missed statement
# is worse than an irrelevant hit the user can ignore. Attachments are filtered to
# PDFs regardless.
# Targeted at the senders that actually mail UAE card statements. Verified against
# a real mailbox: a purely keyword-based query also drags in Indian bank statements,
# VAT invoices, transfer advices and marketing, none of which any parser handles.
# Sender-anchored keeps the signal high; `broad()` is available when something is
# genuinely missing.
STATEMENT_SENDERS = (
    "estatements@cbdstatements.ae",
    "statement@emiratesnbd.com",
    "estatement@emiratesislamic.ae",
    "mashreqstatements@mashreq.com",
    "estatement@bankfab.com",
    "communications@mail.wio.io",
    "estatement@dubaifirst.com",
    "estatement@adcb.com",
    "estatements@rakbank.ae",
)

DEFAULT_QUERY = (
    "has:attachment filename:pdf ("
    + " OR ".join(f"from:{s}" for s in STATEMENT_SENDERS)
    + ") -subject:(advice OR VAT OR invoice OR investor OR transfer)"
)

#: Keyword-based fallback for an issuer not in the sender list above.
BROAD_QUERY = (
    'has:attachment filename:pdf '
    'subject:(statement OR "credit card" OR e-statement OR KFS OR "key facts")'
)


class GmailNotConfigured(Exception):
    """No OAuth client secret has been provided yet."""


def is_configured() -> bool:
    return os.path.exists(CLIENT_SECRET)


def check_client_secret():
    """Validate data/gmail/client_secret.json without revealing the secret.

    Returns a dict describing what is wrong, so a mis-downloaded file (the Web
    application type is the usual mistake) is caught before the consent flow.
    """
    import json

    if not os.path.exists(CLIENT_SECRET):
        return {"ok": False, "problem": "missing",
                "detail": f"No file at {CLIENT_SECRET}"}
    try:
        data = json.loads(open(CLIENT_SECRET, encoding="utf-8").read())
    except Exception as exc:                                      # noqa: BLE001
        return {"ok": False, "problem": "unreadable", "detail": type(exc).__name__}

    if "installed" not in data:
        kind = "web" if "web" in data else next(iter(data), "unknown")
        return {"ok": False, "problem": "wrong_type",
                "detail": f"This is a '{kind}' client. Gmail needs an OAuth client of "
                          "type 'Desktop app' — create a new one and download that."}

    node = data["installed"]
    missing = [k for k in ("client_id", "client_secret", "auth_uri", "token_uri")
               if not node.get(k)]
    if missing:
        return {"ok": False, "problem": "incomplete",
                "detail": f"Missing: {', '.join(missing)}"}

    cid = node["client_id"]
    return {"ok": True, "client_id_suffix": cid[-32:], "project_id": node.get("project_id"),
            "detail": "Desktop OAuth client looks good."}


def is_connected() -> bool:
    return os.path.exists(TOKEN_PATH)


def _credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not is_configured():
        raise GmailNotConfigured(
            "No Google OAuth client is set up. See data/gmail/README for the steps."
        )
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save(creds)
        return creds
    return None


def _save(creds):
    os.makedirs(GMAIL_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    os.chmod(TOKEN_PATH, 0o600)


def connect():
    """Run the desktop OAuth flow. Opens a browser; returns the account address.

    This is interactive by nature -- Google requires a human to grant consent -- so
    it is triggered explicitly, never as a side effect of a page load.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not is_configured():
        raise GmailNotConfigured("No client_secret.json in data/gmail/.")
    creds = _credentials()
    if creds is None:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
        _save(creds)
    return profile()


def _service():
    from googleapiclient.discovery import build

    creds = _credentials()
    if creds is None:
        raise GmailNotConfigured("Not connected. Run the Gmail connect step first.")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def profile():
    p = _service().users().getProfile(userId="me").execute()
    return {"email": p.get("emailAddress"), "messages_total": p.get("messagesTotal")}


def _safe_name(sender, date, filename):
    """A stable, readable file name. Same email + attachment -> same name."""
    # Keep the sender domain INTACT: it is how the issuer is resolved later
    # (analyser.issuers.by_sender). Truncating it once turned "mashreq.com" into
    # "mashreq-co" and made the bank unidentifiable.
    who = re.sub(r"[^a-z0-9]+", "-", (sender or "unknown").lower()).strip("-")[:48]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(filename or "statement.pdf"))
    return f"{date}_{who}_{base}"


def search(query=None, limit=25):
    """List candidate statement emails without downloading anything."""
    svc = _service()
    res = svc.users().messages().list(
        userId="me", q=query or DEFAULT_QUERY, maxResults=limit).execute()
    out = []
    for ref in res.get("messages", []):
        msg = svc.users().messages().get(
            userId="me", id=ref["id"],
            format="metadata", metadataHeaders=["From", "Subject", "Date"]).execute()
        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        pdfs = [p.get("filename") for p in _parts(msg["payload"])
                if (p.get("filename") or "").lower().endswith(".pdf")]
        out.append({
            "id": ref["id"],
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "attachments": pdfs,
        })
    return out


def _parts(payload):
    yield payload
    for part in payload.get("parts", []) or []:
        yield from _parts(part)


def _record(file_name, *, message_id, thread_id, subject, sender, received_at,
            attachment):
    """Remember which email a statement came from, so it can be traced back.

    Written at download time and keyed by file name, so the link survives a database
    rebuild -- the email is the ORIGINAL source of the document and losing that
    breaks the evidence chain the whole system rests on (spec §19).
    """
    from datetime import datetime, timezone
    from analyser import db as dbmod

    db_path = os.path.join(ROOT, "data", "analyser.db")
    try:
        conn = dbmod.connect(db_path)
        dbmod.migrate(conn)
        conn.execute(
            "INSERT OR REPLACE INTO gmail_messages (file_name,message_id,thread_id,"
            "subject,sender,received_at,attachment,fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (file_name, message_id, thread_id, subject, sender, received_at,
             attachment, datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()
    except Exception:                                    # noqa: BLE001
        pass          # a provenance failure must never lose the download itself


def permalink(message_id):
    """A Gmail URL that opens the original email in the browser."""
    return f"https://mail.google.com/mail/u/0/#all/{message_id}"


def download(query=None, limit=25):
    """Download every PDF attachment on matching emails into the statement library.

    Files already present with identical bytes are reported as skipped, so this is
    safe to run repeatedly (D-003).
    """
    svc = _service()
    os.makedirs(STATEMENT_DIR, exist_ok=True)
    res = svc.users().messages().list(
        userId="me", q=query or DEFAULT_QUERY, maxResults=limit).execute()

    saved, skipped = [], []
    for ref in res.get("messages", []):
        msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        sender = re.sub(r".*<|>.*", "", headers.get("From", "")) or "unknown"
        date = (msg.get("internalDate") or "0")
        import datetime as _dt
        stamp = _dt.datetime.utcfromtimestamp(int(date) / 1000).strftime("%Y-%m-%d")

        for part in _parts(msg["payload"]):
            fname = part.get("filename") or ""
            if not fname.lower().endswith(".pdf"):
                continue
            body = part.get("body", {})
            data = body.get("data")
            if not data and body.get("attachmentId"):
                att = svc.users().messages().attachments().get(
                    userId="me", messageId=ref["id"], id=body["attachmentId"]).execute()
                data = att.get("data")
            if not data:
                continue
            raw = base64.urlsafe_b64decode(data)
            if not raw[:5].startswith(b"%PDF"):
                continue
            dest = os.path.join(STATEMENT_DIR, _safe_name(sender, stamp, fname))
            if os.path.exists(dest) and open(dest, "rb").read() == raw:
                # Backfill provenance for files fetched before this was recorded.
                _record(os.path.basename(dest), message_id=ref["id"],
                        thread_id=msg.get("threadId"),
                        subject=headers.get("Subject", ""), sender=sender,
                        received_at=stamp, attachment=fname)
                skipped.append(os.path.basename(dest))
                continue
            with open(dest, "wb") as fh:
                fh.write(raw)
            _record(os.path.basename(dest), message_id=ref["id"],
                    thread_id=msg.get("threadId"), subject=headers.get("Subject", ""),
                    sender=sender, received_at=stamp, attachment=fname)
            saved.append({"file_name": os.path.basename(dest), "size_bytes": len(raw),
                          "from": sender, "subject": headers.get("Subject", ""),
                          "message_id": ref["id"],
                          "permalink": permalink(ref["id"])})
    return {"saved": saved, "skipped": skipped}


def disconnect():
    """Remove the stored token. The Google-side grant is revoked in the user's
    account settings; this only forgets it locally."""
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)
        return True
    return False
