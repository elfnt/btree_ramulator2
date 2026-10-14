# E17–E20: SANITY-only extensions (range / align / slack dummies / all together)

Raw data: `e17_dbscale.csv` (132 rows), `e18` (15), `e19` (40), `e20` (30). Each has 361 columns: the 348 old ones plus 13 appended (`sanity_range, sanity_align_log2, slack_guard, n_range_alarms, n_range_parent_bad, n_range_child_bad, n_range_restarts, n_range_giveups, n_range_anc_recoveries, slack_real_keys, slack_dummies, frac_guard_right, frac_guard_left`).
Scripts: `scripts/run_e17_db.sh … run_e20_db.sh`, `e17_20_common.sh` (16 jobs), `analyze_e17_e20.py`. The full tables are in `dbscale/e17_e20_tables.md`.
No CRC scheme was run. Baselines come from existing rows: NONE from e12 (stride) and e8 (random64); SANITY from e10/e8; internal- and leaf-only from e11 (3 seeds, no random64); order 16 from e9.
The "leaf det. ratio" is the E13 method: SANITY-arm `n_keyflip_real_tp` ÷ CTRL_CRC `n_keyflip_real_tp` per run. Existing e13 CTRL_CRC guard=none rows are used **only as the event-count denominator**. No k0 or k16-base value is available because those older CSVs lack the columns.

## Config, checks
- order 253, 1M keys, 30 000 ops, ssd_blocks 512, rpb 2048, EVERY_READ, `bin/exp_fast.exe`, seeds 1–5. λ = 3e-3 (internal-only: 0.15, as in E11). Order-16 check: E9 geometry (200k keys, ssd_blocks 2048, rpb 8192), seeds 1–3.
- **Regression** (all new flags at defaults, stride 0, NONE/SANITY × 5): `regcheck.py` reports 0 of 10 rows differing (194 cols).
- **Reproduction**: all 44 E17 `sanity_range=0` rows that have an existing counterpart (e10/e8/e11/e9) match it on every shared column.
- Pages and height are identical to the seed-matched SANITY baseline in 125/125 E17-all, E18, E19 and E20 rows. As intended, slack dummies do not change the logical tree.
- Self-tests (abort on failure) run at startup:
  - range (r1–r4): clean parent and child pass; a child pointer redirected to another leaf or to an internal page is caught; every harmful single-bit separator flip that passes SANITY is caught when the affected child is visited (an upward flip only at the right child); internal-child bounds inherit correctly.
  - slack (s1–s5): encode→strip round-trips; full node gets 0 dummies; n_dummies = min(free, cand.); a real key flipped across its own dummy is caught; consecutive keys skip colliding dummies; with align, a real-key low-bit flip and a dummy value flip are both caught.
  - End to end (every run with any new flag): the clean 1M-key prefill must raise **zero** alarms (any alarm aborts the run). 2 000 sampled searches must return the correct value with no alarm. Under slack, real keys after prefill must equal 1M.
- LEVELCHK: 32/217 runs report `walk_ok=0`, all in E17 internal-only, at about the same rate with range on or off. The cause is the oracle walk hitting poisoned internal nodes (see E17). The per-level counts come from allocation counters and are fine.

## Implementation notes (choices you may want to change)
- **Range bounds are inherited.** A child's [lo,hi) comes from the parent's separators, or from the ancestor's bound when the child is leftmost or rightmost. Checked invariants:
  - leaf: if lo is bounded, first real key == lo; last real key < hi.
  - internal: first key > lo (strict); last key < hi.
  - The node_type must match the expected level.
  - I confirmed from the code that leaf split copies `right.keys[0]` up, internal split pushes `keys[mid]` up, and nothing deletes. The 1M-insert prefill raising zero alarms is the empirical check.
- **On a range violation**: the child is recovered inside `GuardedRAM::read` (it counts as a detected read; if the child is clean it shows up as `fp`). The direct parent and the ancestors that supplied lo/hi are re-read from SSD at t_ssd+t_mem each and counted in `n_recoveries`. The descent then restarts from the root, at most 2 times per op. A third alarm counts as a give-up: the op is already "detected", and the range check is turned off for the rest of the op. Comparison cost is charged as 0.
- **Align**: a real key's low k bits must be 0. Under slack, an entry with value == 6 is a dummy and its low bits must be 1 or all-ones.
- **Slack**: dummies are added in `write_node` and stripped in `read_node`. `walk_level_counts` never parses leaf entries, so it needed no change. With fewer free slots than candidates, the selection is `cand[floor(j·m/free)]`. Under `both`, candidates are interleaved K−1/K+1, so each covered key mostly gets one side (see frac columns).

## E17 — range check (all-level λ 3e-3; undetected wrong/run mean / median; missing; value; lat µs; recoveries; leaf det.)
| keys | NONE | SANITY | SANITY+range | range alarms/run (parent bad / child bad / giveups) | det. ratio S → S+r (model .497→.503 @2^32, .333→.338 r64) |
|---|---|---|---|---|---|
| k0  | 2737 / 1916 | 19.4/19; 2.0; 17.4; 15.13; 1712 | 17.0/18; **0.0**; 17.0; 15.19; 1737 | 12.6 (4.2 / 11.0 / 0) | — |
| k16 | 1184 / 1100 | 24.0/23; 6.6; 17.4; 14.06; 1303 | 21.2/21; 4.2; 17.0; 14.14; 1465 | 80.4 (6.0 / 10.4 / 22.4) | 0.722 → 0.728 |
| k32 | 656 / 808 | 28.6/28; 10.2; 18.4; 12.97; 889 | 26.0/26; 7.8; 18.2; 13.06; 1149 | 129 (8.4 / 10.0 / 38.2) | 0.468 → 0.473 |
| r64 | 98.8 / 117 | 33.6/33; 14.8; 18.8; 12.20; 590 | 30.6/30; 12.0; 18.6; 12.30; 852 | 131 (10.4 / 10.4 / 38.2) | 0.298 → 0.302 |

`n_poisoned_writes` (means): S 1398–1877 → S+r 1326–1553. Phantom = 0 everywhere.

**Single-level injection.** Undetected wrong answers per run, median of 5 (the 5 seeds in brackets); per 1000 flips in parentheses. Internal-only has 1 460 flips/run, leaf-only 5 166.
| level | keys | NONE e11 (/1000 fl) | SANITY rerun | SANITY+range | S+r total wrong (median) | lat µs S → S+r | recoveries S → S+r |
|---|---|---|---|---|---|---|---|
| internal | k0  | 12 860/1000 | 23 [28,23,19,14,**616**] (95.9) | **0** [1,3,0,0,0] (0.55) | 3 | 13.29 → 13.61 | 800 → 3 506 |
| internal | k16 | 10 450 | 23 [23,21,37,22,**621**] (99.2) | **1** [1,1,1,2,2] (0.96) | 5 | 12.91 → 13.43 | 686 → 4 807 |
| internal | k32 | 7 427 | 26 [21,24,26,32,**623**] (99.5) | **1** [0,1,1,5,0] (0.96) | 6 | 12.54 → 13.31 | 576 → 7 213 |
| internal | r64 | — | 32 [32,35,29,29,**773**] (123) | **0** [0,0,1,6,0] (0.96) | 5 | 12.26 → 13.32 | 493 → 7 580 |
| leaf | k0  | 9.6 | 21 (4.06) | 20 (3.99) | 20 | 15.04 → 15.08 | 1 696 → 1 710 |
| leaf | k16 | 9.5 | 28 (5.46) | 28 (5.38) | 28 | 13.94 → 13.98 | 1 283 → 1 297 |
| leaf | k32 | 9.9 | 36 (6.54) | 36 (6.50) | 36 | 12.90 → 12.93 | 873 → 885 |
| leaf | r64 | — | 38 (7.70) | 37 (7.63) | 37 | 12.15 → 12.20 | 580 → 595 |

The e11 SANITY rate per 1000 flips (3 seeds) is 15.9–18.4. My 5-seed means are higher only because **seed 5 is catastrophic under plain SANITY in every key set** (≈620–770 undetected, ~32k final integrity errors). Seeds 1–3 equal e11 exactly.
Internal-only alarm load with range: 1 351–3 542 alarms/run, of which only 35–107 had a corrupt parent and 1–3 a corrupt child at alarm time. Give-ups: 439–1 147/run.

**Order 16, 200k keys** (3 seeds; undetected mean/median; missing; lat µs):
- k0: NONE 369/315 → SANITY 38.3/39 (12.3 missing; 15.66) → **+range 26.0/25 (0.3 missing; 15.81)**.
- k16: NONE 257/266 → SANITY 44.7/40 (18.3; 15.49) → **+range 31.0/33 (5.0; 15.66)**.

## E18 — alignment (`--sanity_align_log2 = stride`)
| keys | NONE | SANITY | SANITY+align | det. ratio (model +align) |
|---|---|---|---|---|
| k8  | 1468 / 1361 | 25.0/23; miss 7.6; val 17.4; 14.57 µs; rec 1 499 | 22.8/19; miss 5.6; val 17.2; 15.14 µs; rec 1 714 | 0.849 → **0.992** (n.a.) |
| k16 | 1184 / 1100 | 24.0/23; 6.6; 17.4; 14.06; 1 303 | 19.6/19; **2.4**; 17.2; 15.14; 1 716 | 0.722 → **0.994** (0.996) |
| k32 | 656 / 808 | 28.6/28; 10.2; 18.4; 12.97; 889 | 19.2/19; **2.2**; 17.0; 15.15; 1 718 | 0.468 → **0.996** (0.997) |

Poisoned writes: k8 and k16 unchanged (1 868); k32 1 877 → 1 398.

## E19 — slack dummies (SANITY; pages identical, 5 763 mean)
| keys | SANITY | slack right | slack both | frac right/left (R; B) | det. ratio S → R / B (model +slack) |
|---|---|---|---|---|---|
| k8  | 25.0/23; miss 7.6; 14.57 µs | 24.8/23; 7.2; 16.31 | 25.4/25; 7.8; 16.18 | .445/0; .218/.227 | 0.849 → 0.926 / 0.900 (n.a.) |
| k16 | 24.0/23; 6.6; 14.06 | 23.0/22; 5.0; 15.82 | 25.4/25; 6.8; 15.57 | same | 0.722 → 0.844 / 0.791 (0.859) |
| k32 | 28.6/28; 10.2; 12.97 | 26.4/28; 8.0; 14.76 | 29.2/31; 10.2; 14.29 | same | 0.468 → 0.692 / 0.581 (0.724) |
| r64 | 33.6/33; 14.8; 12.20 | 32.0/33; 12.4; 14.05 | 33.2/35; 13.0; 14.04 | same | 0.298 → 0.442 / 0.445 (0.485) |

Recoveries rise from 590–1 499 to 1 330–2 200 per run, because flipped dummies are now detected and reloaded. Value SDC is unchanged (17.6–20.2).

## E20 — the free package (undetected mean/median; missing; value; poisoned writes; lat µs; recoveries)
| keys | SANITY | range + slack(R) | range + slack(R) + align |
|---|---|---|---|
| k0  | 19.4/19; 2.0; 17.4; 1398; 15.13; 1712 | 17.8/18; **0.0**; 17.8; 1398; 15.20; 1745 | — |
| k16 | 24.0/23; 6.6; 17.4; 1868; 14.06; 1303 | 20.6/22; 2.6; 18.0; 1525; 15.87; 2170 | **15.2/17; 0.0; 15.2**; 1526; 18.53; 3195 |
| k32 | 28.6/28; 10.2; 18.4; 1877; 12.97; 889 | 24.0/26; 5.6; 18.4; 1644; 14.83; 1867 | **15.2/17; 0.0; 15.2**; 1398; 18.52; 3059 |
| r64 | 33.6/33; 14.8; 18.8; 1877; 12.20; 590 | 29.4/30; 9.8; 19.6; 1417; 14.13; 1587 | n.a. |

Det. ratio: k16 0.849 / 1.056, k32 0.694 / 1.056, r64 0.445. Values above 1 mean saturation: the CTRL_CRC event denominator is itself a noisy count (±~5 %). In the +align arm, every single-bit real-key flip was detected.

## Measured vs interpretation
**Measured**
- Leaf detection matched the model within 0–4 pp:
  - range +0.004–0.006 (model +0.005);
  - align 0.992–0.996 (model 0.996–0.997);
  - slack right 0.844 / 0.692 / 0.442 (model 0.859 / 0.724 / 0.485).
  The 1.5–4 pp shortfall is the same leaf-boundary offset seen in E8 and E13.
- Internal-only injection, range on: median undetected falls from 23–32/run to 0–1/run (≈20–30×). It is **not 0**: 0.55–0.96 per 1000 flips undetected and 2.6–3.7 total wrong. The model predicted 0.
- In the durable oracle (= SSD), 7–10 internal nodes violate the range invariant at the end of an internal-only run, **with range off as well** (stderr `RANGECHK`, seeds 1–2, k32). At all-level λ 3e-3 the count is 0.
- Missing SDC: range+slack+align brings it to **0.0 in all 10 runs** (k16, k32); range alone gives 0.0 at k0.
  - random64 package: 9.8 (from 14.8).
  - Order 16 k0 with range: 12.3 → 0.3.
- The value floor stays at 15–20/run in every arm. It is 15.2 only in the +align arm.
- Pages and height never change.

**Cost** (mean op latency vs SANITY): range +0.06–0.10 µs; align +0.6–2.2 µs; slack +1.6–1.9 µs; full package +4.5–5.5 µs (k16/k32, ≈ +32–43 %). The package stays well below E13's ×2–×3. Most of the cost is extra SSD recoveries of detected dummy flips.

**Interpretation (not measured directly)**
- The remaining internal SDC under range is plausibly the **upward-separator-flip window**. After S → S' > S, keys in [S, S') route to the left child, whose keys are all < S < S', so that visit passes. Only a visit to the right child (lo = S' ≠ first key) fires. The self-test (r3) confirms this asymmetry, but I did not attribute the residual SDC to it run by run.
- The give-ups and the huge internal alarm counts are consistent with **poisoned write-backs**. An undetected internal flip in a node on the insert path is written back to SSD with the next split. After that, SSD recovery restores the violation and the range check alarms on every visit without being able to repair it. This makes most of those ops "detected" (total wrong 3–6 vs undetected 0–1), but it does not fix the tree. A fix would need a repair path (e.g. rebuild the separator from the right child's first key) — not implemented.
- The lower value SDC with align (17–18 → 15.2) is plausibly incidental cleansing. Far more recoveries (≈3 000 vs ≈1 300) reload whole pages and wipe co-resident value flips. Not verified.
- `slack both` is no better than `right`. Free slots (≈45 % of real keys) are the binding limit, and `both` spends them one side per key. At k16/k32 it is worse, probably because left dummies protect only downward flips, which already have a closer real neighbour in-node. Not verified.

## Caveats
- n = 5 (order 16: n = 3). Differences of 2–4 per run are within seed spread. Seed 5 is catastrophic under plain SANITY with internal-only injection, so use medians there.
- `n_poisoned_writes` counts every write in an op that had any FN read, including harmless slack-byte flips. It moves little across arms; do not read it as "corruption made durable".
- Range-alarm parent/child attribution compares the tree's held copy (parent) or the DRAM image (child) with the oracle. Alarms with neither flagged come from an oracle that is already poisoned.
- The detection ratio's denominator is borrowed from existing CTRL_CRC rows (a count of single-bit leaf real-key flip events). No k0 values are available.
- `RANGECHK` is a stderr diagnostic added after the sweeps; it did not change any CSV column. I checked it on 8 runs, not across the matrix.
