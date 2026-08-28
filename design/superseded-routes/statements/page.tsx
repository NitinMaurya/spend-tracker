/**
 * Statements — organised by bank, because that is the unit everything else uses:
 * passwords, parsers and accounts are all per-issuer (D-036). A flat file list made
 * the reader do that grouping in their head.
 *
 * Three things happen here, in order: get statements in (email or drop), unlock the
 * banks that need a password, read them. Nothing is read until Process is pressed.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiDown, api, processStatements, saveStatementPassword, uploadStatements,
  type Library, type LibraryBank, type LibraryFile, type ProcessResult,
} from "@/lib/api";
import { Chip, Empty, H1 } from "@/components/ui";
import { GmailPanel } from "@/components/gmail-panel";

export default function StatementsPage() {
  const [lib, setLib] = useState<Library | null>(null);
  const [down, setDown] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState<null | "upload" | "process">(null);
  const [results, setResults] = useState<ProcessResult[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try { setLib(await api.library()); }
    catch (e) { if (e instanceof ApiDown) setDown(true); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const addFiles = useCallback(async (files: File[]) => {
    const pdfs = files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!pdfs.length) { setNotice("Those weren't PDFs."); return; }
    setBusy("upload"); setNotice(null);
    try {
      const r = await uploadStatements(pdfs);
      setNotice(`Added ${r.saved.length}. Press Read statements when you're ready.`);
      await refresh();
    } finally { setBusy(null); }
  }, [refresh]);

  const run = useCallback(async () => {
    setBusy("process"); setResults(null); setNotice(null);
    try {
      const r = await processStatements();
      setResults(r.results);
      await refresh();
    } finally { setBusy(null); }
  }, [refresh]);

  if (down) {
    return (
      <>
        <H1>Statements</H1>
        <Empty title="The analyser isn’t running">
          Start it with <code className="mono">.venv/bin/python -m analyser.api</code>
        </Empty>
      </>
    );
  }
  if (!lib) return <p className="text-sm text-ink3">Loading…</p>;

  const t = lib.totals;
  const todo = t.pending + t.rejected;

  return (
    <>
      <H1 sub="Your statements, grouped by bank. Add them from email or drag them in — nothing is read until you say so.">
        Statements
      </H1>

      {/* Summary ─────────────────────────────────────────────── */}
      <section className="rise mb-6 grid gap-3 sm:grid-cols-4">
        <Metric label="Statements" value={t.files} />
        <Metric label="Read" value={t.read} tone="ok" />
        <Metric label="Transactions" value={t.transactions} />
        <Metric label="Need attention" value={todo} tone={todo ? "warn" : "ok"} />
      </section>

      {/* Add ─────────────────────────────────────────────────── */}
      <GmailPanel onDownloaded={() => void refresh()} />

      <section
        className="rise mb-6"
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); void addFiles(Array.from(e.dataTransfer.files)); }}
      >
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-card border border-line bg-card p-5 shadow-card">
          <div className="min-w-0">
            <p className="font-medium">{todo > 0 ? `${todo} statement${todo > 1 ? "s" : ""} still to read` : "Everything has been read"}</p>
            <p className="mt-0.5 max-w-[58ch] text-sm text-ink2">
              Reading checks each statement adds up to the totals your bank printed. If it
              doesn’t, it’s set aside rather than folded quietly into your numbers.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => inputRef.current?.click()} disabled={busy !== null}
              className={`rounded-xl border px-4 py-2.5 text-sm font-medium disabled:opacity-45 ${dragging ? "border-[var(--accent)] bg-accentSoft text-accent" : "border-line bg-card2"}`}>
              {busy === "upload" ? "Adding…" : dragging ? "Drop to add" : "Add files"}
            </button>
            <button type="button" onClick={() => void run()} disabled={busy !== null || t.files === 0}
              className="rounded-xl px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-45"
              style={{ background: "linear-gradient(135deg,var(--accent),var(--accent-2))" }}>
              {busy === "process" ? "Reading…" : "Read statements"}
            </button>
          </div>
        </div>
        <input ref={inputRef} type="file" accept="application/pdf,.pdf" multiple hidden
               onChange={(e) => { void addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
      </section>

      {notice && <p className="mb-6 rounded-card border border-line bg-accentSoft px-4 py-3 text-sm text-accentInk">{notice}</p>}

      {results && (
        <section className="rise mb-6 rounded-card border border-line bg-card p-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink3">Last read</p>
          <p className="text-sm text-ink2">
            {results.filter((r) => r.status === "RECONCILED").length} read ·{" "}
            {results.filter((r) => r.status === "UNCHANGED").length} already known ·{" "}
            {results.filter((r) => !["RECONCILED", "UNCHANGED"].includes(r.status)).length} need attention
          </p>
        </section>
      )}

      {/* Banks ───────────────────────────────────────────────── */}
      <div className="flex flex-col gap-3">
        {lib.banks.map((b, i) => (
          <BankCard key={b.issuer_id} bank={b} delay={i * 40} onChanged={() => void refresh()} />
        ))}
      </div>

      <p className="mt-6 text-xs text-ink3">
        Stored in <code className="mono">{lib.directory}</code> — on this machine only.
      </p>
    </>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: "ok" | "warn" }) {
  const colour = tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--warn)" : "var(--ink)";
  return (
    <div className="rounded-card border border-line bg-card px-4 py-3.5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink3">{label}</p>
      <p className="tnum display mt-1 text-2xl font-semibold" style={{ color: colour }}>{value}</p>
    </div>
  );
}

function BankCard({ bank, delay, onChanged }: { bank: LibraryBank; delay: number; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const needsAttention = bank.pending > 0 || bank.rejected > 0;

  return (
    <section className="rise rounded-card border border-line bg-card shadow-card" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3 p-5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="display text-base font-semibold">{bank.name}</h2>
            {!bank.has_parser && <Chip tone="warn">no reader yet</Chip>}
            {bank.rejected > 0 && <Chip tone="bad">{bank.rejected} set aside</Chip>}
          </div>
          <p className="tnum mt-1 text-sm text-ink2">
            {bank.read} of {bank.total} read
            {bank.transactions > 0 && ` · ${bank.transactions} transactions`}
          </p>
        </div>

        <PasswordControl bank={bank} editing={editing} setEditing={setEditing} onChanged={onChanged} />

        <button type="button" onClick={() => setOpen((v) => !v)}
          className="rounded-lg border border-line px-3 py-2 text-xs font-medium text-ink2">
          {open ? "Hide" : `${bank.total} file${bank.total > 1 ? "s" : ""}`}
        </button>
      </div>

      {bank.rejected > 0 && (
        <p className="border-t border-line px-5 py-3 text-sm text-ink2">
          <span className="font-medium text-ink">
            {bank.rejected} statement{bank.rejected > 1 ? "s were" : " was"} set aside.
          </span>{" "}
          Every statement prints its own totals. We add up the transactions we extracted
          and compare. When the two disagree, the extraction is provably wrong — a row was
          missed, or something was read that isn’t a transaction — so those figures are
          kept out of your numbers rather than quietly folded in. Open the files below to
          see the exact difference.
        </p>
      )}

      {!bank.has_parser && (
        <p className="border-t border-line px-5 py-3 text-sm text-ink2">
          Nobody has written a reader for {bank.name} statements yet, so these{" "}
          {bank.total} files sit unread. Readers are written per bank format — the layout
          is never guessed at, because a wrong guess produces plausible but wrong money.
        </p>
      )}

      {open && (
        <ul className="border-t border-line">
          {bank.files.map((f) => <FileRow key={f.file_name} file={f} />)}
        </ul>
      )}
    </section>
  );
}

function PasswordControl({
  bank, editing, setEditing, onChanged,
}: {
  bank: LibraryBank; editing: boolean; setEditing: (v: boolean) => void; onChanged: () => void;
}) {
  const [value, setValue] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value) return;
    setState("saving"); setError(null);
    try {
      await saveStatementPassword(value, bank.issuer_id);
      setValue(""); setState("idle"); setEditing(false); onChanged();
    } catch (err) {
      setState("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  // Nothing encrypted and no password on file: there is simply nothing to say.
  if (!bank.has_password && bank.locked === 0) return null;

  if (bank.has_password && !editing) {
    return (
      <div className="flex items-center gap-2">
        <Chip tone={bank.locked > 0 ? "warn" : "ok"}>
          {bank.locked > 0 ? "password doesn’t fit" : "password saved"}
        </Chip>
        <button type="button" onClick={() => setEditing(true)}
          className="rounded-lg border border-line px-3 py-2 text-xs font-medium text-ink2">
          Change
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
      <input type="password" value={value} onChange={(e) => { setValue(e.target.value); setState("idle"); }}
        placeholder={`${bank.name} password`} autoComplete="off"
        className="w-[15rem] rounded-lg border px-3 py-2 text-sm"
        style={{ borderColor: state === "error" ? "var(--bad)" : "var(--line)", background: "var(--bg)" }} />
      <button type="submit" disabled={state === "saving" || !value}
        className="rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-45"
        style={{ background: "linear-gradient(135deg,var(--accent),var(--accent-2))" }}>
        {state === "saving" ? "Checking…" : bank.has_password ? "Replace" : "Unlock"}
      </button>
      {bank.has_password && (
        <button type="button" onClick={() => { setEditing(false); setError(null); }}
          className="text-xs text-ink3">Cancel</button>
      )}
      {error && <p className="w-full text-sm font-medium" style={{ color: "var(--bad)" }}>{error}</p>}
    </form>
  );
}

function FileRow({ file }: { file: LibraryFile }) {
  const tone = file.status === "RECONCILED" ? "ok" : file.status === "REJECTED" ? "bad" : file.locked ? "warn" : "neutral";
  const label = file.status === "RECONCILED" ? "read" : file.status === "REJECTED" ? "set aside" : file.locked ? "locked" : "not read";
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line2 px-5 py-2.5 last:border-0">
      <Chip tone={tone}>{label}</Chip>
      <span className="mono min-w-0 flex-1 truncate text-xs text-ink2">{file.file_name}</span>
      {file.statement_date && <span className="tnum text-xs text-ink3">{file.statement_date}</span>}
      {typeof file.txns === "number" && file.txns > 0 && (
        <span className="tnum text-xs text-ink3">{file.txns} txns</span>
      )}
      {file.reject_reason && <p className="w-full text-xs" style={{ color: "var(--bad)" }}>{file.reject_reason}</p>}
    </li>
  );
}
