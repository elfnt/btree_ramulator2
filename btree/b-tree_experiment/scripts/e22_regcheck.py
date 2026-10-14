#!/usr/bin/env python3
"""e22_regcheck.py <mid_csv> <geo_csv> — E22 regression checks.
(1) --guard=grid --guard_grid_log2=31 (stride 32) vs results/e13_dbscale.csv guard=mid stride 32,
    matched on (scheme, seed): every E13 column except run_id and guard must be identical.
(2) SANITY guard=none at 4x / 8x geometry vs E13 SANITY guard=none stride 32 at 1x: every column
    except run_id / ssd_blocks / ram_rows_per_bank (geometry-sensitivity control; reported, not fatal).
Exit 1 if (1) has any mismatch."""
import csv, sys
def load(p):
    with open(p) as f: return list(csv.DictReader(f))
e13 = load('results/e13_dbscale.csv')
ref = {(r['scheme'], r['seed']): r for r in e13 if r['guard'] == 'mid' and r['key_stride_log2'] == '32'}
new = load(sys.argv[1]); bad = 0; n = 0
for r in new:
    k = (r['scheme'], r['seed']); rr = ref[k]
    cols = [c for c in rr if c not in ('run_id', 'guard')]
    diff = [c for c in cols if rr[c] != r.get(c)]
    n += 1
    if diff: bad += 1; print('MISMATCH', k, diff[:8])
print(f'(1) grid k=31 vs E13 mid: {n} rows x {len(cols)} cols, {bad} rows differ')
if len(sys.argv) > 2:
    ref1 = {r['seed']: r for r in e13 if r['guard'] == 'none' and r['key_stride_log2'] == '32'
            and r['scheme'] == 'SANITY' and r['ssd_blocks'] == '512'}
    for r in load(sys.argv[2]):
        rr = ref1[r['seed']]
        cols = [c for c in rr if c not in ('run_id', 'ssd_blocks', 'ram_rows_per_bank')]
        diff = [c for c in cols if rr[c] != r.get(c)]
        print(f"(2) geo {r['ssd_blocks']}/{r['ram_rows_per_bank']} seed {r['seed']}: {len(cols)} cols, "
              f"{len(diff)} differ {diff[:6]}")
sys.exit(1 if bad or n == 0 else 0)
