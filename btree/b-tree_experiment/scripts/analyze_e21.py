#!/usr/bin/env python3
"""analyze_e21.py — E21 tables (markdown) from results/e21_dbscale.csv + reference CSVs."""
import csv, statistics as st, sys
def load(p): return list(csv.DictReader(open(p)))
new = load('results/e21_dbscale.csv')
e8 = load('results/e8_dbscale.csv'); e13 = load('results/e13_dbscale.csv'); e10 = load('results/e10_dbscale.csv')

def f(r, c):
    v = r.get(c, '')
    return float(v) if v not in ('', None) else float('nan')

def summ(label, rows, mapped=True):
    n = len(rows)
    m = lambda c: sum(f(r, c) for r in rows) / n
    und = [f(r, 'n_wrong_undetected') for r in rows]
    if mapped and rows[0].get('key_map', 'none') != 'none':
        ph = sum(f(r, 'n_probes_hit') for r in rows) / max(1, sum(f(r, 'n_map_lookups_hit') for r in rows))
        pm = sum(f(r, 'n_probes_miss') for r in rows) / max(1, sum(f(r, 'n_map_lookups_miss') for r in rows))
        al = f"{m('n_map_alarms'):.1f}"; lm = f"{m('map_lmax'):.0f}"
        pr = f"{ph:.2f} / {pm:.2f}"
    else:
        al, lm, pr = '–', '–', '1 / 1'
    kl = sum(f(r, 'n_keyflip_single_leaf') for r in rows)
    kt = sum(f(r, 'n_keyflip_single_leaf_tp') for r in rows)
    det = f"{kt / kl:.3f}" if kl else '–'
    return (f"| {label} | {n} | {m('n_wrong_undetected'):.1f} / {st.median(und):g} | "
            f"{m('n_sdc_missing'):.1f} | {m('n_sdc_value'):.1f} | {m('n_sdc_phantom'):.1f} | "
            f"{al} | {pr} | {lm} | {m('mean_op_latency_s') * 1e6:.2f} | {m('n_recoveries'):.1f} | "
            f"{m('n_would_crash'):.1f} | {m('n_final_integrity_errors'):.1f} | "
            f"{m('n_pages_allocated'):.0f} | {m('tree_height'):.0f} | {m('n_internal_total'):.0f} | {det} |")

H = ("| config | n | undetected wrong / run (mean / median) | missing | value | phantom | map alarms | "
     "probes hit / miss | L_max | mean lat µs | recoveries | would_crash | final integ. err | pages | h | internal | leaf key-flip det. |\n"
     "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

def sel(rows, **kw):
    return [r for r in rows if all(r.get(k) == v for k, v in kw.items())]

print("### random64\n"); print(H)
for s in ('SANITY', 'NONE'):
    print(summ(f"ref E8 random64 {s} (1×, as-is)", sel(e8, key_dist='random64', scheme=s), False))
print(summ("ref E13 random64 SANITY guard=right (2×)", sel(e13, key_dist='random64', scheme='SANITY', guard='right'), False))
print(summ("ref E13 random64 SANITY guard=none, 2× geometry (1× tree)",
           [r for r in sel(e13, key_dist='random64', scheme='SANITY', guard='none') if r['ssd_blocks'] == '1024'], False))
for a in ('0.25', '0.5', '0.75'):
    for s in ('SANITY', 'NONE'):
        rows = [r for r in new if r['key_dist'] == 'random64' and r['scheme'] == s and r['key_map'] == 'hashdense'
                and abs(float(r['map_load']) - float(a)) < 1e-9]
        if rows: print(summ(f"**hashdense α={a} {s}** (2×)", rows))

print("\n### stride 2^32\n"); print(H)
print(summ("ref E10 stride-0 SANITY (1×)", sel(e10, scheme='SANITY', key_stride_log2='0', key_dist='stride'), False))
k32 = [r for r in sel(e13, scheme='SANITY', guard='none', key_stride_log2='32') if r['ssd_blocks'] == '512']
if k32: print(summ("ref E13 stride-2^32 SANITY as-is (1×)", k32, False))
for km, lab in (('shift', 'shift (1×)'), ('hashdense', 'hashdense α=0.5 (2×)')):
    rows = [r for r in new if r['key_stride_log2'] == '32' and r['key_map'] == km]
    if rows: print(summ(f"**{lab} SANITY**", rows))

# shift vs stride-0 exactness
print("\n### shift(k=32) vs E10 stride-0 SANITY, per seed\n")
skip = {'run_id', 'key_stride_log2', 'pred_sanity_rel', 'pred_sanity_exact'}
ref0 = {r['seed']: r for r in sel(e10, scheme='SANITY', key_stride_log2='0', key_dist='stride')}
for r in sorted([r for r in new if r['key_map'] == 'shift'], key=lambda r: r['seed']):
    q = ref0.get(r['seed'])
    if not q: continue
    diff = [c for c in q if c not in skip and q[c] != r.get(c)]
    print(f"- seed {r['seed']}: {len(q) - len(skip)} shared cols compared, {len(diff)} differ {diff[:10]}")
