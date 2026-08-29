# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primarily the author: one person reading their own UAE credit-card statements, fluent
in the domain. Confirmed intent to release publicly / open source, so a second audience
is real: a stranger who clones the repo and points it at their own statements. That
stranger has no due dates, no confirmed wallet, and no UAE-banking context, but does
have PDFs to make sense of. Empty and first-run states carry the teaching.

## Stack

Existing, not up for decision. Next.js 16 App Router with React Server Components,
Tailwind v4, TypeScript. A local Python FastAPI engine on 127.0.0.1:8787 over SQLite.
Nothing is deployed; nothing leaves the machine.

## Product Purpose

Read your own credit-card statements locally, establish where the money actually goes,
and decide which card each kind of spending belongs on. Success is a routing decision
the user trusts enough to act on, produced from figures they can trace back to the
printed page they came from.

## Positioning

The engine refuses to guess, and that refusal is the product. A reward rate is used
only when it was quoted verbatim in a Key Facts Statement AND a human has confirmed
which categories that sentence covers. Extracted transactions are summed and compared
against the totals the issuer printed; when they disagree the statement is set aside
rather than folded quietly into the numbers. A neighbouring product that estimates,
infers a category mapping, or silently averages cannot truthfully make this claim.

## Operating Context

Used in a deliberate weekly or monthly sit-down, after statements land: read the new
PDFs in, fix any categories the engine could not place, then look at the period. Not a
daily glance, though payment urgency can make it one.

Statements arrive by Gmail fetch or drag-and-drop, per issuer. Issuers on record:
Emirates NBD, Mashreq, FAB, CBD, Emirates Islamic, Dubai First, Wio. PDF passwords live
in the macOS Keychain keyed by issuer, never in a file, an environment variable, a log
line, or an API response. Category corrections are written to data/category_overrides.csv
so the same fix is never made twice. The confirmed wallet lives in data/wallet.json.

## Capabilities and Constraints

- Parsers are written per bank format and never guessed at; an unrecognised issuer says
  so rather than producing plausible but wrong money.
- Money crosses the wire as minor units plus the currency's own exponent. No arithmetic
  on money happens in TypeScript; the interface only ever displays what the engine
  returned. Dividing by 100 is correct for AED and silently wrong for KWD and JPY.
- Reconciliation is a gate. RECONCILED, PARSED and REJECTED are distinct states and the
  difference is user-visible.
- Every transaction retains its source: document, page, the verbatim printed line, the
  parser name and version, and whether that document reconciled.
- A routing plan requires a human-confirmed wallet. Rate extraction reads a rate and the
  sentence it came from but will not decide which categories that sentence covers.
- Readiness gates are weighted by value, not by row count: uncategorised spend must stay
  at or below 10% by value, and coverage needs at least six months.
- Spending excludes transfers between the user's own accounts, accounts flagged out of
  spending, and reimbursables.
- Three jobs are all first-class, confirmed by the user: what is due, where the money
  went, and which card to use. Hierarchy is resolved by data state rather than fixed
  layout: urgency outranks analysis when something is overdue or imminent; otherwise the
  analytical view leads; the plan is promoted when it becomes actionable.

## Brand Commitments

Named Spend Tracker. Voice is plain, specific and unhedged: it states what a figure is
and where it came from, and says plainly when it does not know. It never uses marketing
language about money.

Standing visual preference, chosen by the user over a direction round and binding on
future work: this is a finance dashboard in the mainstream sense, with graphs, large
numbers and animation. The category convention is the commitment, executed at full
fidelity rather than subverted. The craft bar is Copilot Money and Monarch: large
animated figures, category colour, generous whitespace, rounded surfaces, precise
typography. Motion is present but disciplined, one reveal per screen, crossfade on
scope change, instant hover feedback, nothing looping.

## Evidence on Hand

- Real statements and a populated SQLite database exist locally at data/ and are
  deliberately not committed.
- 302 passing tests, 2 skipped. Golden parser evals assert against local statements and
  are excluded from the repository.
- Public repository at github.com/NitinMaurya/spend-tracker.
- No customers, no benchmarks, no testimonials, no pricing. Future work must not invent
  any.

## Product Principles

1. Evidence over inference. A figure that cannot be traced to a printed line does not
   get shown.
2. Refusing is a feature. Where a rule cannot be evaluated, hold the spend out of the
   result rather than assume in the card's favour.
3. The engine computes, the interface displays. No money arithmetic in the client.
4. Uncertainty is rendered, not hidden. Readiness, coverage, conflicts and reconciliation
   status are visible objects, not footnotes.
5. Local by construction. Nothing leaves the machine, and the interface says so.

## Accessibility & Inclusion

WCAG AA is the established floor and was enforced this session: the muted text token was
raised to 4.9:1 after shipping at 3.2:1, and a separate lighter token exists for hairlines
and icons only. The categorical chart palette is validated for colour-vision deficiency
in both light and dark modes and is capped at the three slots that pass all-pairs; status
always ships colour plus a glyph plus a word. Reduced-motion is honoured.
