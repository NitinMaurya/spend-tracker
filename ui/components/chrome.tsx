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
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[76rem] flex-wrap items-center gap-x-7 gap-y-3 px-6 py-3">
        <Link href={withScope("/")} className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid h-8 w-8 place-items-center rounded-[10px] bg-accent text-[14px] font-extrabold text-white"
          >
            S
          </span>
          <span className="text-[16px] font-extrabold tracking-[-.02em]">Spend Tracker</span>
        </Link>

        <nav aria-label="Main" className="flex items-center gap-1">
          {NAV.map((n) => {
            const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={withScope(n.href)}
                aria-current={active ? "page" : undefined}
                className={`rounded-full px-4 py-1.5 text-[14px] transition-colors ${
                  active
                    ? "bg-accentSoft font-bold text-accentInk"
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
            className={`inline-flex h-9 items-center gap-2 rounded-full border px-3.5 text-[13px] font-semibold transition-colors ${
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
