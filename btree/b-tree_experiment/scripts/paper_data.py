#!/usr/bin/env python3
"""paper_data.py — paper "cost & time" data for E1–E7 (+E7ext incl. E22).

Writes results/paper/paper_data.json and results/paper/paper_tables.md.
Every row = mean over seeds (n_seeds stated); sdc_sd / lat_sd = sample SD.
HDR_CRC / HDR_MIRROR rows are excluded everywhere.
CTRL_CRC comes from the header-covering *_ctrlhdr.csv reruns where they exist.
Run from the harness root:  python3 scripts/paper_data.py
"""
import csv, json, math, os, statistics as st
from collections import defaultdict

R = 'results'
# BACKEND=r2 → read results/r2/<exp>_r2.csv (Ramulator2 DDR4 backend, ECC off) and write results/paper_r2/.
# Arms with no r2 rows (E21 hash mapping: code not merged into the main binary) fall back to the ram CSV
# and are listed under common.ram_fallback.
BACKEND = os.environ.get('BACKEND', 'ram')
OUT = os.path.join(R, 'paper' if BACKEND == 'ram' else 'paper_r2')
RAM_FALLBACK = []
HDR = {'HDR_CRC', 'HDR_MIRROR'}
SCHEME_ORDER = ['NONE', 'SANITY', 'CTRL_CRC', 'HYBRID', 'FULL_CRC']


def load(name):
    if BACKEND == 'r2':
        if name.endswith('_ctrlhdr.csv'):
            # r2 runs already use the header-covering CTRL_CRC: hand back the CTRL_CRC rows of the r2 CSV
            p2 = os.path.join(R, 'r2', name.replace('_ctrlhdr.csv', '_r2.csv'))
            if not os.path.exists(p2):
                return None
            with open(p2) as f:
                return [r for r in csv.DictReader(f) if r['scheme'] == 'CTRL_CRC']
        if name.endswith('_dbscale.csv'):
            p2 = os.path.join(R, 'r2', name.replace('_dbscale.csv', '_r2.csv'))
            if os.path.exists(p2):
                with open(p2) as f:
                    return list(csv.DictReader(f))
            RAM_FALLBACK.append(name)
    p = os.path.join(R, name)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return list(csv.DictReader(f))


def F(r, c):
    v = r.get(c, '')
    return float(v) if v not in ('', None) else float('nan')


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float('nan')


def sd(xs):
    xs = list(xs)
    return st.stdev(xs) if len(xs) > 1 else 0.0


def sdc(r): return F(r, 'n_wrong_undetected') / F(r, 'n_searches')
def lat(r): return F(r, 'total_latency_s') / F(r, 'n_ops') * 1e6


def has(rows, c): return rows and c in rows[0]


def base_stats(rows):
    """common per-cell fields (mean over rows = seeds)."""
    d = {
        'sdc': mean(sdc(r) for r in rows),
        'sdc_sd': sd(sdc(r) for r in rows),
        'n_wrong_undetected': mean(F(r, 'n_wrong_undetected') for r in rows),
        'lat_us': mean(lat(r) for r in rows),
        'lat_sd': sd(lat(r) for r in rows),
        'overhead_pct': None,
        'recoveries': mean(F(r, 'n_recoveries') for r in rows),
        'pages': mean(F(r, 'n_pages_allocated') for r in rows),
        'tree_height': mean(F(r, 'tree_height') for r in rows),
        'n_internal': (mean(F(r, 'n_internal_total') for r in rows)
                       if 'n_internal_total' in rows[0] else None),
        'shadow_bytes': mean(F(r, 'shadow_bytes_used_max') for r in rows),
        'n_seeds': len(rows),
        'seeds': sorted({int(r['seed']) for r in rows}),
    }
    return d


def group(rows, keyf):
    g = defaultdict(list)
    for r in rows:
        g[keyf(r)].append(r)
    return g


def set_overhead(cells, xkey):
    """overhead_pct vs NONE at the same x (cells: list of dicts with 'scheme')."""
    base = {c[xkey]: c['lat_us'] for c in cells if c['scheme'] == 'NONE'}
    for c in cells:
        b = base.get(c[xkey])
        if b is not None:
            c['overhead_pct'] = (c['lat_us'] - b) / b * 100.0


def swap_ctrl(orig, ctrlhdr):
    """drop HDR rows; replace CTRL_CRC rows by header-covering reruns if available."""
    rows = [r for r in orig if r['scheme'] not in HDR]
    if ctrlhdr is None:
        return rows, 'original CSV (no ctrlhdr rerun)'
    rows = [r for r in rows if r['scheme'] != 'CTRL_CRC'] + ctrlhdr
    return rows, 'ctrlhdr rerun'


def sort_scheme(s): return SCHEME_ORDER.index(s) if s in SCHEME_ORDER else 99


def rnd(x, n=6):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    if isinstance(x, float):
        return float(f'{x:.{n}g}')
    return x


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    if isinstance(o, float):
        return rnd(o)
    return o


data = {}
sources = {}
runcounts = {}

# ── E1 ───────────────────────────────────────────────────────────────────────
o, c = load('e1_dbscale.csv'), load('e1_ctrlhdr.csv')
rows, src = swap_ctrl(o, c)
sources['E1'] = {'file': 'e1_dbscale.csv', 'CTRL_CRC': src + ' (e1_ctrlhdr.csv)'}
runcounts['E1'] = len(rows)
cells = []
for (s, l), g in group(rows, lambda r: (r['scheme'], float(r['lambda_page']))).items():
    d = {'scheme': s, 'lambda': l}
    d.update(base_stats(g))
    d['recall'] = mean(F(r, 'recall') for r in g if r['recall'] != '')
    cells.append(d)
set_overhead(cells, 'lambda')
cells.sort(key=lambda d: (sort_scheme(d['scheme']), d['lambda']))
data['E1'] = cells

# reference NONE at λ=3e-3 (1×) for experiments without their own NONE
e1none = {r['seed']: r for r in o if r['scheme'] == 'NONE' and r['lambda_page'] == '0.003'}

# ── E2 ───────────────────────────────────────────────────────────────────────
o = load('e2_dbscale.csv')
sources['E2'] = {'file': 'e2_dbscale.csv', 'CTRL_CRC': 'original CSV (no ctrlhdr rerun for E2)',
                 'overhead_base': 'E1 NONE λ=3e-3, seeds 1–3 (same config; E2 has no NONE rows)'}
runcounts['E2'] = len(o)
cells = []
for (s, p, b), g in group(o, lambda r: (r['scheme'], r['policy'], r['budget_bytes'])).items():
    d = {'scheme': s, 'policy': p, 'budget_bytes': b}
    d.update(base_stats(g))
    d['entries'] = mean(F(r, 'shadow_bytes_used_max') for r in g) / 12.0
    nb = mean(lat(e1none[r['seed']]) for r in g)
    d['overhead_pct'] = (d['lat_us'] - nb) / nb * 100.0
    cells.append(d)
bkey = lambda b: float('inf') if b == 'inf' else float(b)
cells.sort(key=lambda d: (sort_scheme(d['scheme']), d['policy'], bkey(d['budget_bytes'])))
e2 = {'main': cells, 'rescaled': {}, 'knee': []}
E2_INCOMPLETE = []
for tag in ['e2b', 'e2c', 'e2d', 'e2e']:
    rows = load(f'{tag}_dbscale.csv')
    if not rows or len(rows) < 120:          # 4 policies × 10 budgets × 3 seeds; skip a sweep still running
        E2_INCOMPLETE.append(f'{tag}: {len(rows) if rows else 0}/120 rows')
        continue
    runcounts[tag.upper()] = len(rows)
    nint = mean(F(r, 'n_internal_total') for r in rows)
    B_int = nint * 12
    full = [r for r in rows if r['budget_bytes'] not in ('inf',)]
    B_full = max(float(r['budget_bytes']) for r in full)
    b0 = {r['seed']: lat(r) for r in rows if r['budget_bytes'] == '0' and r['policy'] == 'BY_LEVEL'}
    cfg = {'order': int(rows[0]['order']), 'keys': int(rows[0]['prefill_keys']),
           'n_internal': nint, 'B_int': B_int, 'B_full': B_full,
           'pages': mean(F(r, 'n_pages_allocated') for r in rows),
           'tree_height': mean(F(r, 'tree_height') for r in rows), 'rows': []}
    for (p, b), g in group(rows, lambda r: (r['policy'], r['budget_bytes'])).items():
        d = {'x_B_int': (None if b == 'inf' else float(b) / B_int), 'budget_bytes': b, 'policy': p}
        d.update(base_stats(g))
        nb = mean(b0[r['seed']] for r in g)
        d['overhead_pct'] = (d['lat_us'] - nb) / nb * 100.0
        cfg['rows'].append(d)
    cfg['rows'].sort(key=lambda d: (d['policy'], bkey(d['budget_bytes'])))
    e2['rescaled'][tag.upper()] = cfg
    knee_b = min((float(r['budget_bytes']) for r in full), key=lambda b: abs(b - B_int))
    at = {d['policy']: d for d in cfg['rows'] if d['budget_bytes'] != 'inf' and float(d['budget_bytes']) == knee_b}
    e2['knee'].append({'config': tag.upper(), 'order': cfg['order'], 'keys': cfg['keys'],
                       'n_internal': nint, 'B_int': B_int, 'knee_budget_bytes': knee_b,
                       'knee_pct_B_full': knee_b / B_full * 100,
                       **{f'sdc_{p}': at[p]['sdc'] for p in at},
                       'by_level_over_lru': at['BY_LEVEL']['sdc'] / at['LRU']['sdc'],
                       'lru_over_by_level': at['LRU']['sdc'] / at['BY_LEVEL']['sdc']})
sources['E2b-e'] = {'files': 'e2b/e2c/e2d/e2e_dbscale.csv', 'scheme': 'FULL_CRC only', 'incomplete_skipped': E2_INCOMPLETE,
                    'overhead_base': 'budget=0 row of the same config (no shadow entries = unprotected)'}
data['E2'] = e2

# ── E3 ───────────────────────────────────────────────────────────────────────
o = [r for r in load('e3_dbscale.csv') if r['scheme'] not in HDR]
sources['E3'] = {'file': 'e3_dbscale.csv', 'CTRL_CRC': 'original CSV (no ctrlhdr rerun for E3)'}
runcounts['E3'] = len(o)
modemap = {'uniform': 'uniform', 'hammer': 'hammer', 'colctrl': 'col_b128', 'colpay': 'col_b3000'}
mode = lambda r: modemap[r['run_id'].split('_')[1]]
cells = []
g = group(o, lambda r: (mode(r), r['scheme']))
eff = {m: mean(F(r, 'n_recoveries') for r in g[(m, 'FULL_CRC')]) for m in modemap.values()}
for (m, s), rr in g.items():
    d = {'mode': m, 'scheme': s}
    d.update(base_stats(rr))
    d['effective_flips'] = eff[m]
    d['wrong_per_eff_flip'] = d['n_wrong_undetected'] / eff[m]
    cells.append(d)
set_overhead(cells, 'mode')
mo = list(modemap.values())
cells.sort(key=lambda d: (mo.index(d['mode']), sort_scheme(d['scheme'])))
data['E3'] = cells

# ── E4 ───────────────────────────────────────────────────────────────────────
o = load('e4_dbscale.csv')
sources['E4'] = {'file': 'e4_dbscale.csv', 'CTRL_CRC': 'original CSV (no ctrlhdr rerun for E4)',
                 'overhead_base': 'E1 NONE λ=3e-3, seeds 1–3 (E4 has no NONE rows)'}
runcounts['E4'] = len(o)
th = lambda r: 'EVERY_READ' if r['verify_mode'] == 'EVERY_READ' else float(r['theta_s'])
cells = []
for (s, t), g in group(o, lambda r: (r['scheme'], th(r))).items():
    d = {'scheme': s, 'theta_s': t}
    d.update(base_stats(g))
    d['recall'] = mean(F(r, 'recall') for r in g)
    nb = mean(lat(e1none[r['seed']]) for r in g)
    d['overhead_pct'] = (d['lat_us'] - nb) / nb * 100.0
    cells.append(d)
er = {c['scheme']: c['lat_us'] for c in cells if c['theta_s'] == 'EVERY_READ'}
for c in cells:
    c['dlat_vs_every_read_pct'] = (c['lat_us'] - er[c['scheme']]) / er[c['scheme']] * 100.0
cells.sort(key=lambda d: (sort_scheme(d['scheme']), -1 if d['theta_s'] == 'EVERY_READ' else d['theta_s']))
data['E4'] = cells

# ── E5 ───────────────────────────────────────────────────────────────────────
o, c = load('e5_dbscale.csv'), load('e5_ctrlhdr.csv')
rows, src = swap_ctrl(o, c)
sources['E5'] = {'file': 'e5_dbscale.csv', 'CTRL_CRC': src + ' (e5_ctrlhdr.csv)',
                 'caveat': 'ram_misses not exported: final integrity scan runs on a frozen clock, '
                           'so 95–99 % of ram_misses come from the scan (SUMMARY_dbscale §13 item 23).'}
runcounts['E5'] = len(rows)
cells = []
for (s, rpb), g in group(rows, lambda r: (r['scheme'], int(r['ram_rows_per_bank']))).items():
    d = {'scheme': s, 'ram_rows_per_bank': rpb, 'capacity_pages': 8 * rpb}
    d.update(base_stats(g))
    d['n_flip_events'] = mean(F(r, 'n_flip_events') for r in g)
    d['sdc_per_flip'] = mean(F(r, 'n_wrong_undetected') / F(r, 'n_flip_events') for r in g)
    cells.append(d)
set_overhead(cells, 'ram_rows_per_bank')
cells.sort(key=lambda d: (sort_scheme(d['scheme']), -d['ram_rows_per_bank']))
data['E5'] = cells


# ── E6a / E6b ────────────────────────────────────────────────────────────────
def pred_ctrl_ratio(rows):
    """read-weighted ctrl_len/4096 from the measured per-level node counts (ctrlhdr rows).
    one node read per level per search; leaf ctrl = 16+8n, internal ctrl = 24+16n."""
    vals = []
    for r in rows:
        if 'n_nodes_level_0' not in r:
            return None
        lv = [F(r, f'n_nodes_level_{i}') for i in range(8)]
        h = int(F(r, 'tree_height'))
        nkeys = F(r, 'prefill_keys') + F(r, 'n_ops') - F(r, 'n_searches')
        ls = [16 + 8 * nkeys / lv[0]]
        for l in range(1, h):
            ls.append(24 + 16 * (lv[l - 1] - lv[l]) / lv[l])
        vals.append(mean(ls) / 4096)
    return mean(vals)


def e6(tag, xcol, xname):
    o, c = load(f'{tag}_dbscale.csv'), load(f'{tag}_ctrlhdr.csv')
    rows, src = swap_ctrl(o, c)
    sources[tag.upper()] = {'file': f'{tag}_dbscale.csv', 'CTRL_CRC': src + f' ({tag}_ctrlhdr.csv)'}
    runcounts[tag.upper()] = len(rows)
    cells = []
    for (s, x), g in group(rows, lambda r: (r['scheme'], int(r[xcol]))).items():
        d = {'scheme': s, xname: x}
        d.update(base_stats(g))
        d['n_flip_events'] = mean(F(r, 'n_flip_events') for r in g)
        cells.append(d)
    set_overhead(cells, xname)
    lat_of = {(d['scheme'], d[xname]): d['lat_us'] for d in cells}
    ratios = []
    for x in sorted({d[xname] for d in cells}):
        n, ct, fu = lat_of[('NONE', x)], lat_of[('CTRL_CRC', x)], lat_of[('FULL_CRC', x)]
        ctrl_rows = [r for r in c if int(r[xcol]) == x]
        ratios.append({xname: x, 'ctrl_overhead_us': ct - n, 'full_overhead_us': fu - n,
                       'ctrl_over_full_cost_ratio': (ct - n) / (fu - n),
                       'predicted_ratio_read_weighted_ctrl_len_over_4096': pred_ctrl_ratio(ctrl_rows)})
    for d in cells:
        rr = [q for q in ratios if q[xname] == d[xname]][0]
        if d['scheme'] == 'CTRL_CRC':
            d['ctrl_over_full_cost_ratio'] = rr['ctrl_over_full_cost_ratio']
            d['predicted_ratio'] = rr['predicted_ratio_read_weighted_ctrl_len_over_4096']
    cells.sort(key=lambda d: (d[xname], sort_scheme(d['scheme'])))
    return {'rows': cells, 'cost_ratio': ratios}


data['E6a'] = e6('e6a', 'order', 'order')
data['E6a']['predicted_ratio_SUMMARY_11_3'] = {'8': 0.024, '32': 0.081, '128': 0.206, '253': 0.367}
data['E6b'] = e6('e6b', 'prefill_keys', 'keys')

# ── E7 ───────────────────────────────────────────────────────────────────────
o, c = load('e7_dbscale.csv'), load('e7_ctrlhdr.csv')
rows, src = swap_ctrl(o, c)
sources['E7'] = {'file': 'e7_dbscale.csv', 'CTRL_CRC': src + ' (e7_ctrlhdr.csv)',
                 'note': 'detection ratio = mean SANITY tp / mean CTRL_CRC tp (page-level tp column). '
                         'SUMMARY §14.4 used the ORIGINAL CTRL_CRC rows (tp 1728.6); the ctrlhdr rows '
                         'have tp 1745.6, so ratios here are ~1 % lower than §14.4.'}
runcounts['E7'] = len(rows)
cells = []
for (s, k), g in group(rows, lambda r: (r['scheme'], int(r['key_stride_log2']))).items():
    d = {'scheme': s, 'stride_log2': k}
    d.update(base_stats(g))
    d['tp'] = mean(F(r, 'tp') for r in g)
    cells.append(d)
set_overhead(cells, 'stride_log2')
tpof = {(d['scheme'], d['stride_log2']): d['tp'] for d in cells}
orig_ctrl_tp = {k: mean(F(r, 'tp') for r in o if r['scheme'] == 'CTRL_CRC' and int(r['key_stride_log2']) == k)
                for k in [0, 8, 16, 24, 32]}
for d in cells:
    if d['scheme'] == 'SANITY':
        k = d['stride_log2']
        d['detection_ratio_vs_ctrl'] = d['tp'] / tpof[('CTRL_CRC', k)]
        d['detection_ratio_vs_ctrl_original_rows'] = d['tp'] / orig_ctrl_tp[k]
        d['predicted_ratio'] = (64 - k) / 64
cells.sort(key=lambda d: (d['stride_log2'], sort_scheme(d['scheme'])))

# blind-zone edges
e11 = load('e11_dbscale.csv')
ev = []
for lvl in ['leaf', 'internal']:
    for k in [0, 16, 32]:
        S = [r for r in e11 if r['inject_level'] == lvl and int(r['key_stride_log2']) == k and r['scheme'] == 'SANITY']
        C = [r for r in e11 if r['inject_level'] == lvl and int(r['key_stride_log2']) == k and r['scheme'] == 'CTRL_CRC']
        blind = []
        for b in range(64):
            ct = sum(F(r, f'kb_tp_{b:02d}') for r in C)
            stp = sum(F(r, f'kb_tp_{b:02d}') for r in S)
            if ct > 0 and stp / ct < 0.05:
                blind.append(b)
        ev.append({'level': lvl, 'stride_log2': k, 'n_blind_bits': len(blind),
                   'blind_bits': blind, 'n_seeds': len(S)})
data['E7'] = {
    'rows': cells,
    'blind_zone_read_weighted_SUMMARY_14_5': {
        'definition': 'largest key bit whose SANITY kb_tp/kb_seen < 0.05 (read-weighted denominator, '
                      'leaf+internal mixed), E7 data, copied from SUMMARY §14.5',
        'edge_bit': {'0': 7, '8': 18, '16': 23, '24': 30, '32': 34},
        'predicted_internal_separator_gap_log2': {'0': 7.4, '8': 15.4, '16': 23.4, '24': 31.4, '32': 39.4}},
    'blind_zone_event_based_E11': {
        'definition': 'recomputed here from e11_dbscale.csv (single-level injection, 3 seeds): number of key '
                      'bits where SANITY kb_tp / CTRL_CRC kb_tp < 0.05 (CTRL_CRC tp = event count of that bit). '
                      'SUMMARY §16 note 35a reports leaf 0/16/32, internal 8/24/40.',
        'rows': ev},
}

# ── E7ext ────────────────────────────────────────────────────────────────────
e13 = load('e13_dbscale.csv')
e21 = load('e21_dbscale.csv')
e22 = load('e22_dbscale.csv')
e13_ = lambda **kw: [r for r in e13 if all(r[k] == v for k, v in kw.items())]


def ext_stats(rows):
    d = base_stats(rows)
    d['n_sdc_missing'] = mean(F(r, 'n_sdc_missing') for r in rows)
    d['n_sdc_value'] = mean(F(r, 'n_sdc_value') for r in rows)
    d['n_dummy_keys'] = mean(F(r, 'n_dummy_keys') for r in rows) if 'n_dummy_keys' in rows[0] else 0.0
    d['real_keys'] = mean(F(r, 'prefill_keys') + F(r, 'n_ops') - F(r, 'n_searches') for r in rows)
    d['n_keyflip_real_tp'] = mean(F(r, 'n_keyflip_real_tp') for r in rows) if 'n_keyflip_real_tp' in rows[0] else None
    d['ram_misses_main_loop_max'] = max(F(r, 'ram_misses') for r in rows)
    d['geometry'] = f"{rows[0]['ssd_blocks']}/{rows[0]['ram_rows_per_bank']}"
    return d


ext = []


def add_arm(arm, keyset, groups, src, extra=None):
    """groups: {scheme: rows}. Adds one row per scheme; detection ratio SANITY/CTRL on same seeds."""
    cs = groups.get('CTRL_CRC')
    for s, rows in groups.items():
        if not rows:
            continue
        d = {'arm': arm, 'key_set': keyset, 'scheme': s, 'source': src}
        d.update(ext_stats(rows))
        d['total_entries'] = d['real_keys'] + d['n_dummy_keys']
        if s == 'SANITY' and cs:
            seeds = {r['seed'] for r in rows} & {r['seed'] for r in cs}
            a = sum(F(r, 'n_keyflip_real_tp') for r in rows if r['seed'] in seeds)
            b = sum(F(r, 'n_keyflip_real_tp') for r in cs if r['seed'] in seeds)
            d['detection_ratio'] = a / b if b else None
            d['detection_ratio_seeds'] = sorted(int(x) for x in seeds)
        if extra:
            d.update(extra(rows) if callable(extra) else extra)
        ext.append(d)


# stride 2^32
add_arm('none', 'stride2^32', {s: e13_(scheme=s, key_stride_log2='32', guard='none', ssd_blocks='512')
                               for s in ['SANITY', 'CTRL_CRC']}, 'e13_dbscale.csv guard=none 1x')
add_arm('grid k=31 (=E13 mid, 1 dummy)', 'stride2^32',
        {s: e13_(scheme=s, key_stride_log2='32', guard='mid') for s in ['SANITY', 'CTRL_CRC']},
        'e13_dbscale.csv guard=mid 2x')
if e22:
    for k in ['30', '29']:
        add_arm(f'grid k={k} ({2 ** (32 - int(k)) - 1} dummies)', 'stride2^32',
                {s: [r for r in e22 if r['guard'] == 'grid' and r['guard_grid_log2'] == k and r['scheme'] == s]
                 for s in ['NONE', 'SANITY', 'CTRL_CRC']}, 'e22_dbscale.csv')
add_arm('adjacent right (E13)', 'stride2^32',
        {s: e13_(scheme=s, key_stride_log2='32', guard='right') for s in ['SANITY', 'CTRL_CRC']},
        'e13_dbscale.csv guard=right 2x')
add_arm('adjacent both (E13)', 'stride2^32',
        {s: e13_(scheme=s, key_stride_log2='32', guard='both') for s in ['SANITY', 'CTRL_CRC']},
        'e13_dbscale.csv guard=both 3x')
add_arm('shift K>>32 (E21)', 'stride2^32 stored as K>>32',
        {'SANITY': [r for r in e21 if r['key_map'] == 'shift']}, 'e21_dbscale.csv key_map=shift 1x',
        {'detection_ratio': None,
         'note': 'no CTRL_CRC rows; all 210 shared columns identical to E10 stride-0 SANITY (e21_findings.md)'})
# random64
add_arm('none (plain random64 baseline)', 'random64',
        {s: e13_(scheme=s, key_dist='random64', guard='none', ssd_blocks='512') for s in ['SANITY', 'CTRL_CRC']},
        'e13_dbscale.csv random64 guard=none 1x')


def probes(rows):
    return {'probes_per_hit': sum(F(r, 'n_probes_hit') for r in rows) / sum(F(r, 'n_map_lookups_hit') for r in rows),
            'probes_per_miss': sum(F(r, 'n_probes_miss') for r in rows) / sum(F(r, 'n_map_lookups_miss') for r in rows),
            'map_alarms': mean(F(r, 'n_map_alarms') for r in rows),
            'detection_ratio': None,
            'note': 'no CTRL_CRC rows in E21; detection ratio not measurable. '
                    'total_entries = 2 tree entries per key (slot->orig key, value).'}


for a in ['0.25', '0.5', '0.75']:
    rows = [r for r in e21 if r['key_map'] == 'hashdense' and r['map_load'] == a and r['key_dist'] == 'random64']
    add_arm(f'hash α={a} (E21)', 'random64 (hash-mapped)',
            {s: [r for r in rows if r['scheme'] == s] for s in ['SANITY', 'NONE']},
            'e21_dbscale.csv key_map=hashdense', probes)
for d in ext:
    if d['arm'].startswith('hash'):
        d['total_entries'] = 2 * d['real_keys']
# multipliers vs plain SANITY at 1x of the same key set
ref = {}
for d in ext:
    if d['scheme'] == 'SANITY' and d['arm'].startswith('none'):
        ref[d['key_set']] = d
for d in ext:
    ks = 'random64' if d['key_set'].startswith('random64') else 'stride2^32'
    r0 = ref[ks]
    d['page_multiplier'] = d['pages'] / r0['pages']
    d['lat_multiplier_vs_sanity_1x'] = d['lat_us'] / r0['lat_us']
for d in ext:   # E22 prediction: effective spacing 2^k_eff → ratio (64 − k_eff)/64
    if d['arm'] == 'none' and d['key_set'] == 'stride2^32':
        d['k_eff'] = 32
    elif d['arm'].startswith('grid k='):
        d['k_eff'] = int(d['arm'].split('=')[1].split()[0])
    if 'k_eff' in d:
        d['predicted_ratio'] = (64 - d['k_eff']) / 64
data['E7ext'] = ext
sources['E7ext'] = {'files': 'e13_dbscale.csv, e21_dbscale.csv, e22_dbscale.csv',
                    'detection_ratio': 'Σ SANITY n_keyflip_real_tp / Σ CTRL_CRC n_keyflip_real_tp, same arm, same seeds',
                    'multipliers': 'vs plain SANITY guard=none at 1x geometry of the same key set'}

# ── common ───────────────────────────────────────────────────────────────────
data['common'] = {
    'config': {'order': 253, 'prefill_keys': 1000000, 'n_ops': 30000, 'read_ratio': 0.9, 'miss_ratio': 0.05,
               'inserts': 'append (increasing keys)', 'lambda_page': 3e-3, 'verify_mode': 'EVERY_READ',
               'budget': 'inf', 'geometry_1x': 'ssd_blocks=512, ram_rows_per_bank=2048 (tree ~35% of SSD pages, '
               'fully resident)', 'binary': 'bin/exp_fast.exe (-O2 -DNDEBUG)', 'page_size': 4096,
               'shadow_entry_bytes': 12, 'dt_op_s': 0.01},
    'definitions': {'sdc': 'n_wrong_undetected / n_searches', 'lat_us': 'total_latency_s / n_ops (µs)',
                    'shadow_bytes': 'shadow_bytes_used_max (reliable memory)', 'pages': 'n_pages_allocated',
                    'sd': 'sample SD over seeds', 'excluded': 'HDR_CRC, HDR_MIRROR'},
    'deviations': {'E1': 'λ ∈ {1e-5,1e-4,3e-4,1e-3,3e-3,1e-2,3e-2}', 'E2/E3/E4': '3 seeds',
                   'E2b-e': 'FULL_CRC, 3 seeds, configs per table', 'E3': 'modes change the fault model',
                   'E5': 'ram_rows_per_bank swept', 'E6a': '200k keys, order swept, ssd_blocks per order, rpb 8192',
                   'E6b': 'keys swept with scaled geometry'},
    'run_counts': runcounts,
    'seeds': {'E1': [1, 2, 3, 4, 5], 'E2': [1, 2, 3], 'E2b-e': [1, 2, 3], 'E3': [1, 2, 3], 'E4': [1, 2, 3],
              'E5': [1, 2, 3, 4, 5], 'E6a': [1, 2, 3, 4, 5], 'E6b': [1, 2, 3, 4, 5], 'E7': [1, 2, 3, 4, 5],
              'E22': sorted({int(r['seed']) for r in e22}) if e22 else None},
    'sources': sources,
    'backend': ('ram: pure C++ DRAM model, fixed 100 ns access (bin/exp_fast.exe)' if BACKEND == 'ram' else
                'r2: Ramulator2 cycle-accurate DDR4-2400 (DDR4_8Gb_x8), ECC off (bin/exp_r2.exe --backend=r2 --r2_ecc=0)'),
    'ram_fallback': RAM_FALLBACK,
}
if e22:
    runcounts['E22'] = len(e22)

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, 'paper_data.json'), 'w') as f:
    json.dump(clean(data), f, indent=1, ensure_ascii=False)
print('wrote', os.path.join(OUT, 'paper_data.json'))


# ═════════════════════════════════════════════════════════════════════════════
# paper_tables.md
# ═════════════════════════════════════════════════════════════════════════════
def f_sdc(x): return '—' if x is None else ('0' if x == 0 else f'{x:.3e}')
def f1(x, n=1): return '—' if x is None else f'{x:,.{n}f}'
def f0(x): return '—' if x is None else f'{x:,.0f}'
def fpct(x): return '(base)' if x == 0 else ('—' if x is None else f'{x:+.1f} %')
def fr(x, n=3): return '—' if x is None else f'{x:.{n}f}'


def sdcsd(c): return f"{f_sdc(c['sdc'])} ± {f_sdc(c['sdc_sd'])}"
def latsd(c): return f"{c['lat_us']:.3f} ± {c['lat_sd']:.3f}"


L = []
P = L.append
P('# Paper data — cost & time tables (E1–E7, E7ext/E22)' + ('' if BACKEND == 'ram' else ' — Ramulator2 backend'))
P('')
P('Generated by `scripts/paper_data.py` from the CSVs in `results/`; machine-readable copy: '
  f'`{OUT}/paper_data.json`. Backend: {data["common"]["backend"]}. '
  + (f'Rows taken from the ram backend because no r2 run exists: {", ".join(RAM_FALLBACK)}. ' if RAM_FALLBACK else '')
  + 'Every row is the mean over seeds (n in the `n` column); '
  '`±` is the sample SD over seeds. HDR_CRC / HDR_MIRROR are excluded everywhere. '
  'SDC = n_wrong_undetected / n_searches (≈ 27 000 searches/run). Latency = mean op latency '
  '(total_latency_s / n_ops, µs). Overhead = latency vs NONE at the same x. Reliable memory = '
  'shadow_bytes_used_max (B). Pages = n_pages_allocated. `n_int` = internal nodes (only recorded '
  'in CSVs with ≥ 204 columns, i.e. the ctrlhdr reruns and E2b-e/E13/E21/E22; "—" otherwise).')
P('')
P('Standard config: order 253, 1M prefill keys, 30 000 ops (90 % search, 5 % of searches miss; '
  '10 % append-insert), λ = 3e-3 flips/page/s, EVERY_READ, budget ∞, `--ssd_blocks=512 '
  '--ram_rows_per_bank=2048` (tree ≈ 35 % of SSD pages, fully resident), `bin/exp_fast.exe`.')
P('')
P('**CTRL_CRC source per experiment:** ' + '; '.join(
    f"{k}: {v['CTRL_CRC']}" for k, v in sources.items() if 'CTRL_CRC' in v) + '.')
P('')
P('Run counts (after HDR exclusion): ' + ', '.join(f'{k} {v}' for k, v in runcounts.items()) + '.')
P('')

# E1
P('## E1 — scheme × λ (5 seeds)')
P('')
P('| scheme | λ | n | SDC ± sd | undet. | recall | recov. | lat µs ± sd | overhead | rel. mem B | pages | h | n_int |')
P('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for c in data['E1']:
    P(f"| {c['scheme']} | {c['lambda']:g} | {c['n_seeds']} | {sdcsd(c)} | {f1(c['n_wrong_undetected'])} | "
      f"{fr(c['recall'], 4)} | {f1(c['recoveries'])} | {latsd(c)} | {fpct(c['overhead_pct'])} | "
      f"{f0(c['shadow_bytes'])} | {f0(c['pages'])} | {c['tree_height']:.0f} | {f0(c['n_internal'])} |")
P('')

# E2
P('## E2 — policy × budget at 1M keys (3 seeds)')
P('')
P('CTRL_CRC here is the ORIGINAL (non-header-covering) variant; no ctrlhdr rerun exists for E2. '
  'Overhead is vs E1 NONE λ=3e-3 seeds 1–3 (E2 has no NONE rows). entries = rel. mem / 12 B.')
P('')
P('| scheme | policy | budget B | n | entries | SDC ± sd | undet. | recov. | lat µs ± sd | overhead | rel. mem B | pages |')
P('|---|---|---|---|---|---|---|---|---|---|---|---|')
for c in data['E2']['main']:
    P(f"| {c['scheme']} | {c['policy']} | {c['budget_bytes']} | {c['n_seeds']} | {f1(c['entries'])} | {sdcsd(c)} | "
      f"{f1(c['n_wrong_undetected'])} | {f1(c['recoveries'])} | {latsd(c)} | {fpct(c['overhead_pct'])} | "
      f"{f0(c['shadow_bytes'])} | {f0(c['pages'])} |")
P('')
P('### E2b–E2e — budget in units of B_int (FULL_CRC, 3 seeds)')
P('')
P('B_int = mean n_internal × 12 B (measured). Overhead is vs the budget = 0 row of the same config '
  '(no shadow entries, i.e. unprotected).')
P('')
for tag, cfg in data['E2']['rescaled'].items():
    P(f"**{tag}** — order {cfg['order']}, {cfg['keys']:,} keys, n_internal {cfg['n_internal']:,.0f}, "
      f"B_int {cfg['B_int']:,.0f} B, B_full {cfg['B_full']:,.0f} B, pages {cfg['pages']:,.0f}, h {cfg['tree_height']:.0f}")
    P('')
    P('| ×B_int | budget B | policy | n | SDC ± sd | lat µs ± sd | overhead | rel. mem B |')
    P('|---|---|---|---|---|---|---|---|')
    for c in sorted(cfg['rows'], key=lambda d: (bkey(d['budget_bytes']), d['policy'])):
        xb = '∞' if c['x_B_int'] is None else f"{c['x_B_int']:.2f}"
        P(f"| {xb} | {c['budget_bytes']} | {c['policy']} | {c['n_seeds']} | {sdcsd(c)} | {latsd(c)} | "
          f"{fpct(c['overhead_pct'])} | {f0(c['shadow_bytes'])} |")
    P('')
P('**Knee table (budget grid point at 1.0 × B_int):**')
P('')
P('| config | order | keys | n_int | knee B | % B_full | BY_LEVEL | LRU | BY_HOTNESS | RANDOM | BY_LEVEL/LRU | LRU/BY_LEVEL |')
P('|---|---|---|---|---|---|---|---|---|---|---|---|')
for k in data['E2']['knee']:
    P(f"| {k['config']} | {k['order']} | {k['keys']:,} | {k['n_internal']:,.0f} | {k['knee_budget_bytes']:,.0f} | "
      f"{k['knee_pct_B_full']:.2f} % | {f_sdc(k['sdc_BY_LEVEL'])} | {f_sdc(k['sdc_LRU'])} | {f_sdc(k['sdc_BY_HOTNESS'])} | "
      f"{f_sdc(k['sdc_RANDOM'])} | {k['by_level_over_lru']:.3f} | {k['lru_over_by_level']:.1f}× |")
P('')

# E3
P('## E3 — fault mode × scheme (3 seeds)')
P('')
P('Modes: uniform λ=3e-3; hammer 0.7 events/s × 1e-4 per bit on 2 adjacent rows; col_b128 / col_b3000 = '
  'one-shot column fault at t=150 s on 512 rows, (byte 128 | 3000, bit 3). Effective flips = mean FULL_CRC '
  'recoveries of that mode. CTRL_CRC is the original variant (no ctrlhdr rerun for E3).')
P('')
P('| mode | scheme | n | eff. flips | SDC ± sd | undet. | undet./eff. flip | recov. | lat µs ± sd | overhead | rel. mem B | pages |')
P('|---|---|---|---|---|---|---|---|---|---|---|---|')
for c in data['E3']:
    P(f"| {c['mode']} | {c['scheme']} | {c['n_seeds']} | {f1(c['effective_flips'])} | {sdcsd(c)} | {f1(c['n_wrong_undetected'])} | "
      f"{c['wrong_per_eff_flip']:.4f} | {f1(c['recoveries'])} | {latsd(c)} | {fpct(c['overhead_pct'])} | "
      f"{f0(c['shadow_bytes'])} | {f0(c['pages'])} |")
P('')

# E4
P('## E4 — verification period θ (3 seeds)')
P('')
P('Overhead vs E1 NONE λ=3e-3 seeds 1–3 (E4 has no NONE rows). Δlat is vs the same scheme at EVERY_READ. '
  'CTRL_CRC is the original variant (no ctrlhdr rerun for E4).')
P('')
P('| scheme | θ s | n | SDC ± sd | undet. | recall | recov. | lat µs ± sd | Δlat vs E_R | overhead | rel. mem B |')
P('|---|---|---|---|---|---|---|---|---|---|---|')
for c in data['E4']:
    t = 'EVERY_READ' if c['theta_s'] == 'EVERY_READ' else f"{c['theta_s']:g}"
    P(f"| {c['scheme']} | {t} | {c['n_seeds']} | {sdcsd(c)} | {f1(c['n_wrong_undetected'])} | {fr(c['recall'], 4)} | "
      f"{f1(c['recoveries'])} | {latsd(c)} | {fpct(c['dlat_vs_every_read_pct']) if c['theta_s'] != 'EVERY_READ' else '(base)'} | "
      f"{fpct(c['overhead_pct'])} | {f0(c['shadow_bytes'])} |")
P('')

# E5
P('## E5 — constrained RAM (ram_rows_per_bank, 5 seeds)')
P('')
P('Capacity = 8 × rpb pages (tree ≈ 5 763 pages). SDC/flip = undetected / n_flip_events (per seed, then mean). '
  '**ram_misses is deliberately not exported**: the final integrity scan runs on a frozen clock and accounts for '
  '95–99 % of ram_misses (SUMMARY_dbscale §13 item 23); SDC, latency and flips are main-loop only and unaffected. '
  'NONE at rpb 128 is dominated by one seed-1 outlier (SUMMARY §10.2).')
P('')
P('| scheme | rpb | cap. pages | n | flips | SDC ± sd | SDC/flip | undet. | recov. | lat µs ± sd | overhead | rel. mem B | n_int |')
P('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for c in data['E5']:
    P(f"| {c['scheme']} | {c['ram_rows_per_bank']} | {c['capacity_pages']:,} | {c['n_seeds']} | {f1(c['n_flip_events'])} | {sdcsd(c)} | "
      f"{c['sdc_per_flip']:.4f} | {f1(c['n_wrong_undetected'])} | {f1(c['recoveries'])} | {latsd(c)} | {fpct(c['overhead_pct'])} | "
      f"{f0(c['shadow_bytes'])} | {f0(c['n_internal'])} |")
P('')


def e6_table(key, xname, title):
    P(title)
    P('')
    P('| ' + xname + ' | scheme | n | pages | h | n_int | flips | SDC ± sd | undet. | recov. | lat µs ± sd | overhead | rel. mem B | CTRL/FULL cost | predicted |')
    P('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for c in data[key]['rows']:
        cr = fr(c.get('ctrl_over_full_cost_ratio')) if c['scheme'] == 'CTRL_CRC' else ''
        pr = fr(c.get('predicted_ratio')) if c['scheme'] == 'CTRL_CRC' else ''
        P(f"| {c[xname]:,} | {c['scheme']} | {c['n_seeds']} | {f0(c['pages'])} | {c['tree_height']:.0f} | {f0(c['n_internal'])} | "
          f"{f1(c['n_flip_events'])} | {sdcsd(c)} | {f1(c['n_wrong_undetected'])} | {f1(c['recoveries'])} | {latsd(c)} | "
          f"{fpct(c['overhead_pct'])} | {f0(c['shadow_bytes'])} | {cr} | {pr} |")
    P('')


e6_table('E6a', 'order', '## E6a — node density (order, 200k keys, 5 seeds)')
P('CTRL/FULL cost = (lat_CTRL − lat_NONE)/(lat_FULL − lat_NONE). "predicted" = read-weighted ctrl_len/4096 '
  'recomputed here from the measured per-level node counts of the CTRL_CRC rows (one node per level per search; '
  'leaf ctrl = 16+8n, internal = 24+16n). SUMMARY §11.3 values (estimated from tree geometry): '
  'order 8/32/128/253 = 0.024 / 0.081 / 0.206 / 0.367. The two estimates differ by up to 5 pp at order 253; '
  'the measured ratio also contains recovery (SSD reload) cost, which the byte model ignores.')
P('')
e6_table('E6b', 'keys', '## E6b — tree size (keys, order 253, 5 seeds)')
P('The byte model over-predicts at 3M–5M keys (0.46 / 0.58 vs measured 0.44 / 0.45): the measured overheads '
  'include recovery cost and FULL_CRC recovers ~2.4× more often than CTRL_CRC. Treat "predicted" here as indicative only.')
P('')

# E7
P('## E7 — key sparsity (stride 2^k, 5 seeds)')
P('')
P('Detection ratio = mean SANITY page-level tp / mean CTRL_CRC tp at the same stride (same seeds). '
  'CTRL_CRC from `e7_ctrlhdr.csv` (tp 1745.6); SUMMARY §14.4 used the original CTRL_CRC rows (tp 1728.6), '
  'so the "ratio (orig. CTRL)" column reproduces §14.4.')
P('')
P('| stride | scheme | n | SDC ± sd | undet. | tp | ratio SANITY/CTRL | ratio (orig. CTRL) | predicted (64−k)/64 | recov. | lat µs ± sd | overhead | rel. mem B | pages |')
P('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for c in data['E7']['rows']:
    s = c['scheme'] == 'SANITY'
    P(f"| 2^{c['stride_log2']} | {c['scheme']} | {c['n_seeds']} | {sdcsd(c)} | {f1(c['n_wrong_undetected'])} | {f1(c['tp'])} | "
      f"{fr(c.get('detection_ratio_vs_ctrl')) if s else ''} | {fr(c.get('detection_ratio_vs_ctrl_original_rows')) if s else ''} | "
      f"{fr(c.get('predicted_ratio')) if s else ''} | {f1(c['recoveries'])} | {latsd(c)} | {fpct(c['overhead_pct'])} | "
      f"{f0(c['shadow_bytes'])} | {f0(c['pages'])} |")
P('')
bz = data['E7']['blind_zone_read_weighted_SUMMARY_14_5']
ev = {(r['level'], r['stride_log2']): r['n_blind_bits'] for r in data['E7']['blind_zone_event_based_E11']['rows']}
P('**SANITY blind-zone edge per stride.** (a) *read-weighted*, from SUMMARY §14.5 (E7 data, leaf+internal mixed; '
  'largest bit with SANITY kb_tp/kb_seen < 0.05). (b) *event-based*, recomputed here from `e11_dbscale.csv` '
  '(single-level injection, 3 seeds): number of low key bits with SANITY kb_tp / CTRL_CRC kb_tp < 0.05 — '
  'matches SUMMARY §16 note 35a exactly. E11 only ran strides 0/16/32.')
P('')
P('| stride | (a) read-weighted edge bit (§14.5) | predicted internal sep. gap log2 | (b) event-based blind bits, leaf (E11) | (b) event-based blind bits, internal (E11) |')
P('|---|---|---|---|---|')
for k in [0, 8, 16, 24, 32]:
    P(f"| 2^{k} | {bz['edge_bit'][str(k)]} | {bz['predicted_internal_separator_gap_log2'][str(k)]} | "
      f"{ev.get(('leaf', k), '—')} | {ev.get(('internal', k), '—')} |")
P('')

# E7ext
P('## E7ext — making sparse keys visible to SANITY: cost of each arm')
P('')
P('Stride-2^32 keys unless marked random64. Detection ratio = Σ SANITY `n_keyflip_real_tp` / Σ CTRL_CRC '
  '`n_keyflip_real_tp` on the same arm and seeds (real-slot key flips only; "—" where the arm has no CTRL_CRC rows). '
  'Multipliers are vs plain SANITY, guard=none, 1× geometry of the same key set (stride 2^32: 5 763 pages, 12.97 µs; '
  'random64: 5 763 pages, 12.20 µs). Missing/value = undetected wrong answers per run split by kind (phantom = 0 everywhere). '
  'Real keys = 1M prefill + appended inserts. Hash arms store 2 tree entries per key. '
  'Rel. mem = 0 for every SANITY/NONE row; CTRL_CRC rows use 12 B/page.')
P('')
P('| arm | key set | scheme | n | real keys | entries | pages | ×pages | n_int | h | SDC ± sd | missing | value | det. ratio | pred. (64−k_eff)/64 | lat µs ± sd | ×lat | probes hit/miss | recov. | rel. mem B | geometry |')
P('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for c in data['E7ext']:
    pr = f"{c['probes_per_hit']:.2f} / {c['probes_per_miss']:.2f}" if 'probes_per_hit' in c else '—'
    P(f"| {c['arm']} | {c['key_set']} | {c['scheme']} | {c['n_seeds']} | {f0(c['real_keys'])} | {f0(c['total_entries'])} | "
      f"{f0(c['pages'])} | {c['page_multiplier']:.2f} | {f0(c['n_internal'])} | {c['tree_height']:.1f} | {sdcsd(c)} | {f1(c['n_sdc_missing'])} | "
      f"{f1(c['n_sdc_value'])} | {fr(c.get('detection_ratio'))} | {fr(c.get('predicted_ratio')) if c['scheme'] == 'SANITY' else ''} | {latsd(c)} | {c['lat_multiplier_vs_sanity_1x']:.2f} | {pr} | "
      f"{f1(c['recoveries'])} | {f0(c['shadow_bytes'])} | {c['geometry']} |")
P('')
P('Shift arm: no CTRL_CRC rows; it is column-identical to stride-0 SANITY (E10/E7), whose E7 ratio is 0.981 '
  '(vs ctrlhdr CTRL_CRC page-level tp). Hash arms: E21 has no CTRL_CRC rows, so no detection ratio.')
P('')

fs = os.path.join(OUT, 'e22_findings_section.md')
if os.path.exists(fs):
    with open(fs) as f:
        P(f.read().rstrip())
    P('')
with open(os.path.join(OUT, 'paper_tables.md'), 'w') as f:
    f.write('\n'.join(L))
print('wrote', os.path.join(OUT, 'paper_tables.md'))
