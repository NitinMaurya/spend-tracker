# Design

The finance dashboard, executed as the category's best rather than subverted.
Chosen by the user over a direction roll; the convention is the commitment.
Craft bar: Copilot Money and Monarch. Seed `db8fa467`.

## Ground rules

- **The engine computes, the interface displays.** No arithmetic on money in
  TypeScript. The count-up tween is display only: it seeds and rests on the exact
  server-formatted string and never determines a reported value.
- **Fixed order, set by the user.** The figure and the graphs lead, the cards sit
  below them, and the transaction table stays last as the deep detail. Urgency is
  not lost to the ordering: overdue cards raise an alert strip at the top of the
  page regardless of where the card grid sits.
- **No eyebrows.** Headings carry their own weight. `Label` exists only above a
  value inside a stat tile, in sentence case.

## Colour

Warm off-white ground in light, deep warm charcoal in dark. Never pure black or
white. One emerald accent carries every interactive affordance.

| Role | Light | Dark |
|---|---|---|
| bg / surface / surface-2 | `#fbfaf9` `#ffffff` `#f5f4f1` | `#131315` `#1b1b1e` `#232327` |
| line / hair | `#e7e5e0` `#efedea` | `#2e2e33` `#26262a` |
| ink / ink-2 / ink-3 | `#1a1a18` `#55534e` `#6b6862` | `#f2f1ee` `#a9a69f` `#8e8b84` |
| mute (hairlines and icons ONLY) | `#a8a49c` | `#605d58` |
| accent | `#0d7a55` | `#3ecf9a` |

`ink-3` at 5.1:1 is the lightest token allowed to carry text. `mute` is below AA
and never carries text.

### Category hues

Six slots, fixed order, assigned by slot and never by rank, so filtering a
category out never repaints the survivors. Warm and cool interleave because three
warm hues cannot sit adjacent without collapsing under deuteranopia.

| Slot | Light | Dark |
|---|---|---|
| c1 green | `#12805f` | `#1f9e74` |
| c2 orange | `#d4761f` | `#cf7a26` |
| c3 blue | `#3273d4` | `#4a86dc` |
| c4 red | `#c33a20` | `#c94a3a` |
| c5 purple | `#8258cc` | `#8b74d8` |
| c6 ochre | `#9a7a18` | `#b39023` |

Both sets pass lightness band, chroma floor, adjacent CVD separation, normal-vision
floor and surface contrast in their own mode. **There is no seventh hue**: beyond
six the tail folds into `mute`. Every slice and bar is direct-labelled, which is
the secondary encoding the CVD band requires.

`ok` / `warn` / `bad` mean state, never magnitude, and always ship colour plus a
glyph plus a word.

## Type

Manrope throughout, Geist Mono for evidence: statement lines, ids, parser
versions. No serif; it has no role in this world.

- `.figure` — the one big number. Weight 700, tracking -0.035em, **proportional**
  figures. Tabular digits give every glyph the width of a zero and read loose at
  display size.
- `.tnum` — tabular figures, only where numbers align vertically in columns.
- Page title `clamp(1.6rem, 2.6vw, 2.05rem)` at 800. Section 19px/700. Card 15px/700.
- Label 12.5px/500 in `ink-3`.

## Shape and depth

One radius per role: `10px` controls, `16px` cards, `20px` sheets, full pills for
chips and segmented controls. Two elevations only, both with offset plus soft
blur, tinted to the ground. Cards group related figures; never nested, never the
page's only structure.

## Motion

Present but disciplined. One authored reveal per screen, nothing loops.

- Exponential ease-out, `cubic-bezier(.16,1,.3,1)`. No overshoot or bounce.
- Hero figure counts up once. Trend path draws once. Donut arcs sweep once. Bars
  grow once, staggered 70ms.
- Hover and press respond instantly. Donut hover dims the other arcs by opacity
  alone; nothing animates a layout or paint property.
- Everything collapses under `prefers-reduced-motion`, including stroke dashes.

## Browser surfaces

Selection, caret, scrollbars, focus ring and underline offset are themed from the
palette rather than left at browser defaults.

## Charts

| Job | Form | Colour |
|---|---|---|
| Category share | Donut, direct-labelled, 2px surface gap between arcs | six slots + `mute` tail |
| Category ranking | Horizontal bars | six slots + `mute` tail |
| Trend over time | Area, single series, 2.25px line, soft vertical wash | accent |
| Ratio against a limit | Meter, track is a lighter step of the fill's own ramp | status |
| Card comparison | Grouped bars with legend | six slots |
| Income per month | Vertical bars, median rule, outlier month in `--c2` | accent + `--c2` |

Axis labels never round away from the gridline they sit on. Hit targets on the
trend span the full column, well past the 8px marker.

Reveals animate FROM a hidden keyframe TO the element's own resting value, with
`forwards` and no `to` block. This is not stylistic: a `to`-state that an
animation must reach in order for content to be visible renders blank whenever
the animation does not run, and CSS animations do not run on a hidden page. Two
chart keyframes were shipped with that defect and both drew nothing.

## Two axes, never one

A consolidated ledger naturally answers *did money enter or leave this account*.
That is a bookkeeping question, and it gets read as an economic one. They
disagree constantly, and the disagreement is not marginal: paying your own card
bill is money arriving on the card, a wire abroad is money leaving without
anything being bought, and drawing a loan is money arriving that you now owe.

So every row carries a **flow** as well as a sign:

| Flow | Means |
|---|---|
| `EARNED` | arrived from outside — yours to keep |
| `SPENT` | left for good, at a merchant or in fees |
| `MOVED` | between accounts you own, card bills included |
| `BORROWED` | arrived, but you owe it |
| `REPAID` | loan instalments |
| `REFUNDED` | earlier spending reversed |
| `NEUTRAL` | bookkeeping that nets to zero |
| `UNKNOWN` | money in the statement never named |

Two rules hold the model together. **No flow that should point one way carries
both directions** — a bucket holding credits and debits at once cannot be
reported as a single figure, because whichever side is shown hides the other.
Only `MOVED` and `NEUTRAL` carry both, since being the same money twice is what
they mean. And **the displayed magnitude is always the larger side**, never the
side implied by the label: borrowing posts as a debit on the card that created
the debt, so reading "money in" for it printed a confident 0.00 against a real
loan.

`flow` is derived, never stored, so it cannot drift from the type beneath it and
needs no backfill when the rules improve.

## Money in

Income is not drawn as the mirror of spending, because the two are not
symmetrical. Spending is known for every month a card statement was read; income
only for months a bank statement was read. Netting one against the other assumes
the windows match, so the comparison is drawn strictly over the overlap and the
months left out are named on the page.

No screen shows a "saved" or "left over" figure, and the engine does not compute
one. Only card spending can be subtracted, while rent, transfers and cheques
leave the current account without touching a card — so earnings minus card spend
is not money kept. It is the most flattering number this data can produce and the
least true, so the share is named for exactly what it measures instead.

A bonus month is marked, never smoothed: the bars scale to the tallest month, a
dashed rule marks the median, and the outlier takes `--c2` so it reads as
different in kind rather than merely taller. Median and mean are shown side by
side wherever they disagree.

## States

Every screen ships loading, empty, error and engine-down. One `State` component,
one copy source. Copy names the problem and the recovery.

The engine-down state is not a dead end. `EngineDownPanel` polls health every two
seconds and refreshes the route the moment the engine answers, so starting the
engine visibly resolves the page instead of leaving the reader to guess whether a
manual reload is needed. It is the only error a local-first tool routinely
produces, so it gets the only recovery path.
