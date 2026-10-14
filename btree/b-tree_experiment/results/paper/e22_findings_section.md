## E22 findings — dummies on a fixed 2^k grid

**Parameters.** Stride keys K = idx << 32 (1M prefill + ~2 977 appends). `--guard=grid --guard_grid_log2=k` inserts the dummies K + j·2^k (j = 1 … 2^(32−k) − 1) through the normal insert path (sentinel value 6, shuffled into the prefill, main-loop dummies inserted inside the same op so their latency counts, a search that hits a dummy counts as not-found), exactly like `--guard=mid`. k = 31 / 30 / 29 → 1 / 3 / 7 dummies per real key. Standard config otherwise (order 253, 30 000 ops, λ = 3e-3, EVERY_READ, 5 seeds; no seed reduction was needed, since an 8× run took ≤ ~3 min wall and 1.4 GB RSS). Data: `results/e22_dbscale.csv` (40 rows), script `scripts/run_e22_db.sh`, checks `scripts/e22_regcheck.py`.

**Geometry.** `--ssd_blocks/--ram_rows_per_bank` = 1024/4096 (2×, k=31), 2048/8192 (4×, k=30), 4096/16384 (8×, k=29). `ram_misses = ram_lru_evictions = 0` in all 40 rows (fully resident; this is the whole-run count, so the main loop is 0 too). Geometry-only controls (SANITY, guard=none at 4× and 8×) are identical to the 1× rows on all 345 columns except geometry/run_id, 10/10 runs.

**Regression.** (a) New binary with default flags vs `e7_dbscale/e7_ctrlhdr` at stride 0: 20/20 rows, 0 columns differ. (b) grid k=31 vs `e13_dbscale.csv` guard=mid, stride 32, SANITY + CTRL_CRC × seeds 1–5: **10/10 rows identical on all 346 shared columns** (only `guard` and `run_id` excluded). So the k=31 row below *is* E13 `mid`.

| arm (stride 2^32) | dummies | ×pages | h | SANITY det. ratio (pred.) | SANITY SDC | missing + value | NONE SDC | CTRL_CRC SDC | SANITY lat µs (×) |
|---|---|---|---|---|---|---|---|---|---|
| none (E13, 1×) | 0 | 1.00 | 3 | 0.468 (0.500) | 1.058e-3 | 10.2 + 18.4 | 2.43e-2 (E7) | 6.07e-4 | 12.97 (1.00) |
| grid k=31 (= E13 mid) | 1 | 2.00 | 3 | 0.490 (0.516) | 1.406e-3 | 14.8 + 23.2 | — | 7.99e-4 | 24.48 (1.89) |
| grid k=30 | 3 | 3.98 | 3 | 0.505 (0.531) | 1.362e-3 | 16.8 + 20.0 | 1.61e-2 | 6.37e-4 | 46.31 (3.57) |
| grid k=29 | 7 | 8.00 | **4** | 0.546 (0.547) | 1.221e-3 | 14.0 + 19.0 | 2.24e-2 | 6.37e-4 | 88.59 (6.83) |
| adjacent right (E13) | 1 | 2.00 | 3 | 0.976 | 1.095e-3 | 7.2 + 22.4 | — | 7.99e-4 | 26.04 (2.01) |

Detection ratio = Σ SANITY `n_keyflip_real_tp` / Σ CTRL_CRC `n_keyflip_real_tp`, same k, same 5 seeds. Pages 5 763 → 11 520 → 22 934 → 46 079; internal nodes 33 → 65 → 130 → 260. Reliable memory is 0 B for SANITY/NONE; CTRL_CRC uses 69 154 / 138 238 / 275 206 / 552 943 B.

**Did the one-bit-per-doubling prediction hold?** In size, yes. The ratio rises monotonically, by +2.2 / +1.5 / +4.1 pp per doubling of entries (predicted +1.6 each), ending at 0.546 against a predicted 0.547. The measurement sits 2.6 pp below the model at none, k=31 and k=30 (the same offset E13 showed) and closes the gap at k=29. Over the whole range the gain is +7.8 pp for 8× pages, while adjacent dummies gain +50.8 pp (0.976) for 2× pages and shift (E21) restores stride-0 behaviour at 1× pages.

**Caveats.**
- **The rising ratio is mostly a falling denominator.** SANITY catches no more real-key flips: real-key tp per run is 535 (none) / 500 / 448 / 447. CTRL_CRC's count falls faster (1 143 / 1 019 / 887 / 818), because real keys hold a shrinking share of each page's bytes as dummies fill it. The "extra bit" is a relative gain only.
- **End to end, SANITY gets worse than no dummies.** Undetected answers per run are 28.6 (none), 38.0, 36.8, 33.0; missing answers go 10.2 → 14.8 → 16.8 → 14.0. The causes are the same as E13 §17.2: more pages means more flips (5 195 → 41 318 per run) and more internal nodes in SANITY's blind zone. The k=29 tree is also one level taller (h = 4), which confounds that cell.
- **Latency scales roughly with the multiplier** (3.6× and 6.8× for SANITY), because every append inserts 3 or 7 extra entries and recoveries rise to 3 607 / 7 358 per run.
- n = 5 per cell. SDC differences of a few answers per run are within seed spread (per-seed SANITY undetected: k=30 27–45, k=29 27–41).
- **Verdict:** grid dummies buy about one bit of SANITY coverage per doubling of the tree, which is the predicted rate and therefore not worth paying for. Adjacency (E13 right) or removing the stride (E21 shift, E18 alignment) dominates.
