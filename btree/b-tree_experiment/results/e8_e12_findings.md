# E8–E12 findings (key sparsity follow-ups)

Base config unless noted (= E7′): `--order=253 --prefill_keys=1000000 --n_ops=30000 --ssd_blocks=512
--ram_rows_per_bank=2048 --lambda_page=3e-3`, EVERY_READ, budget ∞, `bin/exp_fast.exe`.
All CSVs have 214 columns: the 60-column e1 prefix (verified byte-identical header) + E7′/E2b′ columns +
10 new ones appended: `key_dist,inject_level,pred_sanity_rel,pred_sanity_exact,n_wrong_{missing,value,phantom},
n_sdc_{missing,value,phantom}` (n_sdc_* = the same split restricted to no-alarm ops; sums to n_wrong_undetected).
Tables: `python3 scripts/analyze_e8_12.py e{8..12}`. SDC = n_wrong_undetected / n_searches. "edge" = largest
key bit b with Σseeds kb_seen_b > 1000 and kb_tp_b/kb_seen_b < 0.05 (read-weighted histogram; see §14.2 warning 1).

## Regression guard (stride 0 must be a no-op)
`scripts/regcheck.py <csv>` compares every column except run_id against e7_dbscale.csv (NONE/SANITY/FULL_CRC,
stride 0) and e7_ctrlhdr.csv (CTRL_CRC, stride 0), matched on (scheme, seed).
**PASS: 0 differing rows.** NONE and SANITY 5/5 rows × 194 cols (from e12), SANITY/FULL_CRC 5/5 × 194 cols and CTRL_CRC 5/5 × 203 cols
(from e10). `--inject_level=all` was also checked against the e12 NONE s1 k0 row: identical.
Note: the CTRL_CRC numbers in SUMMARY §14.3 (tp 1728.6, 17.626 µs) predate header coverage; current
CTRL_CRC = e7_ctrlhdr (tp 1745.6, 17.698 µs, SDC 6.069e-4).

## E12 — why NONE's SDC falls with sparsity (50 runs: {NONE,SANITY} × k∈{0,8,16,24,32} × 5 seeds)
| stride | scheme | SDC | wrong_total | missing | value | phantom |
|---|---|---|---|---|---|---|
| 0 | NONE | 1.013e-1 | 2737.2 | 2719.0 | 18.2 | 0 |
| 8 | NONE | 5.431e-2 | 1467.6 | 1447.8 | 19.8 | 0 |
| 16 | NONE | 4.382e-2 | 1184.2 | 1164.8 | 19.4 | 0 |
| 24 | NONE | 3.319e-2 | 897.0 | 877.0 | 20.0 | 0 |
| 32 | NONE | 2.426e-2 | 655.8 | 636.6 | 19.2 | 0 |
| 0 | SANITY | 7.179e-4 | 19.6 | 2.2 | 17.4 | 0 |
| 32 | SANITY | 1.058e-3 | 28.6 | 10.2 | 18.4 | 0 |

**Aliasing hypothesis rejected.** Value errors are flat (~19, i.e. values[] payload flips, stride-independent)
and phantoms are 0 at every stride. The whole drop is in `missing` (2719 → 637, −77 %). My interpretation (not
separately tested): a flip of bit b in a separator mis-routes the keys in a 2^b-wide range. With dense keys that
range holds real keys. With sparse keys a low-bit separator shift lands inside an empty gap and mis-routes nothing,
so the flip is **harmless** as well as invisible to SANITY. So part of SANITY's "blind zone" on separators is also a
harmless zone. Phantoms are structurally 0 here because stride-mode miss keys sit at index ≥1e9, far outside the key range.

## E9 — blind edge vs log2(2^k × fanout) across orders (144 runs: order{16,64,253} × k{0,8,16,24} × 4 schemes × 3 seeds)
200k keys, ram_rows_per_bank=8192; ssd_blocks 2048/512/128 for order 16/64/253 (~30 % tree occupancy, like E6a′).
| order | k | pages | internal | fill | pred edge | SANITY edge | SANITY/CTRL tp | (64−k)/64 |
|---|---|---|---|---|---|---|---|---|
| 16 | 0 | 19824 | 1673 | 11.2 | 3.5 | 3 | 0.779 | 1.000 |
| 16 | 8 | | | | 11.5 | 3* | 0.696 | 0.875 |
| 16 | 16 | | | | 19.5 | 3* | 0.611 | 0.750 |
| 16 | 24 | | | | 27.5 | 3* | 0.535 | 0.625 |
| 64 | 0 | 4693 | 121 | 44.4 | 5.5 | 2 | 0.937 | 1.000 |
| 64 | 8 | | | | 13.5 | 12 | 0.805 | 0.875 |
| 64 | 16 | | | | 21.5 | 17 | 0.706 | 0.750 |
| 64 | 24 | | | | 29.5 | 22 | 0.616 | 0.625 |
| 253 | 0 | 1134 | 9 | 180.3 | 7.5 | 7 | 0.980 | 1.000 |
| 253 | 8 | | | | 15.5 | 12 | 0.840 | 0.875 |
| 253 | 16 | | | | 23.5 | 15 | 0.730 | 0.750 |
| 253 | 24 | | | | 31.5 | 23 | 0.616 | 0.625 |

- Stride-0 edges match the prediction for order 16 (3 vs 3.5) and order 253 (7 vs 7.5). Order 64 does not (2 vs 5.5).
- For k > 0 the edge sits near **k to k+4 (leaf gap)**, well below log2(2^k·fill). At 200k keys
  order 253 has only 9 internal nodes, so the separator signal that dominated E7′ (35 internal, 1M keys) is diluted.
  The "edge tracks the separator gap" reading of E7′ **does not generalize** under this edge definition. Which level
  dominates the read-weighted blind mass depends on the tree shape.
- *Order 16 at k>0: too few single-key-flip events (3.6k–7k read-weighted over 3 seeds, keys are ~2 % of a 4 KB page)
  for bits ≥4 to pass seen>1000, so the edge is stuck at 3. With raw counts, bits 0–7 have tp=0 and bit 8+ are detected
  at k=8, i.e. the leaf-gap edge. Treat the order-16 edges as unmeasured.
- tp ratio: order 64/253 track (64−k)/64 within 1–3.5 pp. Order 16 sits ~0.78× below it at every k. My guess is that
  SANITY's children/next_leaf checks matter less relative to CTRL_CRC on small nodes (not investigated).
- 8 LEVELCHK `walk_ok=0` warnings, all NONE seed 3 (order 64/253). The oracle walk is defeated by poisoned write-backs
  under NONE (the oracle stores what was written). The same thing happens in e12 NONE s3. Allocation-based level columns are unaffected.

## E10 — HYBRID (internal = CTRL_CRC, leaf = SANITY) (100 runs: {SANITY,CTRL_CRC,FULL_CRC,HYBRID} × 5 k × 5 seeds)
Self-test `hybrid_self_test()` passes (leaf protect → no entry; internal flips in [0,16+ctrl_len) caught; leaf key
flip caught by sanity ⇔ ordering breaks, exhaustive over 64 bits × 4 key positions). NONE latency = 10.50 µs.
| k | scheme | SDC | lat µs | shadow_max B | tp | fn | final_err |
|---|---|---|---|---|---|---|---|
| 0 | SANITY | 7.179e-4 | 15.128 | 0 | 1711.6 | 1265822 | 1718 |
| 0 | CTRL_CRC | 6.069e-4 | 17.698 | 69154 | 1745.6 | 1171514 | 1434 |
| 0 | **HYBRID** | **6.439e-4** | **16.817** | **396** | 1716.6 | 1175394 | 1522 |
| 0 | FULL_CRC | 0 | 28.559 | 69154 | 4489.8 | 0 | 0 |
| 8 | SANITY / HYBRID | 9.253e-4 / 7.179e-4 | 14.569 / 16.263 | 0 / 396 | 1499.2 / 1505.0 | | |
| 16 | SANITY / HYBRID | 8.881e-4 / 7.993e-4 | 14.062 / 15.759 | 0 / 396 | 1303.4 / 1310.4 | | |
| 24 | SANITY / HYBRID | 9.769e-4 / 9.029e-4 | 13.522 / 15.223 | 0 / 396 | 1095.0 / 1103.2 | | |
| 32 | SANITY / HYBRID | 1.058e-3 / 9.695e-4 | 12.971 / 14.675 | 0 / 396 | 889.4 / 898.6 | | |
CTRL_CRC and FULL_CRC are identical at every k (as in E7′). Fraction of the SANITY→CTRL_CRC SDC gap that HYBRID closes:
k=0 67 %, k=8 65 %, k=16 32 %, k=24 20 %, k=32 20 %.

**Verdict: partially as predicted.**
- ✔ Memory: shadow_bytes_used_max = 396 B = 12 × 33 internal = B_int exactly (vs 69 154 B for CTRL_CRC, −99.4 %).
- ✔ At k=0, SDC is close to CTRL_CRC (6.44e-4 vs 6.07e-4) and well below SANITY.
- ✘ Latency is not ≈ SANITY. It is +60 % over NONE vs +44 % (SANITY) / +69 % (CTRL_CRC). At h=3, 2 of 3 reads per
  search are internal nodes, which are the full 4088 B CRC, so most of CTRL_CRC's verify cost is internal.
- ✘ It does not "stay well below SANITY" as k grows. At k=32 HYBRID is 9.70e-4 vs SANITY 1.06e-3 (−8 %), and tp ≈ SANITY's
  at every k (internal flips are ~0.6 % of all flips). The stride-driven degradation is mostly leaf-side, which E11 confirms.

## E8 — realistic key distributions (100 runs: 4 schemes × {random64, geomgap@8/16/24, clustered} × 5 seeds)
`--key_dist`: random64 = uniform in [0,2^63) deduped (bit 63 is always 0, which leaves headroom for appends);
geomgap@k = cumulative Σ(1+Geom), mean gap 2^k; clustered = (idx/1000)<<32 | idx%1000. The prefill order is the same
index shuffle (`mt19937(seed^0x5f3759df)`), key = sorted_keys[idx]. Appends = max + one gap from the same distribution
(clustered: next idx). Miss keys use **draw-and-reject**: uniform in [0, max_key], redrawn if present in ref (reject rate ≤ 2^-8 for these
distributions). After 64 failed draws it falls back to max+U(1,2^20); that only matters for dense sets like geomgap@0. The stride-mode wrng draw is still
consumed, so the op sequence stays aligned. `pred_sanity_rel` = the spec formula (min-gap). `pred_sanity_exact` = a direction-aware
per-(key,bit) neighbor-crossing fraction. Both use global neighbors, are computed on the final key set, and ignore leaf boundaries.
| key_dist | pred_rel | pred_exact | SANITY/CTRL tp | edge | NONE SDC | SANITY SDC | CTRL SDC |
|---|---|---|---|---|---|---|---|
| geomgap@8 | 0.911 | 0.880 | 0.865 | 18 | 5.43e-2 | 9.92e-4 | 6.07e-4 |
| geomgap@16 | 0.786 | 0.755 | 0.751 | 23 | 4.38e-2 | 8.73e-4 | 6.07e-4 |
| geomgap@24 | 0.661 | 0.630 | 0.632 | 30 | 3.23e-2 | 9.62e-4 | 6.07e-4 |
| random64 | 0.364 | 0.332 | 0.338 | 53 | 3.66e-3 | 1.24e-3 | 6.07e-4 |
| clustered | 1.000 | 1.000 | 0.980 | 18 | 3.37e-2 | 7.40e-4 | 6.07e-4 |
**The formula survives.** pred_exact is within 1.5 pp of the measured ratio on all five distributions. pred_rel (min-gap)
is consistently ~3 pp high, because the min of two gaps overstates the gap in the flip's direction. geomgap@k is within 0.6 pp of
fixed stride k (0.859/0.747/0.627 = SANITY/current CTRL_CRC tp in E10), so the **mean** gap governs and variance doesn't matter. random64
(mean gap 2^43) drops SANITY to 34 % of CTRL_CRC. Clustered is dense locally, so the ratio is 0.98 even though the internal edge is 18
(cluster boundaries put 2^32 gaps into some separators). CTRL_CRC/FULL_CRC SDC is identical across distributions (the fault stream is key-independent).
Caveat: geomgap@8 SANITY SDC (9.9e-4) > @16 (8.7e-4) is non-monotone. NONE also differs, so I'd treat it as workload noise in absolute SDC.

## E11 — single-level injection (54 runs: {NONE,SANITY,CTRL_CRC} × k{0,16,32} × {internal,leaf} × 3 seeds)
`--inject_level`: GuardedRAM keeps page→level from write(), and the injector draws Poisson(λ × |filtered resident| × dt).
**Calibration:** internal = 33 pages → 3e-3 gives ~38 flips/run, so **λ_internal = 0.15 (×50) → 1468 flips/run**;
λ_leaf = 3e-3 (standard) → 5148 flips/run. Absolute SDCs across the two levels are therefore not comparable. Compare within a level.
| inject | k | SANITY edge | SANITY/CTRL tp | NONE SDC | SANITY SDC | CTRL SDC |
|---|---|---|---|---|---|---|
| leaf | 0 | **none (−1)** | 0.984 | 1.83e-3 | 7.77e-4 | 6.91e-4 |
| leaf | 16 | 15 | 0.744 | 1.81e-3 | 1.06e-3 | 6.91e-4 |
| leaf | 32 | 31 | 0.506 | 1.89e-3 | 1.25e-3 | 6.91e-4 |
| internal | 0 | **7** | 0.830 | 6.99e-1 | 8.63e-4 | 0 |
| internal | 16 | 23 | 0.710 | 5.68e-1 | 9.99e-4 | 0 |
| internal | 32 | 38 | 0.597 | 4.03e-1 | 8.76e-4 | 0 |
**Prediction confirmed.** Under leaf injection the edge is the leaf gap (none / 15 / 31 ≈ k−1). Under internal injection it is the separator gap
(7 / 23 / 38 vs log2(2^k·174) = 7.4 / 23.4 / 39.4), so the internal blind zone exists even with dense leaves. Also:
CTRL_CRC's whole residual SDC (6.9e-4) comes from leaf payload, with internal-only SDC = 0. NONE's internal-only SDC
falls with k (0.70 → 0.40), consistent with the E12 interpretation that low-bit separator flips in sparse key spaces are harmless.
The leaf-side NONE SDC is flat in k.

## Cut / unsure
- E9 order-16 edges are unmeasured (too few events). The order-64 stride-0 edge misses the prediction. I didn't investigate.
- E12's mechanism (harmless low-bit separator shifts) is inferred from the missing/value split plus E11, not measured per event.
- The pred_* columns use global neighbors. SANITY really checks within one node only (first/last key of a leaf are unconstrained on one side).
- Code changes: HYBRID scheme, `--key_dist`, `--inject_level`, 10 CSV columns, `hybrid_self_test()`; scripts
  `run_e{8..12}_db.sh`, `e8_12_common.sh` (part-count check), `regcheck.py`, `analyze_e8_12.py`.
