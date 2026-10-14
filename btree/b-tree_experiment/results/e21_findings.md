# E21 — dense key mapping so the SANITY ordering check works again

**Setup.** λ = 3e-3, order 253, 1M prefill keys, 30 000 ops (90 % search, 5 % of searches are misses), EVERY_READ, 5 seeds. No CRC scheme anywhere; only `NONE` and `SANITY`.
Geometry: `hashdense` uses 2× (`--ssd_blocks=1024 --ram_rows_per_bank=4096`); `shift` uses 1× (512/2048), the same as the E10 reference. Every run kept the whole tree in RAM (`ram_misses = ram_lru_evictions = 0` in all 40 rows).
Matrix: 40 rows in `results/e21_dbscale.csv` (357 columns). Script: `scripts/run_e21_db.sh`. Tables: `scripts/analyze_e21.py`.
New columns, appended after column 348: `key_map, map_load, map_slots, map_lmax, n_probes_hit, n_probes_miss, n_map_alarms`, plus **two not in the brief**: `n_map_lookups_hit, n_map_lookups_miss`. Mean probes cannot be computed without these denominators.

**Implementation.** `include/keymap.hpp` and `src/keymap.cpp` (mixer: splitmix64). Small, flag-gated edits elsewhere:
- `ExpBTree::search_pair` returns entry 2s and, when it sits in the same leaf, entry 2s+1 from one traversal. It falls back to a second search only when 2s is the last key of its leaf.
- `ExpBTree::reload_page` and `GuardedRAM::reload_clean`: an SSD reload that counts toward `n_recoveries`.
- `M = ceil(N_total/α)`. `N_total` is computed exactly by replaying the workload RNG, and the driver asserts that it matches the real insert count.
- A lookup also stops once the probe distance exceeds `L_max`. This is valid because nothing is ever deleted.
- The map's consistency check stays on under `NONE` too, because it is part of the mapping.

## Self-test and regression (all passed)
- Round trip on a clean tree with 10^5 random keys: 0 lost, 0 phantom, 0 alarms over 10^5 absent keys. The same holds for `shift` at k = 32.
- Consistency check on single-bit flips of the stored original key (10^5 keys × 64 bits):

  | α | M | L_max | caught | expected 1 − (L_max+1)/M |
  |---|---|---|---|---|
  | 0.25 | 400 000 | 10 | 0.999970 | 0.999973 |
  | 0.5 | 200 000 | 24 | 0.999868 | 0.999875 |
  | 0.75 | 133 334 | 112 | 0.999161 | 0.999153 |

- End to end, with real DRAM `flip_bit`s on the stored key: 3000 / 3000 caught at α = 0.25 and 0.5, and 2999 / 3000 at α = 0.75. Every alarm reloaded the leaf and returned the correct value. The one miss was predicted by the consistency check.
- With `--key_map=none` the binary reproduces the references byte for byte. `regcheck.py` against e7: NONE and SANITY, 5 + 5 rows × 194 columns, 0 differ. random64 SANITY seed 1 against e8: 214 columns, 0 differ.

## Arm A — `shift` (stride 2^32 stored as K >> 32)
Compared with the E10 stride-0 SANITY rows, all 5 seeds are **identical in all 210 shared columns** (excluding `run_id`, `key_stride_log2` and `pred_sanity_*`).
- Undetected wrong answers per run: 19.4 (2.0 missing + 17.4 value). Stored as-is (E13, 1×) it is 28.6 (10.2 + 18.4).
- No extra pages; latency 15.13 µs.

## Arm B — `hashdense`, random64 keys (undetected wrong answers per run)
| config | undet. mean / median | missing | value | phantom | map alarms | probes/hit | probes/miss | L_max | lat µs | recoveries | pages | h | internal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ref E8 SANITY as-is (1×) | 33.6 / 33 | 14.8 | 18.8 | 0 | – | 1 | 1 | – | 12.20 | 590 | 5 763 | 3 | 33 |
| ref E8 NONE as-is (1×) | 98.8 / 117 | 79.2 | 19.6 | 0 | – | 1 | 1 | – | 10.50 | 0 | 5 763 | 3 | 33 |
| ref E13 SANITY guard=right (2×) | 35.4 / 30 | 12.6 | 22.8 | 0 | – | 1 | 1 | – | 25.53 | 2 294 | 11 520 | 3 | 65 |
| **α=0.25 SANITY** | **22.6 / 21** | **4.6** | 18.0 | 0 | 1 616 | 1.17 | 1.40 | 14 | 28.21 | 4 971 | 11 504 | 3 | 65 |
| **α=0.5 SANITY** | **26.0 / 23** | **4.6** | 21.4 | 0 | 1 696 | 1.50 | 2.57 | 39 | 28.55 | 5 063 | 11 493 | 3 | 65 |
| **α=0.75 SANITY** | **21.4 / 21** | **3.4** | 18.0 | 0 | 2 102 | 2.50 | 8.18 | 184 | 29.42 | 5 447 | 11 522 | 3 | 65 |
| α=0.25 NONE | 1 116.6 / 781 | 1 095.6 | 21.0 | 0 | 3 352 | 1.16 | 1.38 | 14 | 20.87 | 3 365 | 11 505 | 3 | 65 |
| α=0.5 NONE | 1 625.0 / 1 746 | 1 601.4 | 23.6 | 0 | 3 327 | 1.47 | 2.47 | 39 | 20.98 | 3 338 | 11 493 | 3 | 65 |
| α=0.75 NONE | 1 174.8 / 1 156 | 1 155.2 | 19.6 | 0 | 3 804 | 2.43 | 7.80 | 184 | 21.58 | 3 820 | 11 521 | 3 | 65 |
| stride 2^32 hashdense α=0.5 SANITY | 70.6 / 25 | 52.4 | 18.2 | 0 | 1 720 | 1.50 | 2.45 | 37 | 32.76 | 306 873* | 11 502 | 3 | 65 |

\* One seed (s2) caused a reload storm: 1.51M recoveries and 242 missing answers. The other four seeds have 16–25 undetected answers and about 5 100 recoveries. Read this row by its median.
A control at 2× geometry with the tree at its original size (E13 random64 SANITY guard=none geo2x) is identical to E8 (33.6), so geometry alone changes nothing.

**Offline model vs measured probes:**

| α | hit (model) | hit (measured) | miss (model) | miss (measured, SANITY / NONE) |
|---|---|---|---|---|
| 0.25 | 1.16 | 1.17 | 1.39 | 1.40 / 1.38 |
| 0.5 | 1.50 | 1.50 | 2.47 | 2.57 / 2.47 |
| 0.75 | 2.50 | 2.50 | 8.57 | 8.18 / 7.80 |

At α = 0.75 the miss figure comes in under the model, plausibly because of the `L_max` stop and the finite run.

## Caveats and interpretation (not separately verified unless stated)
- **Missing answers fall, value errors do not.** Under SANITY, undetected "missing" answers drop from 14.8 to 3.4–4.6 (stride-0 is 2.0). Value errors stay at 18–21: values are outside every check here.
- **No clean α trend.** The totals of 21–26 per run differ by about the seed-to-seed spread (5 seeds).
- **Key-flip detection.** The read-weighted `n_keyflip_single_leaf_tp / seen` is 0.50–0.56 for hashdense, against 0.58 for stride-0 and 0.004 for random64 stored as-is. So in-leaf key flips are now caught about as often as with dense keys. The model's per-flip 0.98 is a different, event-level quantity; it was not measured directly.
- **NONE gets much worse with the mapping (measured).** In single-seed diagnostics (seed 1, α = 0.5):
  - λ = 0: 0 errors.
  - Flips injected into internal nodes only: 1 072 undetected answers (as-is random64: 355).
  - Flips injected into leaves only: 55.

  Interpretation: hashed inserts land everywhere and split leaves everywhere, so corrupted internal nodes get written back to SSD and misroute whole key ranges for good. Also, one hidden slot cuts off every probe chain that runs through it. Don't use the mapping without SANITY.
- **Cost.** About 2× pages (5 763 → ~11 500), internal nodes 33 → 65, and mean latency 12.2 → 28–29 µs (2.3–2.4×).
  - About 1 600–2 100 map alarms per run each trigger a 100 µs SSD reload. That is roughly 5–7 µs per op, and alarms are cheap to cause because stored-key flips are now caught.
  - Every insert costs probes plus two tree inserts.
  - The value fetch uses one traversal (`search_pair`), so this is not a harness artifact. The second search happens only when entry 2s is the last key in its leaf, roughly 1 time in 170.
- **Structural costs that held up:** (1) the original 8-byte key must be stored next to the value (2 tree entries per key, about 2× pages); (2) the tree order is hash order, so **ordered range scans over application keys are lost**.
- **SANITY prediction columns.** `pred_sanity_*` is still computed on application keys, so it does not describe the mapped tree.
- Each cell has 5 seeds. Differences of 2–4 answers are within seed noise. The stride-2^32 hashdense row has a single-seed outlier.
