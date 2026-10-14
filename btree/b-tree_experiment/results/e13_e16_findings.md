# E13 (guard keys) and E16 (in-page CRC): findings

Raw data: `e13_dbscale.csv` (270 rows), `e16_dbscale.csv` (30 rows). Scripts: `scripts/run_e13_db.sh`,
`scripts/run_e16_db.sh`, `scripts/analyze_e13_e16.py` (full tables → `dbscale/e13_e16_tables.md`).
CSV: 348 columns (214 old + 134 appended: `guard, n_dummy_keys, n_keyflip_real[_tp], n_keyflip_dummy[_tp], kbr_seen_00..63, kbr_tp_00..63`).

## Config, geometry, checks

- order 253, 1M real keys, 30 000 ops, λ = 3e-3, EVERY_READ, budget ∞, `bin/exp_fast.exe`, seeds 1–5.
- Geometry (tree takes about 35 % of physical pages; RAM > tree, so the whole tree stays resident):
  1×: `--ssd_blocks=512 --ram_rows_per_bank=2048` (guard none) · 2×: `1024 / 4096` (right/left/mid) · 3×: `1536 / 6144` (both).
- Sentinel value = 6. Real values are 7K+13 mod 2^64. Because 7 is odd, the value 6 only arises for K = 2^64−1, which is never a real key (checked at insert time).
- **Regression** (all new flags at default, stride 0, NONE/SANITY/FULL_CRC/CTRL_CRC × 5): `regcheck.py` matched every row on every column
  (194 columns; 203 for CTRL_CRC). 0 rows differ.
- **Reproduction**: all 55 guard=none 1× rows that have a reference row in `e10`/`e8` match it on every shared column except run_id
  (0 rows differ). The 5 HYBRID×random64 rows are new and have no reference.
- **Geometry sensitivity**: SANITY×none at 2× and 3× is **identical** to 1× on every non-config column (k32 and random64, all seeds).
  So larger SSD/RAM geometry alone does not change the results. Any guard effect comes from the tree, not from the geometry.
- Invariants hold in all 300 rows: `real+dummy == single_leaf` and `Σkbr_seen == n_keyflip_real`.
- LEVELCHK: 6/270 E13 runs report `walk_ok=0`. All six are SANITY runs with guards (5 of them guard=both), and the failure is in the oracle walk only.
  This is the same kind of failure as the known NONE s3 cases in E9/E12: a poisoned write corrupts the oracle. The per-level counts come from the allocation counters and are unaffected.
- Self-tests (abort on failure): INPAGE (i0–i6) and guard (g1–g3) at startup. Every guarded run also performs a post-prefill
  end-to-end check: a sample of dummies is found raw with value = sentinel, and a sample of real keys returns the correct value.

## E13: real-key detection ratio, SANITY real_tp ÷ CTRL_CRC real_tp (measured vs `guard_model.py`)

| keys | none | right | left | both | mid |
|---|---|---|---|---|---|
| stride 2^8  | 0.849 (0.870) | 0.988 (0.999) | 0.860 (0.866) | 0.986 (1.000) | 0.874 (0.889) |
| stride 2^16 | 0.722 (0.746) | 0.984 (0.999) | 0.727 (0.743) | 0.981 (1.000) | 0.745 (0.764) |
| stride 2^32 | 0.468 (0.497) | 0.976 (0.999) | 0.474 (0.496) | 0.969 (1.000) | 0.490 (0.514) |
| random64    | 0.298 (0.333) | 0.635 (0.666) | 0.635 (0.665) | 0.975 (1.000) | — |

Measured (pooled over 5 seeds; denominator = CTRL_CRC's `n_keyflip_real_tp` at the same guard config, 943–1148 events/run).
- The model's ordering holds in every column. The right/left asymmetry on stride keys holds: left ≈ none (+0.5–1.1 pp), right ≈ 0.98.
  mid ≈ none +1.6–2.5 pp (model predicts +1.7–1.9). random64: right ≈ left ≈ 0.635; both = 0.975.
- The measurement sits systematically 1–3.5 pp below the model, including at guard=none. *Interpretation:* the model ignores leaf boundaries,
  and the first or last key in a leaf (or a K whose K+1 dummy landed in the next leaf after a split) has no in-node neighbour on one side.
  E8 showed the same offset.
- Flips of dummy keys are caught at ≈ the unguarded ratio (0.48–0.87), as expected, because dummies have no guards of their own.

## E13: end-to-end cost and benefit (undetected wrong answers per run, mean/median of 5; SDC = that ÷ ~27 000 searches)

| keys | guard | pages | SANITY | SANITY missing | HYBRID | HYBRID missing | CTRL_CRC | lat µs S / H / C |
|---|---|---|---|---|---|---|---|---|
| k8  | none  | 5 763  | 25.0 / 23 | 7.6 | 19.4 / 19 | 2.0 | 16.4 / 16 | 14.6 / 16.3 / 17.7 |
| k8  | right | 11 520 | 28.6 / 27 | 6.8 | 22.4 / 23 | 0.6 | 21.6 / 21 | 27.2 / 29.4 / 30.8 |
| k8  | both  | 16 971 | 48.2 / 32 | 28.0* | 21.6 / 20 | 1.4 | 19.6 / 19 | 38.8 / 41.4 / 43.2 |
| k32 | none  | 5 763  | 28.6 / 28 | 10.2 | 26.2 / 26 | 7.8 | 16.4 / 16 | 13.0 / 14.7 / 17.7 |
| k32 | right | 11 520 | 29.6 / 28 | 7.2 | 23.0 / 24 | 0.6 | 21.6 / 21 | 26.0 / 28.2 / 30.8 |
| k32 | left  | 11 520 | 36.6 / 37 | 14.4 | — | — | 20.8 / 21 | 24.4 / — / 30.8 |
| k32 | both  | 16 971 | 51.2 / 37 | 30.4* | 22.2 / 20 | 1.4 | 19.6 / 19 | 36.8 / 39.5 / 43.2 |
| k32 | mid   | 11 520 | 38.0 / 38 | 14.8 | — | — | 21.6 / 21 | 24.5 / — / 30.8 |
| r64 | none  | 5 763  | 33.6 / 33 | 14.8 | 30.8 / 30 | 12.0 | 16.4 / 16 | 12.2 / 13.9 / 17.7 |
| r64 | right | 11 520 | 35.4 / 30 | 12.6 | 28.6 / 27 | 5.8 | 21.6 / 21 | 25.5 / 27.7 / 30.9 |
| r64 | left  | 11 516 | 34.4 / 32 | 12.4 | — | — | 19.6 / 18 | 25.5 / — / 31.0 |
| r64 | both  | 16 975 | 48.2 / 29 | 30.0* | 19.2 / 22 | 1.2 | 17.0 / 17 | 37.7 / 40.4 / 43.3 |

Height is 3 in every cell. Internal nodes: 33 (1×), 65 (2×), 110–111 (3×). Flip events/run: 5 195 / 10 346 / 15 217 (λ is per resident page, so flips scale with pages).
k16 is omitted here for space and sits between k8 and k32 (full table in `dbscale/e13_e16_tables.md`).
\* Each `both` SANITY mean includes one catastrophic seed (126–140 wrong, ~110 missing, thousands of poisoned writes, LEVELCHK walk failure).
Without that seed, missing is about 8–10. Medians are given for this reason.

Measured:
- **With SANITY alone, guards never lowered SDC.** Mean or median stayed the same or rose in every cell. right: ≈ +1 to +4/run. both: +6 to +9/run (median).
- **With HYBRID (internal CRC + leaf SANITY), guards remove almost all leaf-key missing SDC**: k32 7.8 → 0.6 (right) / 1.4 (both); random64 12.0 → 5.8 / 1.2.
  The total falls only a little (k32 26.2 → 23.0 / 22.2; random64 30.8 → 28.6 / 19.2). HYBRID+both ends up within ~2–3/run of CTRL_CRC at the *same* geometry.
- CTRL_CRC itself gets worse with the bigger tree (16.4 → 21.6 / 19.6). This is all value SDC (missing = 0).
  So HYBRID+guards does not reach 1× CTRL_CRC (16.4) in any cell.
- Cost: mean op latency roughly ×2 (right/left/mid) and ×3 (both). Each insert also writes the dummies, with one t_ssd write-through each.
  Pages also go ×2 / ×3, and with a per-page λ the flip count goes ×2 / ×3 too.

Interpretation (not measured directly):
- Guards fix the leaf-key blind zone as the model predicts. The SANITY total still rises because (a) there are about 2–3× as many internal nodes,
  and their SANITY blind zone (§16.2) produces more missing answers (SANITY missing − HYBRID missing goes 2.4 → 6.6 → ~7 at k32),
  and (b) value SDC rises by about 3–5/run even under CTRL_CRC. A possible cause of (b): reads per page halve or third, so cleansing on detection is slower.
  I have not verified this.
- Under this fault model (a fixed per-page flip rate), doubling the tree doubles the exposure. That cost is larger than the leaf-key benefit unless internal nodes have a CRC.

## E16: in-page CRC vs shadow-store schemes (5 seeds; SANITY/HYBRID/CTRL_CRC/FULL_CRC rows from e10 / e8)

| keys | scheme | undetected/run | SDC | mean lat µs | shadow_bytes_used_max |
|---|---|---|---|---|---|
| k0  | SANITY / HYBRID | 19.4 / 17.4 | 7.18e-4 / 6.44e-4 | 15.13 / 16.82 | 0 / 396 |
| k0  | CTRL_CRC → **INPAGE_CTRL** | 16.4 → **16.4** | 6.07e-4 → **6.07e-4** | 17.70 → **17.64** | 69 408 → **0** |
| k0  | FULL_CRC → **INPAGE_FULL** | 0 → **0** | 0 → **0** | 28.56 → **28.49** | 69 408 → **0** |
| k32 | SANITY / HYBRID | 28.6 / 26.2 | 1.06e-3 / 9.70e-4 | 12.97 / 14.68 | 0 / 396 |
| k32 | INPAGE_CTRL / INPAGE_FULL | 16.4 / 0 | 6.07e-4 / 0 | 17.64 / 28.49 | 0 / 0 |
| r64 | SANITY | 33.6 | 1.24e-3 | 12.20 | 0 |
| r64 | CTRL_CRC → INPAGE_CTRL | 16.4 → 16.4 | 6.07e-4 → 6.07e-4 | 17.73 → 17.67 | 69 408 → 0 |
| r64 | FULL_CRC → INPAGE_FULL | 0 → 0 | 0 | 28.66 → 28.59 | 69 408 → 0 |

Measured: in all 30 runs, per-seed `n_wrong_undetected` and `n_wrong_total` equal the shadow-store counterpart's, and flip events are identical.
Recoveries are +2–3/run. These are presumably flips in the 4-byte stored-CRC tail; I have not counted them separately. fp = 0.
Cost charged: per verified read, `(cover bytes) × t_crc_per_byte`, where cover = 16+ctrl_len re-derived from the image just read, clamped to ≤ 4092
(INPAGE_CTRL), or 4092 (INPAGE_FULL). Writes are charged the same on the trusted image. **No `t_reliable_s`**
(this is the only difference from CTRL_CRC/FULL_CRC, apart from FULL charging 4092 instead of 4096 bytes). Net: about −0.06–0.07 µs/op.
Tail-is-free: asserted on every write (used ≤ 4092, tail all zero before stamping). `deserialize` reads only the range set by n_keys, and the SSD stores bytes 16..4095 verbatim.
The n_keys-corruption self-test passes: all 32 single-bit flips of n_keys, plus 0xDEADBEEF, are caught for both schemes.

## Caveats / unsure

- n = 5 per cell. Differences of 2–4 wrong answers per run are within seed spread (e.g. CTRL_CRC right: 16–29).
- SANITY×both means are dominated by one seed. Use medians or exclude that seed when comparing.
- "real/dummy" uses the oracle's value slot. Only single-byte, single-bit key flips in leaves are classified (as with `kb_*`).
- I did not test guards on internal separators separately, or "slack-only" guards (model columns `slack-only`, `INTERNAL` table). E13 is data-level only.
- INPAGE under PERIODIC verify is rejected (no per-page last-verified state without an entry).
