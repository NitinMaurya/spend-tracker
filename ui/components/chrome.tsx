"use client";

/**
 * The app chrome: two destinations and a utility.
 *
 * Money and Plan are the only questions the product answers. Data is
 * maintenance, so it is right-aligned and carries a count instead of a tab.
 *
 * Nav links CARRY THE SCOPE. Losing the selected period on every navigation
 * was the single most disorienting thing about the old six-tab layout.
 */

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Doc, Lock } from "./icons";

const NAV = [
  { href: "/", label: "Money" },
  { href: "/plan", label: "Plan" },
];

export function Chrome({ fixups }: { fixups: number | null }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const query = params.toString();
  const withScope = (href: string) => (query ? `${href}?${query}` : href);
  const onData = pathname.startsWith("/data");

  return (
    <header className="border-b border-line bg-bg">
      <div className="mx-auto flex max-w-[70rem] flex-wrap items-center gap-x-8 gap-y-3 px-6 py-3.5">
        <Link href={withScope("/")} className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid h-[26px] w-[26px] place-items-center rounded-[7px] bg-accent text-[13px] font-semibold text-white"
          >
            L
          </span>
          <span className="serif text-[19px]">Ledger</span>
        </Link>

        <nav aria-label="Main" className="flex items-center gap-1">
          {NAV.map((n) => {
            const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={withScope(n.href)}
                aria-current={active ? "page" : undefined}
                className={`rounded-control px-3.5 py-1.5 text-sm transition-colors ${
                  active
                    ? "bg-accentSoft font-semibold text-accentInk"
                    : "font-medium text-ink2 hover:text-ink"
                }`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3.5">
          <Link
            href="/data"
            aria-current={onData ? "page" : undefined}
            className={`inline-flex h-8 items-center gap-2 rounded-control border px-2.5 text-[12.5px] font-medium transition-colors ${
              onData
                ? "border-transparent bg-accentSoft text-accentInk"
                : "border-line bg-surface text-ink2 hover:text-ink"
            }`}
          >
            <Doc />
            Data
            {fixups ? (
              <span className="tnum inline-grid h-[18px] min-w-[19px] place-items-center rounded-full bg-warnSoft px-1.5 text-[11px] font-semibold text-warn">
                {fixups}
              </span>
            ) : null}
          </Link>
          <span className="hidden items-center gap-1.5 text-xs text-ink3 sm:flex">
            <Lock size={13} className="text-ok" />
            on this machine only
          </span>
        </div>
      </div>
    </header>
  );
}
