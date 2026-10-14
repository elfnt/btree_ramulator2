#!/usr/bin/env python3
"""analyze_e8_12.py <e8|e9|e10|e11|e12> — compact headline tables for E8–E12."""
import csv, sys, math
from collections import defaultdict
def load(p):
    with open(p) as f: return list(csv.DictReader(f))
def F(r, c): return float(r[c]) if r[c] != '' else float('nan')
def mean(xs): xs = list(xs); return sum(xs) / len(xs) if xs else float('nan')
def group(rows, keys):
    g = defaultdict(list)
    for r in rows: g[tuple(r[k] for k in keys)].append(r)
    return g
def sdc(r): return F(r, 'n_wrong_undetected') / F(r, 'n_searches')
def edge(rows, seen_min=1000, thr=0.05):
    """largest bit b with Σseen_b > seen_min and Σtp_b/Σseen_b < thr (−1 if none)"""
    e = -1
    for b in range(64):
        s = sum(F(r, f'kb_seen_{b:02d}') for r in rows)
        t = sum(F(r, f'kb_tp_{b:02d}') for r in rows)
        if s > seen_min and t / s < thr: e = b
    return e
def tp(rows): return mean(F(r, 'tp') for r in rows)

which = sys.argv[1]
if which == 'e12':
    rows = load('results/e12_dbscale.csv')
    for r in rows:
        assert int(r['n_wrong_missing']) + int(r['n_wrong_value']) + int(r['n_wrong_phantom']) == int(r['n_wrong_total'])
        assert int(r['n_sdc_missing']) + int(r['n_sdc_value']) + int(r['n_sdc_phantom']) == int(r['n_wrong_undetected'])
    print('| stride | scheme | SDC | wrong_total | missing | value | phantom | sdc_missing | sdc_value | sdc_phantom | final_err |')
    print('|---|---|---|---|---|---|---|---|---|---|---|')
    g = group(rows, ['key_stride_log2', 'scheme'])
    for k in sorted(g, key=lambda x: (int(x[0]), x[1])):
        R = g[k]
        m = lambda c: mean(F(r, c) for r in R)
        print(f"| {k[0]} | {k[1]} | {mean(sdc(r) for r in R):.3e} | {m('n_wrong_total'):.1f} | {m('n_wrong_missing'):.1f} | "
              f"{m('n_wrong_value'):.1f} | {m('n_wrong_phantom'):.1f} | {m('n_sdc_missing'):.1f} | {m('n_sdc_value'):.1f} | "
              f"{m('n_sdc_phantom'):.1f} | {m('n_final_integrity_errors'):.0f} |")
elif which == 'e9':
    rows = load('results/e9_dbscale.csv')
    g = group(rows, ['order', 'key_stride_log2', 'scheme'])
    print('| order | stride | pages | internal | fill (keys/leaf) | pred edge log2(2^k·fill) | SANITY edge | SANITY/CTRL tp | (64−k)/64 | NONE SDC | SANITY SDC | CTRL SDC |')
    print('|---|---|---|---|---|---|---|---|---|---|---|---|')
    for o in sorted({k[0] for k in g}, key=int):
        for kk in sorted({k[1] for k in g}, key=int):
            S = g[(o, kk, 'SANITY')]; C = g[(o, kk, 'CTRL_CRC')]; N = g[(o, kk, 'NONE')]
            leaves = mean(F(r, 'n_nodes_level_0') for r in S)
            nkeys = F(S[0], 'prefill_keys') + mean(F(r, 'n_ops') for r in S) * (1 - F(S[0], 'read_ratio'))
            fill = nkeys / leaves
            pred = int(kk) + math.log2(fill)
            print(f"| {o} | {kk} | {mean(F(r,'n_pages_allocated') for r in S):.0f} | {mean(F(r,'n_internal_total') for r in S):.0f} | "
                  f"{fill:.1f} | {pred:.1f} | {edge(S)} | {tp(S)/tp(C):.3f} | {(64-int(kk))/64:.3f} | "
                  f"{mean(sdc(r) for r in N):.3e} | {mean(sdc(r) for r in S):.3e} | {mean(sdc(r) for r in C):.3e} |")
elif which == 'e10':
    rows = load('results/e10_dbscale.csv')
    g = group(rows, ['key_stride_log2', 'scheme'])
    print('| stride | scheme | SDC | mean lat (µs) | shadow_max (B) | B_int (12·n_int) | tp | fn | fp | ctrl_only | payload_only | mixed | ssd_hdr | final_err |')
    print('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    order = ['SANITY', 'CTRL_CRC', 'HYBRID', 'FULL_CRC']
    for k in sorted(g, key=lambda x: (int(x[0]), order.index(x[1]))):
        R = g[k]; m = lambda c: mean(F(r, c) for r in R)
        print(f"| {k[0]} | {k[1]} | {mean(sdc(r) for r in R):.3e} | {m('mean_op_latency_s')*1e6:.3f} | {m('shadow_bytes_used_max'):.0f} | "
              f"{12*m('n_internal_total'):.0f} | {m('tp'):.1f} | {m('fn'):.1f} | {m('fp'):.1f} | {m('n_corrupt_reads_ctrl_only'):.1f} | "
              f"{m('n_corrupt_reads_payload_only'):.1f} | {m('n_corrupt_reads_mixed'):.1f} | {m('n_corrupt_reads_ssd_header'):.1f} | {m('n_final_integrity_errors'):.0f} |")
elif which == 'e8':
    rows = load('results/e8_dbscale.csv')
    for r in rows: r['dist'] = r['key_dist'] + ('@' + r['key_stride_log2'] if r['key_dist'] == 'geomgap' else '')
    g = group(rows, ['dist', 'scheme'])
    print('| key_dist | pred_sanity_rel | pred_sanity_exact | SANITY/CTRL tp | SANITY edge | NONE SDC | SANITY SDC | CTRL SDC | FULL SDC |')
    print('|---|---|---|---|---|---|---|---|---|')
    for d in sorted({k[0] for k in g}):
        S = g[(d, 'SANITY')]; C = g[(d, 'CTRL_CRC')]
        print(f"| {d} | {mean(F(r,'pred_sanity_rel') for r in S):.3f} | {mean(F(r,'pred_sanity_exact') for r in S):.3f} | "
              f"{tp(S)/tp(C):.3f} | {edge(S)} | " + ' | '.join(f"{mean(sdc(r) for r in g[(d,s)]):.3e}" for s in ['NONE','SANITY','CTRL_CRC','FULL_CRC']) + ' |')
elif which == 'e11':
    rows = load('results/e11_dbscale.csv')
    g = group(rows, ['inject_level', 'key_stride_log2', 'scheme'])
    print('| inject | stride | scheme | λ | flips/run | key-single flips (Σseeds) | tp | fn | SDC | SANITY edge | SANITY/CTRL tp |')
    print('|---|---|---|---|---|---|---|---|---|---|---|')
    for k in sorted(g, key=lambda x: (x[0], int(x[1]), x[2])):
        R = g[k]; m = lambda c: mean(F(r, c) for r in R)
        e = edge(R) if k[2] == 'SANITY' else ''
        ratio = f"{tp(R)/tp(g[(k[0],k[1],'CTRL_CRC')]):.3f}" if k[2] == 'SANITY' else ''
        print(f"| {k[0]} | {k[1]} | {k[2]} | {R[0]['lambda_page']} | {m('n_flip_events'):.0f} | {sum(F(r,'n_keyflip_single_tp') for r in R):.0f}tp/{sum(F(r,'n_keyflip_single') for r in R):.0f}seen | "
              f"{m('tp'):.1f} | {m('fn'):.1f} | {mean(sdc(r) for r in R):.3e} | {e} | {ratio} |")
