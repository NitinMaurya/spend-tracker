# Design

The finance dashboard, executed as the category's best rather than subverted.
Chosen by the user over a direction roll; the convention is the commitment.
Craft bar: Copilot Money and Monarch. Seed `db8fa467`.

## Ground rules

- **The engine computes, the interface displays.** No arithmetic on money in
  TypeScript. The count-up tween is display only: it seeds and rests on the exact
  server-formatted string and never determines a reported value.
- **Hierarchy is decided by data state, not layout.** Anything overdue or due
  within a week outranks analysis. Absent that, spending leads, which is also
  what a stranger cloning the repo will see.
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

Axis labels never round away from the gridline they sit on. Hit targets on the
trend span the full column, well past the 8px marker.

## States

Every screen ships loading, empty, error and engine-down. One `State` component,
one copy source. Copy names the problem and the recovery.
