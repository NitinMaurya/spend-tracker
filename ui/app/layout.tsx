import type { Metadata } from "next";
import { Instrument_Serif, Instrument_Sans, Geist_Mono } from "next/font/google";
import { Suspense } from "react";
import { CategorySheetProvider } from "@/components/category-sheet-provider";
import { Chrome } from "@/components/chrome";
import { EvidenceProvider } from "@/components/evidence-drawer";
import { CardDrawerProvider } from "@/components/card-drawer";
import { api } from "@/lib/api";
import "./globals.css";

/**
 * Three faces, three jobs. The serif carries the voice (titles), the sans
 * carries the data (every figure, including the hero — a display face on a
 * hero number reads as decoration), the mono carries the evidence.
 */
const serif = Instrument_Serif({ subsets: ["latin"], weight: "400", variable: "--font-serif" });
const ui = Instrument_Sans({ subsets: ["latin"], variable: "--font-ui" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Spend Tracker — where your money goes",
  description: "Track where your money goes, and find out which card is worth using.",
};

/** The badge is a count, not a tab: a chore gets surfaced by number. */
async function fixupCount(): Promise<number | null> {
  try {
    const rows = await api.review();
    return rows.length;
  } catch {
    return null;
  }
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const fixups = await fixupCount();
  return (
    <html lang="en">
      <body className={`${serif.variable} ${ui.variable} ${mono.variable} min-h-screen`}>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-control focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:shadow-sheet"
        >
          Skip to content
        </a>
        <Suspense fallback={<div className="h-[57px] border-b border-line" />}>
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
