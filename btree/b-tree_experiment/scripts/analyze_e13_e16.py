#!/usr/bin/env python3
"""analyze_e13_e16.py — headline tables for E13 (guard keys) and E16 (in-page CRC).
Usage: python3 scripts/analyze_e13_e16.py [e13|e16|all]   (cwd = b-tree_experiment)
Prints markdown tables; also runs data-quality checks (row counts, invariants,
guard=none reproduction vs e10/e8)."""
import csv, sys, os
from collections import defaultdict
from statistics import mean

def load(p):
    with open(p) as f: return list(csv.DictReader(f))
def f(x): return float(x) if x not in ('', None) else 0.0
def sdc(r): return f(r['n_wrong_undetected']) / f(r['n_searches'])
def dkey(r):
    if r['key_dist'] == 'random64': return 'random64'
    if r['key_dist'] != 'stride': return f"{r['key_dist']}{r['key_stride_log2']}"
    return f"k{r['key_stride_log2']}"
def geo(r): return {'512': '1x', '1024': '2x', '1536': '3x'}[r['ssd_blocks']]

MODEL = {  # scripts/guard_model.py LEAF table
    'k8':  dict(none=.870, right=.999, left=.866, both=1.0, mid=.889),
    'k16': dict(none=.746, right=.999, left=.743, both=1.0, mid=.764),
    'k32': dict(none=.497, right=.999, left=.496, both=1.0, mid=.514),
    'random64': dict(none=.333, right=.666, left=.665, both=1.0),
}
GUARDS = ['none', 'right', 'left', 'both', 'mid']
KEYS = ['k8', 'k16', 'k32', 'random64']

def checks(rows, name):
    bad = 0
    for r in rows:
        if r.get('guard') is None: continue
        if int(r['n_keyflip_real']) + int(r['n_keyflip_dummy']) != int(r['n_keyflip_single_leaf']):
            bad += 1; print(f"  INVARIANT FAIL real+dummy!=single_leaf: {r['run_id']}")
        if r['guard'] == 'none' and int(r['n_dummy_keys']) != 0:
            bad += 1; print(f"  INVARIANT FAIL dummies under guard=none: {r['run_id']}")
        if sum(int(r[f'kbr_seen_{b:02d}']) for b in range(64)) != int(r['n_keyflip_real']):
            bad += 1; print(f"  INVARIANT FAIL kbr_seen sum: {r['run_id']}")
    print(f"- {name}: {len(rows)} rows, invariant failures: {bad}")

def e13():
    rows = load('results/e13_dbscale.csv')
    print('## E13 data checks'); checks(rows, 'e13_dbscale.csv')
    # reproduction of guard=none @1x vs e10/e8
    ref = {}
    for p in ('results/e10_dbscale.csv', 'results/e8_dbscale.csv'):
        for r in load(p): ref[(r['scheme'], dkey(r), r['seed'])] = r
    n = nd = 0; diffcols = defaultdict(int); nref = 0
    for r in rows:
        if r['guard'] != 'none' or geo(r) != '1x': continue
        k = (r['scheme'], dkey(r), r['seed'])
        n += 1
        if k not in ref: continue
        nref += 1
        d = [c for c in ref[k] if c != 'run_id' and ref[k][c] != r.get(c)]
        if d: nd += 1; [diffcols.__setitem__(c, diffcols[c] + 1) for c in d]; print('   differs:', k, d[:6])
    print(f"- guard=none @1x rows: {n}; with a reference row: {nref}; differing rows: {nd}"
          + (f" cols={dict(diffcols)}" if nd else ''))

    cell = defaultdict(list)
    for r in rows: cell[(dkey(r), r['guard'], r['scheme'], geo(r))].append(r)

    print('\n## E13 headline: SDC and real-key detection ratio (SANITY real_tp / CTRL_CRC real_tp)')
    print('| keys | guard | geom | SDC SANITY | SDC CTRL_CRC | SDC HYBRID | ratio meas. | model | dummy-flip ratio | pages | h | internal | dummies | lat SANITY µs | lat CTRL µs |')
    print('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for k in KEYS:
        for g in GUARDS:
            gm = {'none': '1x', 'both': '3x'}.get(g, '2x')
            S = cell.get((k, g, 'SANITY', gm)); C = cell.get((k, g, 'CTRL_CRC', gm))
            H = cell.get((k, g, 'HYBRID', gm))
            if not S: continue
            ratio = sum(int(r['n_keyflip_real_tp']) for r in S) / max(1, sum(int(r['n_keyflip_real_tp']) for r in C))
            dS = sum(int(r['n_keyflip_dummy_tp']) for r in S); dC = sum(int(r['n_keyflip_dummy_tp']) for r in C)
            dr = f"{dS/dC:.3f}" if dC else '—'
            m = MODEL[k].get(g)
            print(f"| {k} | {g} | {gm} | {mean(map(sdc,S)):.3e} | {mean(map(sdc,C)):.3e} | "
                  f"{(f'{mean(map(sdc,H)):.3e}' if H else '—')} | {ratio:.3f} | "
                  f"{(f'{m:.3f}' if m is not None else '—')} | {dr} | "
                  f"{mean(f(r['n_pages_allocated']) for r in S):.0f} | {mean(f(r['tree_height']) for r in S):.0f} | "
                  f"{mean(f(r['n_internal_total']) for r in S):.0f} | {mean(f(r['n_dummy_keys']) for r in S):.0f} | "
                  f"{1e6*mean(f(r['mean_op_latency_s']) for r in S):.2f} | {1e6*mean(f(r['mean_op_latency_s']) for r in C):.2f} |")

    print('\n## E13 absolute counts per run (mean of 5): wrong-undetected, flips, real-key single flips')
    print('| keys | guard | scheme | undetected wrong | missing SDC | value SDC | flip events | real keyflips (CTRL tp) | SANITY real tp |')
    print('|---|---|---|---|---|---|---|---|---|')
    for k in KEYS:
        for g in GUARDS:
            gm = {'none': '1x', 'both': '3x'}.get(g, '2x')
            for s in ('SANITY', 'CTRL_CRC', 'HYBRID'):
                R = cell.get((k, g, s, gm))
                if not R: continue
                print(f"| {k} | {g} | {s} | {mean(f(r['n_wrong_undetected']) for r in R):.1f} | "
                      f"{mean(f(r['n_sdc_missing']) for r in R):.1f} | {mean(f(r['n_sdc_value']) for r in R):.1f} | "
                      f"{mean(f(r['n_flip_events']) for r in R):.0f} | {mean(f(r['n_keyflip_real_tp']) for r in R):.1f} | "
                      f"{(mean(f(r['n_keyflip_real_tp']) for r in cell[(k,g,'SANITY',gm)])):.1f} |")

    cfgcols = {'run_id', 'ssd_blocks', 'ram_rows_per_bank', 'ram_hits', 'ram_misses'}
    for k in ('k32', 'random64'):
        for sd in '12345':
            base = [r for r in cell[(k, 'none', 'SANITY', '1x')] if r['seed'] == sd][0]
            for gm in ('2x', '3x'):
                o = [r for r in cell[(k, 'none', 'SANITY', gm)] if r['seed'] == sd][0]
                d = [c for c in base if c not in cfgcols and base[c] != o[c]]
                if d: print('  geometry diff', k, sd, gm, d[:8])
    print('- geometry sensitivity: rows compared on all non-config columns (diffs printed above if any)')
    print('\n## E13 geometry sensitivity: SANITY × guard=none')
    print('| keys | geom | SDC | flip events | pages | lat µs |')
    print('|---|---|---|---|---|---|')
    for k in ('k32', 'random64'):
        for gm in ('1x', '2x', '3x'):
            R = cell.get((k, 'none', 'SANITY', gm))
            if not R: continue
            print(f"| {k} | {gm} | {mean(map(sdc,R)):.3e} | {mean(f(r['n_flip_events']) for r in R):.0f} | "
                  f"{mean(f(r['n_pages_allocated']) for r in R):.0f} | {1e6*mean(f(r['mean_op_latency_s']) for r in R):.2f} |")

def e16():
    rows = load('results/e16_dbscale.csv')
    print('## E16 data checks'); checks(rows, 'e16_dbscale.csv')
    ref = load('results/e10_dbscale.csv') + [r for r in load('results/e8_dbscale.csv') if r['key_dist'] == 'random64']
    allr = rows + ref
    cell = defaultdict(list)
    for r in allr: cell[(dkey(r), r['scheme'])].append(r)
    print('\n## E16: in-page CRC vs shadow-store schemes (5 seeds each; ref rows from e10/e8)')
    print('| keys | scheme | SDC | undetected wrong/run | mean lat µs | shadow_bytes_used_max | recall | recoveries/run | fp |')
    print('|---|---|---|---|---|---|---|---|---|')
    for k in ('k0', 'k32', 'random64'):
        for s in ('SANITY', 'HYBRID', 'CTRL_CRC', 'INPAGE_CTRL', 'FULL_CRC', 'INPAGE_FULL'):
            R = cell.get((k, s))
            if not R: continue
            print(f"| {k} | {s} | {mean(map(sdc,R)):.3e} | {mean(f(r['n_wrong_undetected']) for r in R):.1f} | "
                  f"{1e6*mean(f(r['mean_op_latency_s']) for r in R):.2f} | {max(int(r['shadow_bytes_used_max']) for r in R)} | "
                  f"{mean(f(r['recall']) for r in R):.4f} | {mean(f(r['n_recoveries']) for r in R):.0f} | "
                  f"{sum(int(r['fp']) for r in R)} |")

if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    w = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if w in ('e16', 'all') and os.path.exists('results/e16_dbscale.csv'): e16(); print()
    if w in ('e13', 'all') and os.path.exists('results/e13_dbscale.csv'): e13()
