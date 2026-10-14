#!/usr/bin/env python3
"""regcheck.py <new_csv_or_dir> — stride-0 regression guard.
Compares every column except run_id (and columns the reference lacks) of new
stride-0 / key_dist=stride / inject_level=all rows against
  results/e7_dbscale.csv  (NONE, SANITY, FULL_CRC; key_stride_log2==0)
  results/e7_ctrlhdr.csv  (CTRL_CRC)
matched on (scheme, seed). Prints per-scheme verdict; exit 1 on any mismatch."""
import csv, sys, glob, os
def load(p):
    with open(p) as f: return list(csv.DictReader(f))
src = sys.argv[1]
files = sorted(glob.glob(os.path.join(src, '*.csv'))) if os.path.isdir(src) else [src]
new = [r for f in files for r in load(f)]
ref = {}
for r in load('results/e7_dbscale.csv'):
    if r['key_stride_log2'] == '0' and r['scheme'] in ('NONE', 'SANITY', 'FULL_CRC'):
        ref[(r['scheme'], r['seed'])] = r
for r in load('results/e7_ctrlhdr.csv'):
    if r['scheme'] == 'CTRL_CRC' and r['key_stride_log2'] == '0': ref[(r['scheme'], r['seed'])] = r
bad = 0; checked = {}
for r in new:
    if r.get('key_stride_log2') != '0' or r.get('key_dist', 'stride') != 'stride' \
       or r.get('inject_level', 'all') != 'all' or r['lambda_page'] != '0.003' or r['order'] != '253':
        continue
    k = (r['scheme'], r['seed'])
    if k not in ref: continue
    cols = [c for c in ref[k] if c != 'run_id']
    diff = [c for c in cols if ref[k][c] != r.get(c)]
    checked.setdefault(r['scheme'], [0, 0, len(cols)])
    checked[r['scheme']][0] += 1
    if diff:
        checked[r['scheme']][1] += 1; bad += 1
        print('MISMATCH', k, diff[:8])
for s, (n, nb, nc) in sorted(checked.items()):
    print(f'{s}: {n} rows x {nc} cols, {nb} rows differ')
sys.exit(1 if bad or not checked else 0)
