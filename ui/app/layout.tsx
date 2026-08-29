import type { Metadata } from "next";
import { Manrope, Geist_Mono } from "next/font/google";
import { Suspense } from "react";
import { CategorySheetProvider } from "@/components/category-sheet-provider";
import { EvidenceProvider } from "@/components/evidence-drawer";
import { CardDrawerProvider } from "@/components/card-drawer";
import { Chrome } from "@/components/chrome";
import { api } from "@/lib/api";
import "./globals.css";

const ui = Manrope({ subsets: ["latin"], variable: "--font-ui" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" });

const DIRECTION_CONTRACT = `<!--
THESIS: The finance dashboard done as the category's best, not subverted. It
refuses the audit-document reading the roll offered: the figure leads, and the
evidence sits one click behind it.
OWN-WORLD: Warm off-white ground, deep warm charcoal in dark. One emerald
accent. Six CVD-validated category hues on fixed slots. Manrope throughout,
Geist Mono for evidence. 16px cards, tinted offset shadows, no eyebrows.
STORY: See the period's shape at a glance, trust it because every figure opens
its source, then act on what is due or what to route.
FIRST VIEWPORT: Scope rail on top. Left, the period total counting up with its
delta and sparkline. Right, the category donut, direct-labelled. Due cards
lead instead whenever something is overdue or due inside a week.
FORM: Category canon, the standing exit, chosen by the user over the roll;
seed db8fa467.
FINISH: unreviewed and undocumented is unfinished; this build ends with the
finish review, the verdict, DESIGN.md, and every shipping raster carrying its
provenance.
-->`;

export const metadata: Metadata = {
  title: "Spend Tracker",
  description: "Where your money goes, and which card it belongs on.",
};

async function fixupCount(): Promise<number | null> {
  try {
    return (await api.review()).length;
  } catch {
    return null;
  }
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const fixups = await fixupCount();
  return (
    <html lang="en">
      <body className={`${ui.variable} ${mono.variable} min-h-screen`}>
        <div style={{ display: "none" }} aria-hidden
             dangerouslySetInnerHTML={{ __html: DIRECTION_CONTRACT }} />
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-control focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:shadow-sheet"
        >
          Skip to content
        </a>
        <Suspense fallback={<div className="h-16 border-b border-line" />}>
          <Chrome fixups={fixups} />
        </Suspense>
        <Suspense fallback={null}>
          <CategorySheetProvider>
            <EvidenceProvider>
              <CardDrawerProvider>{children}</CardDrawerProvider>
            </EvidenceProvider>
          </CategorySheetProvider>
        </Suspense>
      </body>
    </html>
  );
}
