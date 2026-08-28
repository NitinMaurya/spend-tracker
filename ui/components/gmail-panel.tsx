/**
 * Gmail intake panel (read-only).
 *
 * Three deliberate separations: connecting, fetching, and processing are distinct
 * actions. Connecting grants read access; fetching downloads attachments into the
 * library; nothing touches your numbers until Process is pressed (D-033).
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { gmail, type GmailMail, type GmailStatus } from "@/lib/api";
import { Chip, CardTitle } from "@/components/ui";

export function GmailPanel({ onDownloaded }: { onDownloaded: () => void }) {
  const [status, setStatus] = useState<GmailStatus | null>(null);
  const [mails, setMails] = useState<GmailMail[] | null>(null);
  const [busy, setBusy] = useState<null | "connect" | "search" | "download">(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try { setStatus(await gmail.status()); } catch { /* API down handled by the page */ }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const act = async (kind: "connect" | "search" | "download", fn: () => Promise<void>) => {
    setBusy(kind); setError(null); setMessage(null);
    try { await fn(); } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(null); }
  };

  if (!status) return null;

  return (
    <section className="rise mb-8 rounded-card border border-line bg-surface p-5 shadow-card"
             style={{ animationDelay: "30ms" }}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <CardTitle>From your inbox</CardTitle>
            {status.connected
              ? <Chip tone="ok">connected</Chip>
              : status.configured
                ? <Chip tone="warn">not connected</Chip>
                : <Chip tone="neutral">setup needed</Chip>}
          </div>
          <p className="mt-1 max-w-[64ch] text-sm text-ink2">
            {status.connected
              ? <>Reading statement emails for <span className="font-medium text-ink">{status.email}</span>. Read-only — this app cannot send, delete or change anything in your mailbox.</>
              : "Pull statement PDFs straight from your email instead of downloading them by hand. Access is read-only."}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {status.configured && !status.connected && (
            <button type="button" disabled={busy !== null}
              onClick={() => act("connect", async () => {
                const r = await gmail.connect();
                setMessage(`Connected as ${r.email}.`);
                await refresh();
              })}
              className="rounded-card px-4 py-2 text-sm font-semibold text-white disabled:opacity-45"
              style={{ background: "var(--accent)" }}>
              {busy === "connect" ? "Waiting for your browser…" : "Connect Gmail"}
            </button>
          )}
          {status.connected && (
            <>
              <button type="button" disabled={busy !== null}
                onClick={() => act("search", async () => { setMails(await gmail.search(25)); })}
                className="rounded-card border border-line bg-surface2 px-4 py-2 text-sm font-medium disabled:opacity-45">
                {busy === "search" ? "Looking…" : "Find statements"}
              </button>
              <button type="button" disabled={busy !== null}
                onClick={() => act("download", async () => {
                  const r = await gmail.download(25);
                  setMessage(
                    r.saved.length
                      ? `Added ${r.saved.length} statement${r.saved.length > 1 ? "s" : ""}${r.skipped.length ? `, ${r.skipped.length} already had` : ""}. Press Process to read them.`
                      : `Nothing new — ${r.skipped.length} already in your library.`);
                  onDownloaded();
                })}
                className="rounded-card px-4 py-2 text-sm font-semibold text-white disabled:opacity-45"
                style={{ background: "var(--accent)" }}>
                {busy === "download" ? "Fetching…" : "Fetch attachments"}
              </button>
              <button type="button" disabled={busy !== null}
                onClick={() => act("connect", async () => {
                  await gmail.disconnect(); setMails(null);
                  setMessage("Disconnected. The local token was removed.");
                  await refresh();
                })}
                className="rounded-card border border-line px-4 py-2 text-sm text-ink2 disabled:opacity-45">
                Disconnect
              </button>
            </>
          )}
        </div>
      </div>

      {!status.configured && (
        <div className="mt-4 rounded-lg border border-line bg-surface2 p-4 text-sm">
          <p className="font-medium">One-time setup, about three minutes</p>
          <p className="mt-1 text-ink2">
            Google requires you to create the OAuth client yourself — it cannot be done on
            your behalf. The steps are written out in:
          </p>
          <code className="mono mt-2 block text-xs text-accentInk">{status.setup_doc}</code>
          <p className="mt-2 text-xs text-ink3">
            Create a Google Cloud project, enable the Gmail API, add the{" "}
            <span className="mono">gmail.readonly</span> scope, create a{" "}
            <strong>Desktop app</strong> OAuth client, and save the JSON as{" "}
            <span className="mono">data/gmail/client_secret.json</span>.
          </p>
        </div>
      )}

      {message && <p className="mt-3 text-sm text-ok">{message}</p>}
      {error && <p className="mt-3 text-sm text-bad">{error}</p>}

      {mails && (
        <div className="mt-4">
          <p className="mb-2 text-xs text-ink3">
            {mails.length} matching email{mails.length === 1 ? "" : "s"} — nothing downloaded yet.
          </p>
          <ul className="flex flex-col gap-1.5">
            {mails.slice(0, 12).map((m) => (
              <li key={m.id} className="rounded-lg border border-line bg-surface2 px-3 py-2 text-sm">
                <p className="truncate font-medium">{m.subject || "(no subject)"}</p>
                <p className="mt-0.5 truncate text-xs text-ink3">
                  {m.from} · {m.attachments.join(", ") || "no PDF"}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
