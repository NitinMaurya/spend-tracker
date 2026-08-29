"use client";

/**
 * The engine is not answering.
 *
 * This used to be a dead end: the page rendered the command and waited for a
 * manual reload, so starting the engine looked like nothing had happened. It
 * now polls health and refreshes itself the moment the engine answers, which
 * is the whole recovery path for the one error a local-first tool actually
 * produces.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, Code } from "@/components/ui";
import { Check } from "@/components/icons";

const BASE = process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8787";
const CMD = "./run.sh";

export function EngineDownPanel() {
  const router = useRouter();
  const [waited, setWaited] = useState(0);
  const [back, setBack] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let alive = true;
    const id = window.setInterval(async () => {
      if (!alive) return;
      setWaited((n) => n + 1);
      try {
        const res = await fetch(`${BASE}/api/health`, { cache: "no-store" });
        if (!alive || !res.ok) return;
        setBack(true);
        window.setTimeout(() => router.refresh(), 400);
        window.clearInterval(id);
      } catch {
        /* still down; keep waiting */
      }
    }, 2000);
    return () => { alive = false; window.clearInterval(id); };
  }, [router]);

  return (
    <Card className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <span className="relative flex h-2.5 w-2.5 shrink-0" aria-hidden>
          <span className={`absolute inline-flex h-full w-full rounded-full ${back ? "bg-ok" : "bg-warn"}`} />
        </span>
        <p className="text-[15px] font-bold">
          {back ? "The engine is back. Reloading." : "Waiting for the engine"}
        </p>
        {back ? <Check size={16} className="text-ok" /> : null}
      </div>

      <p className="max-w-[66ch] text-sm leading-relaxed text-ink2">
        Start it from the project root. This page is watching, and reloads itself the
        moment it answers, so you will not need to refresh.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-grow"><Code>{CMD}</Code></div>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(CMD).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1600);
            });
          }}
          className="h-9 shrink-0 rounded-control border border-line bg-surface px-4 text-[13px] font-bold transition-colors hover:border-accent"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>

      <p className="text-[12.5px] text-ink3">
        {`${CMD} starts the engine and this interface together. `}
        To run only the engine: <span className="mono">.venv/bin/python -m analyser.api</span>
        {waited > 0 ? ` · checked ${waited} time${waited === 1 ? "" : "s"}` : ""}
      </p>
    </Card>
  );
}
