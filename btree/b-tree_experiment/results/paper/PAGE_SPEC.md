# Paper page spec (for the page-building agent)

Deliverable: ONE self-contained HTML file `results/paper/paper.html`, written in English in the register of a
systems workshop paper, rendered as a web page (not a PDF). It is published through the Artifact tool by the
session owner, so it must follow the Artifact page contract below exactly.

## Artifact page contract (hard rules)
- No `<!doctype>`, `<html>`, `<head>`, `<body>` tags. File starts with `<title>` (a short name, e.g.
  `Per-Level Differential Protection`), then `<link>` to Google Fonts, then one `<style>`, then content, then one `<script>`.
- External resources: stylesheets only from https://fonts.googleapis.com; no external scripts at all (draw charts
  with inline JS + inline SVG). No images from the network. No `alert/confirm/prompt`, no downloads, no print button.
- Theme tokens: every color is a CSS custom property defined on bare `:root` (light), redefined under
  `@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]) {... color-scheme:dark} }` and again under
  `:root[data-theme="dark"] {...}`. `body` sets `background: var(--bg); color: var(--fg)`. Never a literal color in a
  component rule. Chart text uses token colors.
- Responsive: works at 400 px width. 16 px side gutter set once on the outer wrapper (`padding-inline`, vertical
  padding via `padding-block`). Flex/grid children holding text or tables get `min-width:0`. Only tables, code and
  charts may be wider than the screen, each inside its own `overflow-x:auto` container. No horizontal page scroll.
- Everything visible at rest (no scroll-triggered reveals). `font-variant-numeric: tabular-nums` on numeric columns.
- Size < 500 KB. Embedded data as a compact inline JSON in the script.
- Figures: `<figure>` with a `<figcaption>`; every SVG has `role="img"` and an `aria-label`.

## Typography / look
- Serif body for paper feel: "Source Serif 4" (Google Fonts) with a real fallback stack; headings same family, 600;
  numbers/code in "IBM Plex Mono". Add "Noto Sans TC" only if any CJK text remains (it should not).
- Single reading column, max-width ~ 760 px for prose; figures may extend to ~ 920 px.
- Numbered sections (1, 1.1 …), numbered figures and tables with captions that state the claim.
- Cool-grey neutral palette biased toward the accent blue; no AI-template looks (no cream+terracotta, no gradient hero).

## Charts (dataviz rules)
- One y-axis per chart, never dual axes. Separate small charts for SDC and latency.
- Series colors are fixed per entity (never by rank) and identical across all charts:
  NONE `#e34948` (dark `#e66767`), SANITY `#2a78d6` (dark `#3987e5`), CTRL_CRC `#eb6834` (dark `#d95926`),
  FULL_CRC `#4a3aa7` (dark `#9085e9`). Policies reuse the same four slots in order BY_LEVEL, LRU, BY_HOTNESS, RANDOM
  (a legend names them). Extension arms (grid / adjacent / shift / hash) likewise take slots 1–4 in that order.
- Lines 2 px, markers ≥ 8 px with a 2 px surface-colored ring and a DIFFERENT shape per series (circle, square,
  triangle, diamond) so overlapping lines stay distinguishable; bars ≤ 24 px thick, rounded data end only.
- Legend always present for ≥ 2 series; direct end-labels when they do not collide. Axis ticks are clean numbers;
  log axes label powers (10⁻⁴ …). SDC = 0 cannot sit on a log axis: state "FULL_CRC: 0 in every run (not drawn)" in the caption.
- Hover: a crosshair + tooltip listing every series at that x (line charts); per-bar tooltip for bars. Keyboard focusable.
- Every chart has a table twin inside `<details><summary>Data</summary>…</details>`.
- Gridlines solid hairlines in a one-step-off-surface grey. No number on every point.
- Render and LOOK at the page once (headless chrome command below) at 1100 px and 400 px, fix collisions/overflow, re-render once.

## Headless chrome for checks
```
CH=$(ls -d ~/.cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-linux64/chrome-headless-shell | tail -1)
export LD_LIBRARY_PATH=/scratch/ff/libs/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH
"$CH" --no-sandbox --disable-gpu --hide-scrollbars --window-size=1100,12000 --virtual-time-budget=8000 --screenshot=out.png file:///abs/path/preview.html
```
(preview.html = your file wrapped in `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>…</body></html>`; crop the PNG with PIL and view pieces.)

## Content sources
- `results/SUMMARY_dbscale.md` §0–§15 (E1′, attribution §3, E3′, E4′, E2′, Ramulator2 §8, E5′ §10, E6a′ §11, E6b′ §12,
  E7′ §14, E2b′–E2e′ §15, observations §9/§13). Ignore §16–§18 entirely (not part of this paper).
- `results/paper/paper_data.json` and `results/paper/paper_tables.md` (cost & time tables, E7-extension rows) produced
  by the experiment agent — these are the numbers to plot; when SUMMARY and paper_data disagree, paper_data wins and
  the discrepancy is noted in a footnote.
- Figure 1 (leaf vs internal flip): reuse the inline SVG markup from `results/figures/btree_bitflip_overview.html`
  (take the English strings from its `data-en` attributes; drop the language toggle and the takeaway/legend text you don't need).
- Abstract: adapt `results/paper/ABSTRACT.txt`.

## Exclusions
- HDR_CRC and HDR_MIRROR appear NOWHERE (no rows, no series). The design section may say in one sentence that a
  header-only CRC covers <1 % of a dense page and was found ineffective, as the motivation for CTRL_CRC.
- No E8–E21 material except the three E7-extension arms (grid dummies, shift, hash mapping) that the experiment agent
  packages in paper_data.json as `E7ext`.

## Structure
Title · author placeholder line (`Author — Institution`) · Abstract
1 Introduction (problem; Figure 1; contributions as a short list)
2 Protection schemes and the reliable-memory model (Table 1: scheme, what it verifies, reliable memory per page,
  verification cost model; shadow store, budget and eviction policies BY_LEVEL / LRU / BY_HOTNESS / RANDOM; B_int)
3 Experimental method (simulator stack, fault injection models, workload, metrics incl. cost = reliable memory and
  pages, time = mean op latency; scale calibration; seeds and paired bootstrap; Ramulator2 replication in one paragraph)
4 Results — one subsection per experiment, each with: setup (one line), figure(s), a cost & time table, findings:
  4.1 E1 Error rate × scheme · 4.2 E2 Budget × policy (1M-key sweep + B_int-rescaled knee table) ·
  4.3 E3 Fault spatial structure · 4.4 E4 Verification frequency · 4.5 E5 DRAM capacity · 4.6 E6 Node density and scale
  (E6a + E6b) · 4.7 E7 Key sparsity (detection ratio vs (64−k)/64, blind-zone edge) ·
  4.8 Raising key density: grid dummies, shift, hash mapping — detection vs cost (pages, reliable memory) and time (latency)
5 Discussion (what follows for differential protection; limitations: accelerated λ, DRAM-only flips, single workload,
  frozen-clock scan affecting E5 ram_misses, NONE heavy tail, E3 confounds)
6 Conclusion
Appendix A: run counts and configurations per experiment (table).
