#!/usr/bin/env python3
"""analyze_e17_e20.py — tables for E17–E20 (SANITY-only extensions) next to NONE/SANITY baselines.
Prints markdown to stdout. Missing CSVs are skipped (partial results are still tabulated).
Baselines are taken from existing CSVs (no reruns):
  NONE   all-level : e12 (stride), e8 (random64)          SANITY all-level: e10/e12 (stride), e8 (random64)
  internal/leaf    : e11 (3 seeds, stride 0/16/32 only)   order 16       : e9 (3 seeds)
  key-flip event denominator (detection ratio only): CTRL_CRC real_tp from e13 (guard none) / e7_ctrlhdr (k0)."""
import csv, os, statistics as st, sys
R = 'results'
def load(name):
    p = os.path.join(R, name)
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []
def kd(r):
    return 'r64' if r.get('key_dist') == 'random64' else 'k' + r['key_stride_log2']
def sel(rows, **c):
    out = []
    for r in rows:
        ok = True
        for k, v in c.items():
            if k == 'keys': ok &= kd(r) == v
            elif k == 'il': ok &= r.get('inject_level', 'all') == v
            elif k == 'rg': ok &= r.get('sanity_range', '0') == v
            elif k == 'al': ok &= r.get('sanity_align_log2', '0') != '0' if v else r.get('sanity_align_log2', '0') == '0'
            elif k == 'sg': ok &= r.get('slack_guard', 'none') == v
            elif k == 'guard': ok &= r.get('guard', 'none') == v
            else: ok &= r.get(k) == v
        if ok: out.append(r)
    return sorted(out, key=lambda r: int(r['seed']))
f = lambda r, c: float(r[c]) if r.get(c, '') != '' else float('nan')
def mean(rows, c): return st.mean(f(r, c) for r in rows) if rows else float('nan')
def med(rows, c):  return st.median(f(r, c) for r in rows) if rows else float('nan')

E17, E18, E19, E20 = (load(f'e{i}_dbscale.csv') for i in (17, 18, 19, 20))
E8, E9, E10, E11, E12, E13 = (load(f'e{i}_dbscale.csv') for i in (8, 9, 10, 11, 12, 13))
CTRLK0 = load('e7_ctrlhdr.csv')
STD = dict(order='253', ssd_blocks='512')

def base(scheme, keys, il='all', order='253'):
    if order == '16':
        return sel(E9, scheme=scheme, keys=keys, order='16')
    if il != 'all':
        return sel(E11, scheme=scheme, keys=keys, il=il)
    src = E8 if keys == 'r64' else (E12 if scheme == 'NONE' else E10)
    return sel(src, scheme=scheme, keys=keys, il='all', **STD)

def ctrl_events(keys):
    rows = sel(CTRLK0, scheme='CTRL_CRC', keys='k0') if keys == 'k0' else \
           sel(E13, scheme='CTRL_CRC', keys=keys, guard='none', ssd_blocks='512')
    return sum(f(r, 'n_keyflip_real_tp') for r in rows), len(rows)

def det_ratio(rows, keys):
    den, n = ctrl_events(keys)
    if not rows or not n or not den: return float('nan')
    # per-run normalisation (seed sets may differ in size)
    return (sum(f(r, 'n_keyflip_real_tp') for r in rows) / len(rows)) / (den / n)

HDR = '| keys | arm | n | undet/run mean / med | missing | value | phantom | poisoned wr | lat µs | recov | pages | h | leaf det. ratio |'
SEP = '|' + '---|' * 13
def line(keys, arm, rows, det=True):
    if not rows: return f'| {keys} | {arm} | 0 | — | | | | | | | | | |'
    dr = det_ratio(rows, keys) if det else float('nan')
    return (f"| {keys} | {arm} | {len(rows)} | {mean(rows,'n_wrong_undetected'):.1f} / {med(rows,'n_wrong_undetected'):.0f} "
            f"| {mean(rows,'n_sdc_missing'):.1f} | {mean(rows,'n_sdc_value'):.1f} | {mean(rows,'n_sdc_phantom'):.1f} "
            f"| {mean(rows,'n_poisoned_writes'):.0f} | {mean(rows,'mean_op_latency_s')*1e6:.2f} "
            f"| {mean(rows,'n_recoveries'):.0f} | {mean(rows,'n_pages_allocated'):.0f} | {mean(rows,'tree_height'):.0f} "
            f"| {dr:.3f} |")

KEYS4 = ['k0', 'k16', 'k32', 'r64']
print('## E17 — all-level injection (λ 3e-3)\n'); print(HDR); print(SEP)
for k in KEYS4:
    print(line(k, 'NONE (base)', base('NONE', k), det=False))
    print(line(k, 'SANITY (base)', base('SANITY', k)))
    print(line(k, 'SANITY (rerun)', sel(E17, keys=k, il='all', rg='0', **STD)))
    print(line(k, '**SANITY+range**', sel(E17, keys=k, il='all', rg='1', **STD)))

print('\n## E17 — single-level injection: wrong answers per 1000 flips (undetected / total)\n')
print('| level | keys | NONE e11 | SANITY e11 (3 s) | SANITY rerun (5 s) | SANITY+range (5 s) | flips/run | range alarms/run (parent bad / child bad) | missing S→S+r |')
print('|---|---|---|---|---|---|---|---|---|')
def pf(rows):
    if not rows: return '—'
    fl = sum(f(r, 'n_flip_events') for r in rows)
    return f"{1000*sum(f(r,'n_wrong_undetected') for r in rows)/fl:.2f} / {1000*sum(f(r,'n_wrong_total') for r in rows)/fl:.2f}"
for il in ('internal', 'leaf'):
    for k in KEYS4:
        a = sel(E17, keys=k, il=il, rg='0', **STD); b = sel(E17, keys=k, il=il, rg='1', **STD)
        print(f"| {il} | {k} | {pf(base('NONE', k, il))} | {pf(base('SANITY', k, il))} | {pf(a)} | {pf(b)} "
              f"| {mean(b,'n_flip_events'):.0f} | {mean(b,'n_range_alarms'):.1f} ({mean(b,'n_range_parent_bad'):.1f} / {mean(b,'n_range_child_bad'):.1f}) "
              f"| {mean(a,'n_sdc_missing'):.1f} → {mean(b,'n_sdc_missing'):.1f} |")

print('\n## E17 — range-alarm bookkeeping (all arms with range on; means per run)\n')
print('| inject | keys | alarms | parent bad | child bad | restarts | giveups | ancestor recoveries | fp |')
print('|---|---|---|---|---|---|---|---|---|')
for il in ('all', 'internal', 'leaf'):
    for k in KEYS4:
        b = sel(E17, keys=k, il=il, rg='1', **STD)
        if b: print(f"| {il} | {k} | {mean(b,'n_range_alarms'):.1f} | {mean(b,'n_range_parent_bad'):.1f} | {mean(b,'n_range_child_bad'):.1f} "
                    f"| {mean(b,'n_range_restarts'):.1f} | {mean(b,'n_range_giveups'):.1f} | {mean(b,'n_range_anc_recoveries'):.1f} | {mean(b,'fp'):.1f} |")

print('\n## E17 — order 16, 200k keys (3 seeds)\n'); print(HDR); print(SEP)
for k in ('k0', 'k16'):
    print(line(k, 'NONE e9', base('NONE', k, order='16'), det=False))
    print(line(k, 'SANITY e9', base('SANITY', k, order='16'), det=False))
    print(line(k, 'SANITY rerun', sel(E17, keys=k, rg='0', order='16'), det=False))
    print(line(k, '**SANITY+range**', sel(E17, keys=k, rg='1', order='16'), det=False))

print('\n## E18 — alignment check\n'); print(HDR); print(SEP)
for k in ('k8', 'k16', 'k32'):
    print(line(k, 'NONE (base)', base('NONE', k), det=False))
    print(line(k, 'SANITY (base)', base('SANITY', k) or sel(E13, scheme='SANITY', keys=k, guard='none', ssd_blocks='512')))
    print(line(k, '**SANITY+align**', sel(E18, keys=k)))

print('\n## E19 — slack dummies\n')
print(HDR[:-1] + ' frac right / left |'); print(SEP + '---|')
for k in ('k8', 'k16', 'k32', 'r64'):
    sb = base('SANITY', k) if k != 'k8' else sel(E13, scheme='SANITY', keys=k, guard='none', ssd_blocks='512')
    if k == 'k8' and not sb: sb = sel(E10, scheme='SANITY', keys=k, **STD)
    print(line(k, 'NONE (base)', base('NONE', k), det=False) + ' |')
    print(line(k, 'SANITY (base)', sb) + ' |')
    for g in ('right', 'both'):
        rows = sel(E19, keys=k, sg=g)
        print(line(k, f'**slack {g}**', rows) + f" {mean(rows,'frac_guard_right'):.3f} / {mean(rows,'frac_guard_left'):.3f} |")

print('\n## E20 — free package\n'); print(HDR); print(SEP)
for k in KEYS4:
    print(line(k, 'NONE (base)', base('NONE', k), det=False))
    print(line(k, 'SANITY (base)', base('SANITY', k)))
    print(line(k, '**range+slack(R)**', sel(E20, keys=k, al=False)))
    if k in ('k16', 'k32'):
        print(line(k, '**range+slack(R)+align**', sel(E20, keys=k, al=True)))

# consistency: page count / height vs baseline SANITY, per seed
print('\n## Checks\n')
def pages_eq(rows, keys):
    b = {r['seed']: r for r in base('SANITY', keys)}
    if keys == 'k8' and not b: b = {r['seed']: r for r in sel(E10, scheme='SANITY', keys='k8', **STD)}
    bad = [(r['seed'], r['n_pages_allocated'], b[r['seed']]['n_pages_allocated'])
           for r in rows if r['seed'] in b and (r['n_pages_allocated'], r['tree_height']) != (b[r['seed']]['n_pages_allocated'], b[r['seed']]['tree_height'])]
    return sum(r['seed'] in b for r in rows), bad
for name, rows in (('E17 all', [r for r in E17 if r.get('inject_level') == 'all' and r['order'] == '253']),
                   ('E18', E18), ('E19', E19), ('E20', E20)):
    tot, bad = 0, []
    for k in ('k0', 'k8', 'k16', 'k32', 'r64'):
        n, b = pages_eq([r for r in rows if kd(r) == k], k); tot += n; bad += b
    print(f'- {name}: pages/height identical to baseline SANITY in {tot - len(bad)}/{tot} seed-matched rows; differing: {bad[:6]}')
# SANITY rerun vs baseline reproduction (all shared columns except run_id)
def repro(new, old):
    o = {(r['seed']): r for r in old}; n = d = 0
    for r in new:
        if r['seed'] not in o: continue
        n += 1
        cols = [c for c in o[r['seed']] if c != 'run_id']
        d += any(o[r['seed']][c] != r.get(c) for c in cols)
    return n, d
tot = dif = 0
for il in ('all', 'internal', 'leaf'):
    for k in KEYS4:
        n, d = repro(sel(E17, keys=k, il=il, rg='0', **STD), base('SANITY', k, il)); tot += n; dif += d
for k in ('k0', 'k16'):
    n, d = repro(sel(E17, keys=k, rg='0', order='16'), base('SANITY', k, order='16')); tot += n; dif += d
print(f'- E17 SANITY (range=0) rows vs existing SANITY rows, all shared columns except run_id: {tot} compared, {dif} differ')
