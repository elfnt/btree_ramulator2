#!/usr/bin/env python3
"""Builds results/paper/paper.html from paper_data.json (+ Figure 1 SVG from the overview figure)."""
import json, os, re, math, html as H

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
D = json.load(open(ROOT + '/paper/paper_data.json'))
OUT = ROOT + '/paper/paper.html'

# ---------------------------------------------------------------- formatting
def sci(v, d=3):
    if v is None: return '—'
    if v == 0: return '0'
    m, e = ('%.*e' % (d - 1, v)).split('e')
    return '%se%d' % (m, int(e))
def sd_sci(v, s):
    return '0' if v == 0 else '%s ± %s' % (sci(v), sci(s, 2))
def f(v, d=2):
    return '—' if v is None else '%.*f' % (d, v)
def ints(v):
    return '—' if v is None else '{:,}'.format(int(round(v)))
def pct(v):
    if v is None: return '—'
    if abs(v) < 1e-9: return '(base)'
    return '%+.1f %%' % v
def mult(v):
    return '—' if v is None else '%.2f×' % v

def esc(s): return H.escape(str(s), quote=True)

def table(head, rows, num_from=1, cls='', text_cols=()):
    """head: list of header strings (may contain HTML); rows: list of lists of cell strings."""
    isn = lambda i: i >= num_from and i not in text_cols
    th = ''.join('<th%s>%s</th>' % (' class="n"' if isn(i) else '', h) for i, h in enumerate(head))
    body = []
    for r in rows:
        tds = []
        for i, c in enumerate(r):
            tds.append('<td%s>%s</td>' % (' class="n"' if isn(i) else '', c))
        body.append('<tr>' + ''.join(tds) + '</tr>')
    return '<div class="tw%s"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
        (' ' + cls) if cls else '', th, ''.join(body))

TNUM = [0]
def tcap(text):
    TNUM[0] += 1
    return '<p class="tcap"><span class="lbl">Table %d.</span> %s</p>' % (TNUM[0], text), TNUM[0]

def tblock(caption, head, rows, num_from=1, text_cols=()):
    cap, n = tcap(caption)
    return '<div class="tblock" id="t%d">%s%s</div>' % (n, cap, table(head, rows, num_from, '', text_cols))

# ---------------------------------------------------------------- charts
CHARTS = []
def chart(cid, spec, fmt_x=None, fmt_y=None):
    """spec keys: aria, x{type,label,cats?,ticks?,tickLabels?,min?,max?}, y{...,fmt}, series[{name,slot,pts,line?,hollow?,dash?,ref?}]"""
    spec['id'] = cid
    CHARTS.append(spec)
    # details table twin
    xs = []
    for s in spec['series']:
        for p in s['pts']:
            if p[0] not in xs: xs.append(p[0])
    if spec['x']['type'] != 'cat':
        xs.sort()
    head = [esc(spec['x']['label'])] + [esc(s['name']) for s in spec['series']]
    rows = []
    for x in xs:
        if spec['x']['type'] == 'cat':
            xl = spec['x']['cats'][x]
        else:
            xl = fmt_x(x) if fmt_x else str(x)
        r = [xl if '<sup>' in xl else esc(xl)]
        for s in spec['series']:
            v = next((p for p in s['pts'] if p[0] == x), None)
            if v is None: r.append('—')
            else:
                t = fmt_y(v[1]) if fmt_y else str(v[1])
                if len(v) > 2 and v[2]: t += ' <span class="mu">(' + esc(v[2]) + ')</span>'
                r.append(t)
        rows.append(r)
    det = '<details><summary>Data</summary>%s</details>' % table(head, rows)
    ttl = spec.get('title', '')
    return ('<div class="panel">%s<div class="chart" id="%s" data-chart="%d"></div>%s</div>' %
            (('<p class="ptitle">%s</p>' % ttl) if ttl else '', cid, len(CHARTS) - 1, det))

FNUM = [0]
def figure(panels, caption, cols=2):
    FNUM[0] += 1
    n = FNUM[0]
    return ('<figure class="fig" id="f%d"><div class="panels c%d">%s</div>'
            '<figcaption><span class="lbl">Figure %d.</span> %s</figcaption></figure>' % (
                n, cols if len(panels) > 1 else 1, ''.join(panels), n, caption)), n

NOTES = []
def fn(text):
    NOTES.append(text)
    k = len(NOTES)
    return '<sup class="fn"><a href="#n%d" id="r%d">%d</a></sup>' % (k, k, k)

SLOT = {'NONE': 1, 'SANITY': 2, 'CTRL_CRC': 3, 'FULL_CRC': 4}
PSLOT = {'BY_LEVEL': 1, 'LRU': 2, 'BY_HOTNESS': 3, 'RANDOM': 4}
def nz(v): return v

# ================================================================ E1
E1 = D['E1']
lams = sorted(set(r['lambda'] for r in E1))
def e1(s, l): return next(r for r in E1 if r['scheme'] == s and r['lambda'] == l)
def lamfmt(l):
    m, e = ('%.0e' % l).split('e')
    return ('%s×10^%d' % (m, int(e))).replace('1×', '') if m != '1' else '10^%d' % int(e)
def lamtxt(l):
    m, e = ('%.0e' % l).split('e'); e = int(e)
    return ('10<sup>−%d</sup>' % -e) if m == '1' else ('%s×10<sup>−%d</sup>' % (m, -e))

c_e1_sdc = chart('c-e1-sdc', {
    'title': '(a) Silent-corruption rate',
    'aria': 'Line chart, log-log: SDC rate versus flip rate lambda for NONE, SANITY and CTRL_CRC.',
    'x': {'type': 'log', 'label': 'λ (flips / page / s)', 'min': 1e-5, 'max': 3e-2, 'fmt': 'sci'},
    'y': {'type': 'log', 'label': 'SDC rate (wrong answers / search)', 'fmt': 'sci'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[l, e1(s, l)['sdc']] for l in lams]} for s in ['NONE', 'SANITY', 'CTRL_CRC']]
}, lamtxt, sci)
c_e1_lat = chart('c-e1-lat', {
    'title': '(b) Mean operation latency',
    'aria': 'Line chart: mean op latency in microseconds versus lambda for the four schemes.',
    'x': {'type': 'log', 'label': 'λ (flips / page / s)', 'min': 1e-5, 'max': 3e-2, 'fmt': 'sci'},
    'y': {'type': 'lin', 'label': 'mean op latency (µs)', 'min': 0, 'fmt': 'f2'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[l, e1(s, l)['lat_us']] for l in lams]} for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']]
}, lamtxt, lambda v: f(v, 2))

def e1row(s, l):
    r = e1(s, l)
    return [lamtxt(l), s, sd_sci(r['sdc'], r['sdc_sd']), ints(r['shadow_bytes']), ints(r['pages']),
            f(r['lat_us'], 2) + ' ± ' + f(r['lat_sd'], 2), pct(r['overhead_pct'])]
e1_rows = [e1row(s, l) for l in [1e-5, 3e-3, 3e-2] for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']]

n3 = e1('NONE', 3e-3); c3 = e1('CTRL_CRC', 3e-3); s3 = e1('SANITY', 3e-3); f3 = e1('FULL_CRC', 3e-3)
red = 1 - c3['sdc'] / n3['sdc']
cost_ratio = (c3['lat_us'] - n3['lat_us']) / (f3['lat_us'] - n3['lat_us'])
n0 = e1('NONE', 1e-5); c0 = e1('CTRL_CRC', 1e-5); f0 = e1('FULL_CRC', 1e-5)
floor_ratio = (c0['lat_us'] - n0['lat_us']) / (f0['lat_us'] - n0['lat_us'])

# ================================================================ E2
E2 = D['E2']['main']
budgets = ['0', '128', '256', '512', '1024', '4096', '16384', '69312', 'inf']
bud_lbl = ['0', '128', '256', '512', '1 K', '4 K', '16 K', '69 K (all)', '∞']
def e2(sch, pol, b): return next(r for r in E2 if r['scheme'] == sch and r['policy'] == pol and r['budget_bytes'] == b)
c_e2 = chart('c-e2', {
    'aria': 'Line chart: SDC rate versus reliable-memory budget for four eviction policies, CTRL_CRC, 1M keys.',
    'x': {'type': 'cat', 'label': 'budget (bytes of reliable memory)', 'cats': bud_lbl[:8]},
    'y': {'type': 'log', 'label': 'SDC rate', 'fmt': 'sci'},
    'series': [{'name': p, 'slot': PSLOT[p], 'pts': [[i, e2('CTRL_CRC', p, b)['sdc']] for i, b in enumerate(budgets[:8])]} for p in PSLOT],
    'endLabels': False
}, None, sci)

def cell(r):
    return '%s<br><span class="mu">%s µs (%s)</span>' % (sci(r['sdc']), f(r['lat_us'], 2), pct(r['overhead_pct']))
e2_rows = []
for i, b in enumerate(budgets):
    rr = e2('CTRL_CRC', 'BY_LEVEL', b)
    e2_rows.append([bud_lbl[i], ints(rr['shadow_bytes']), ints(rr['pages'])] + [cell(e2('CTRL_CRC', p, b)) for p in PSLOT])
fb = e2('FULL_CRC', 'BY_LEVEL', 'inf')
b0 = e2('CTRL_CRC', 'BY_LEVEL', '0'); b512 = e2('CTRL_CRC', 'BY_LEVEL', '512')

RS = D['E2']['rescaled']
nominal = ['0', '0.1', '0.25', '0.5', '0.75', '1', '2', '4']
e2r_panels = []
cfgname = {'E2B': 'E2b', 'E2C': 'E2c', 'E2D': 'E2d', 'E2E': 'E2e'}
for k in ['E2B', 'E2C', 'E2D', 'E2E']:
    c = RS[k]
    xs = sorted(set(r['x_B_int'] for r in c['rows'] if r['budget_bytes'] != 'inf'))[:8]
    ser = []
    for p in PSLOT:
        pts = []
        for i, x in enumerate(xs):
            r = next(r for r in c['rows'] if r['policy'] == p and r['x_B_int'] == x and r['budget_bytes'] != 'inf')
            pts.append([i, r['sdc']])
        ser.append({'name': p, 'slot': PSLOT[p], 'pts': pts})
    ttl = '%s: order %d, %s keys, %s internal nodes, h = %d' % (cfgname[k], c['order'], '{:,}'.format(c['keys']), ints(c['n_internal']), c['tree_height'])
    e2r_panels.append(chart('c-' + k.lower(), {
        'title': ttl,
        'aria': 'Line chart: SDC rate versus budget in multiples of B_int for ' + cfgname[k] + ', four policies.',
        'x': {'type': 'cat', 'label': 'budget (× B_int)', 'cats': nominal, 'mark': 5, 'markLabel': 'B_int'},
        'y': {'type': 'log', 'label': 'SDC rate', 'fmt': 'sci'},
        'series': ser, 'endLabels': False
    }, None, sci))

knee_rows = []
klbl2 = {5000000: '5 M', 2000000: '2 M'}
for kr in D['E2']['knee']:
    c = RS[kr['config']]
    rows = c['rows']
    xs = sorted(set(r['x_B_int'] for r in rows if r['budget_bytes'] != 'inf'))
    xk = xs[5]
    bl = next(r for r in rows if r['policy'] == 'BY_LEVEL' and r['x_B_int'] == xk)
    lr = next(r for r in rows if r['policy'] == 'LRU' and r['x_B_int'] == xk)
    full = max((r for r in rows if r['policy'] == 'BY_LEVEL' and r['budget_bytes'] != 'inf'), key=lambda r: float(r['budget_bytes']))
    knee_rows.append(['%s <span class="mu">o%d, %s</span>' % (cfgname[kr['config']], kr['order'], klbl2[kr['keys']]), ints(c['pages']), ints(kr['n_internal']),
                      ints(kr['knee_budget_bytes']), '%.2f %%' % kr['knee_pct_B_full'],
                      sci(kr['sdc_BY_LEVEL']), sci(kr['sdc_LRU']), sci(kr['sdc_BY_HOTNESS']), sci(kr['sdc_RANDOM']),
                      '%.1f×' % kr['lru_over_by_level'],
                      '%s<br><span class="mu">%s</span>' % (f(bl['lat_us'], 2), pct(bl['overhead_pct'])),
                      '%s<br><span class="mu">%s</span>' % (f(lr['lat_us'], 2), pct(lr['overhead_pct'])),
                      '%s<br><span class="mu">%s</span>' % (f(full['lat_us'], 2), pct(full['overhead_pct']))])
nint = [RS[k]['n_internal'] for k in ['E2B', 'E2C', 'E2D', 'E2E']]
nint_range = nint[-1] / nint[0]

# ================================================================ E3
E3 = D['E3']
modes = ['uniform', 'hammer', 'col_b128', 'col_b3000']
mode_lbl = ['uniform', 'hammer', 'column, byte 128 (keys[])', 'column, byte 3000 (values[])']
mode_short = ['uniform', 'hammer', 'col. byte 128', 'col. byte 3000']
def e3(m, s): return next(r for r in E3 if r['mode'] == m and r['scheme'] == s)
c_e3 = chart('c-e3', {
    'aria': 'Dot plot: undetected wrong answers per effective flip by fault mode for NONE, SANITY and CTRL_CRC, log scale.',
    'x': {'type': 'cat', 'label': 'fault mode', 'cats': mode_short},
    'y': {'type': 'log', 'label': 'undetected wrong answers per effective flip', 'fmt': 'sci'},
    'series': [{'name': s, 'slot': SLOT[s], 'line': False, 'pts': [[i, e3(m, s)['wrong_per_eff_flip']] for i, m in enumerate(modes)]} for s in ['NONE', 'SANITY', 'CTRL_CRC']],
    'endLabels': False
}, None, lambda v: sci(v))
e3_rows = []
for i, m in enumerate(modes):
    for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']:
        r = e3(m, s)
        e3_rows.append([mode_lbl[i] if s == 'NONE' else '', s, f(r['effective_flips'], 1), sd_sci(r['sdc'], r['sdc_sd']),
                        f(r['wrong_per_eff_flip'], 4), ints(r['shadow_bytes']), ints(r['pages']),
                        f(r['lat_us'], 2) + ' ± ' + f(r['lat_sd'], 2), pct(r['overhead_pct'])])

# ================================================================ E4
E4 = D['E4']
thetas = ['EVERY_READ', '0.1', '0.3', '1', '3', '10', '30', '100']
th_lbl = ['every read', '0.1', '0.3', '1', '3', '10', '30', '100']
def e4(s, t): return next(r for r in E4 if r['scheme'] == s and str(r['theta_s']) == t)
# check theta encoding
_ths = sorted(set(str(r['theta_s']) for r in E4))
def e4k(s, t):
    for r in E4:
        if r['scheme'] != s: continue
        ts = str(r['theta_s'])
        if ts == t or (t != 'EVERY_READ' and ts != 'EVERY_READ' and abs(float(ts) - float(t)) < 1e-9): return r
    raise KeyError((s, t))
c_e4_sdc = chart('c-e4-sdc', {
    'title': '(a) Silent-corruption rate',
    'aria': 'Line chart: SDC rate versus verification period theta for CTRL_CRC and FULL_CRC, log scale.',
    'x': {'type': 'cat', 'label': 'verification period θ (s)', 'cats': th_lbl},
    'y': {'type': 'log', 'label': 'SDC rate', 'fmt': 'sci'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[i, e4k(s, t)['sdc']] for i, t in enumerate(thetas)]} for s in ['CTRL_CRC', 'FULL_CRC']]
}, None, sci)
c_e4_lat = chart('c-e4-lat', {
    'title': '(b) Mean operation latency',
    'aria': 'Line chart: mean op latency versus theta for CTRL_CRC and FULL_CRC.',
    'x': {'type': 'cat', 'label': 'verification period θ (s)', 'cats': th_lbl},
    'y': {'type': 'lin', 'label': 'mean op latency (µs)', 'min': 0, 'fmt': 'f2', 'refLine': {'v': 10.501, 'label': 'NONE 10.50 µs'}},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[i, e4k(s, t)['lat_us']] for i, t in enumerate(thetas)]} for s in ['CTRL_CRC', 'FULL_CRC']]
}, None, lambda v: f(v, 2))
e4_rows = []
for s in ['CTRL_CRC', 'FULL_CRC']:
    for i, t in enumerate(thetas):
        r = e4k(s, t)
        e4_rows.append([th_lbl[i], s, sd_sci(r['sdc'], r['sdc_sd']), f(r['recall'], 4), ints(r['shadow_bytes']), ints(r['pages']),
                        f(r['lat_us'], 2) + ' ± ' + f(r['lat_sd'], 2), pct(r['dlat_vs_every_read_pct']) if r['dlat_vs_every_read_pct'] else '(base)', pct(r['overhead_pct'])])

# ================================================================ E5
E5 = D['E5']
rpbs = [2048, 720, 512, 256, 128, 64, 32]
def e5(s, rpb): return next(r for r in E5 if r['scheme'] == s and r['ram_rows_per_bank'] == rpb)
caps = sorted(set(r['capacity_pages'] for r in E5))
def capfmt(c): return '{:,}'.format(int(c))
c_e5_sdc = chart('c-e5-sdc', {
    'title': '(a) Damage per injected flip',
    'aria': 'Line chart, log-log: undetected wrong answers per injected flip versus DRAM capacity in pages for NONE, SANITY and CTRL_CRC.',
    'x': {'type': 'log', 'label': 'DRAM capacity (pages; tree ≈ 5,763)', 'ticks': [256, 1024, 4096, 16384], 'tickLabels': ['256', '1 K', '4 K', '16 K']},
    'y': {'type': 'log', 'label': 'undetected wrong answers per flip', 'fmt': 'sci'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[e5(s, rpb)['capacity_pages'], e5(s, rpb)['sdc_per_flip']] for rpb in sorted(rpbs)]} for s in ['NONE', 'SANITY', 'CTRL_CRC']]
}, capfmt, lambda v: sci(v))
c_e5_lat = chart('c-e5-lat', {
    'title': '(b) Mean operation latency',
    'aria': 'Line chart: mean op latency versus DRAM capacity for the four schemes.',
    'x': {'type': 'log', 'label': 'DRAM capacity (pages; tree ≈ 5,763)', 'ticks': [256, 1024, 4096, 16384], 'tickLabels': ['256', '1 K', '4 K', '16 K']},
    'y': {'type': 'lin', 'label': 'mean op latency (µs)', 'min': 0, 'fmt': 'f2'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[e5(s, rpb)['capacity_pages'], e5(s, rpb)['lat_us']] for rpb in sorted(rpbs)]} for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']]
}, capfmt, lambda v: f(v, 2))
e5_rows = []
for rpb in rpbs:
    for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']:
        r = e5(s, rpb)
        e5_rows.append([capfmt(r['capacity_pages']) if s == 'NONE' else '', s, f(r['n_flip_events'], 1), sd_sci(r['sdc'], r['sdc_sd']),
                        f(r['sdc_per_flip'], 4), ints(r['shadow_bytes']), ints(r['pages']),
                        f(r['lat_us'], 2) + ' ± ' + f(r['lat_sd'], 2), pct(r['overhead_pct'])])
gap_full = e5('FULL_CRC', 2048)['lat_us'] / e5('CTRL_CRC', 2048)['lat_us'] - 1
gap_small = e5('FULL_CRC', 32)['lat_us'] / e5('CTRL_CRC', 32)['lat_us'] - 1

# ================================================================ E6
E6a = D['E6a']['rows']; E6b = D['E6b']['rows']
orders = [8, 32, 128, 253]; keysz = [200000, 1000000, 3000000, 5000000]
def e6a(s, o): return next(r for r in E6a if r['scheme'] == s and r['order'] == o)
def e6b(s, k): return next(r for r in E6b if r['scheme'] == s and r['keys'] == k)
klbl = {200000: '200 K', 1000000: '1 M', 3000000: '3 M', 5000000: '5 M'}
c_e6a_sdc = chart('c-e6a-sdc', {
    'title': '(a) E6a: SDC rate vs node order (200 K keys)',
    'aria': 'Line chart: SDC rate versus B+tree order for NONE and CTRL_CRC, log scale.',
    'x': {'type': 'log', 'label': 'order (max keys per node)', 'ticks': orders, 'tickLabels': [str(o) for o in orders]},
    'y': {'type': 'log', 'label': 'SDC rate', 'fmt': 'sci'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[o, e6a(s, o)['sdc']] for o in orders]} for s in ['NONE', 'CTRL_CRC']]
}, str, sci)
c_e6a_lat = chart('c-e6a-lat', {
    'title': '(b) E6a: latency vs node order',
    'aria': 'Line chart: mean op latency versus order for NONE, CTRL_CRC and FULL_CRC.',
    'x': {'type': 'log', 'label': 'order (max keys per node)', 'ticks': orders, 'tickLabels': [str(o) for o in orders]},
    'y': {'type': 'lin', 'label': 'mean op latency (µs)', 'min': 0, 'fmt': 'f2'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[o, e6a(s, o)['lat_us']] for o in orders]} for s in ['NONE', 'CTRL_CRC', 'FULL_CRC']]
}, str, lambda v: f(v, 2))
c_e6b_sdc = chart('c-e6b-sdc', {
    'title': '(c) E6b: SDC rate vs tree size (order 253)',
    'aria': 'Line chart: SDC rate versus number of keys for NONE and CTRL_CRC, log scale.',
    'x': {'type': 'log', 'label': 'keys', 'ticks': keysz, 'tickLabels': [klbl[k] for k in keysz]},
    'y': {'type': 'log', 'label': 'SDC rate', 'fmt': 'sci'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[k, e6b(s, k)['sdc']] for k in keysz]} for s in ['NONE', 'CTRL_CRC']]
}, lambda k: klbl[k], sci)
c_e6b_lat = chart('c-e6b-lat', {
    'title': '(d) E6b: latency vs tree size',
    'aria': 'Line chart: mean op latency versus number of keys for NONE, CTRL_CRC and FULL_CRC.',
    'x': {'type': 'log', 'label': 'keys', 'ticks': keysz, 'tickLabels': [klbl[k] for k in keysz]},
    'y': {'type': 'lin', 'label': 'mean op latency (µs)', 'min': 0, 'fmt': 'f2'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[k, e6b(s, k)['lat_us']] for k in keysz]} for s in ['NONE', 'CTRL_CRC', 'FULL_CRC']]
}, lambda k: klbl[k], lambda v: f(v, 2))
cra = {c['order']: c for c in D['E6a']['cost_ratio']}
crb = {c['keys']: c for c in D['E6b']['cost_ratio']}
e6_rows = []
for o in orders:
    for s in ['NONE', 'CTRL_CRC', 'FULL_CRC']:
        r = e6a(s, o)
        cr = cra[o] if s == 'CTRL_CRC' else None
        e6_rows.append(['E6a' if (o == 8 and s == 'NONE') else '', ('order %d' % o) if s == 'NONE' else '', s, ints(r['pages']), '%d' % r['tree_height'],
                        ints(r['n_internal']) if r['n_internal'] else '—', sd_sci(r['sdc'], r['sdc_sd']), ints(r['shadow_bytes']),
                        f(r['lat_us'], 2), pct(r['overhead_pct']),
                        ('%.3f' % cr['ctrl_over_full_cost_ratio']) if cr else '', ('%.3f' % cr['predicted_ratio_read_weighted_ctrl_len_over_4096']) if cr else ''])
for k in keysz:
    for s in ['NONE', 'CTRL_CRC', 'FULL_CRC']:
        r = e6b(s, k)
        cr = crb[k] if s == 'CTRL_CRC' else None
        e6_rows.append(['E6b' if (k == 200000 and s == 'NONE') else '', ('%s keys' % klbl[k]) if s == 'NONE' else '', s, ints(r['pages']), '%d' % r['tree_height'],
                        ints(r['n_internal']) if r['n_internal'] else '—', sd_sci(r['sdc'], r['sdc_sd']), ints(r['shadow_bytes']),
                        f(r['lat_us'], 2), pct(r['overhead_pct']),
                        ('%.3f' % cr['ctrl_over_full_cost_ratio']) if cr else '', ('%.3f' % cr['predicted_ratio_read_weighted_ctrl_len_over_4096']) if cr else ''])

# ================================================================ E7
E7 = D['E7']['rows']
ks = [0, 8, 16, 24, 32]
def e7(s, k): return next(r for r in E7 if r['scheme'] == s and r['stride_log2'] == k)
c_e7_ratio = chart('c-e7-ratio', {
    'title': '(a) SANITY detection relative to CTRL_CRC',
    'aria': 'Line chart: SANITY to CTRL_CRC detection ratio versus key stride exponent k, with the model (64 minus k) over 64.',
    'x': {'type': 'lin', 'label': 'key stride exponent k (adjacent keys 2^k apart)', 'min': 0, 'max': 32, 'ticks': ks, 'tickLabels': [str(k) for k in ks]},
    'y': {'type': 'lin', 'label': 'detections, SANITY / CTRL_CRC', 'min': 0.4, 'max': 1.0, 'fmt': 'f3'},
    'series': [{'name': 'SANITY (measured)', 'slot': 2, 'pts': [[k, e7('SANITY', k)['detection_ratio_vs_ctrl']] for k in ks]},
               {'name': 'model (64−k)/64', 'ref': True, 'pts': [[k, (64 - k) / 64] for k in ks]}]
}, str, lambda v: '%.3f' % v)
c_e7_sdc = chart('c-e7-sdc', {
    'title': '(b) Silent-corruption rate',
    'aria': 'Line chart: SDC rate versus key stride exponent for NONE, SANITY and CTRL_CRC, log scale.',
    'x': {'type': 'lin', 'label': 'key stride exponent k', 'min': 0, 'max': 32, 'ticks': ks, 'tickLabels': [str(k) for k in ks]},
    'y': {'type': 'log', 'label': 'SDC rate', 'fmt': 'sci'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[k, e7(s, k)['sdc']] for k in ks]} for s in ['NONE', 'SANITY', 'CTRL_CRC']]
}, str, sci)
e7_rows = []
for k in ks:
    for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']:
        r = e7(s, k)
        e7_rows.append([('2<sup>%d</sup>' % k) if s == 'NONE' else '', s, sd_sci(r['sdc'], r['sdc_sd']), f(r['tp'], 1),
                        ('%.3f' % r['detection_ratio_vs_ctrl']) if s == 'SANITY' else '', ('%.3f' % r['predicted_ratio']) if s == 'SANITY' else '',
                        ints(r['shadow_bytes']), ints(r['pages']), f(r['lat_us'], 2) + ' ± ' + f(r['lat_sd'], 2), pct(r['overhead_pct'])])
bz = D['E7']['blind_zone_read_weighted_SUMMARY_14_5']
bz_rows = [['2<sup>%d</sup>' % k, str(bz['edge_bit'][str(k)]), '%d' % k, '%.1f' % bz['predicted_internal_separator_gap_log2'][str(k)]] for k in ks]
maxdev = max(abs(e7('SANITY', k)['detection_ratio_vs_ctrl'] - (64 - k) / 64) for k in ks)

# ================================================================ E7ext
X = D['E7ext']
def xr(prefix, s, ks_='stride2^32'):
    return next(r for r in X if r['arm'].startswith(prefix) and r['scheme'] == s and (ks_ is None or r['key_set'].startswith(ks_)))
g = [xr('none', 'SANITY'), xr('grid k=31', 'SANITY'), xr('grid k=30', 'SANITY'), xr('grid k=29', 'SANITY')]
gc = [xr('none', 'CTRL_CRC'), xr('grid k=31', 'CTRL_CRC'), xr('grid k=30', 'CTRL_CRC'), xr('grid k=29', 'CTRL_CRC')]
adjR = xr('adjacent right', 'SANITY'); adjB = xr('adjacent both', 'SANITY')
shf = xr('shift', 'SANITY', None)
r64 = xr('none (plain random64', 'SANITY', 'random64'); r64c = xr('none (plain random64', 'CTRL_CRC', 'random64')
hsh = [xr('hash α=0.25', 'SANITY', None), xr('hash α=0.5', 'SANITY', None), xr('hash α=0.75', 'SANITY', None)]
def pm(r): return round(r['page_multiplier'], 2)
e7_shift_ratio = e7('SANITY', 0)['detection_ratio_vs_ctrl']
c_x_ratio = chart('c-x-ratio', {
    'title': '(a) SANITY detection ratio vs page cost',
    'aria': 'Chart: SANITY to CTRL_CRC real-key detection ratio versus page multiplier for grid dummies, adjacent dummies and shift, with the model line.',
    'x': {'type': 'log', 'label': 'pages relative to plain stride-2^32 tree', 'ticks': [1, 2, 4, 8], 'tickLabels': ['1×', '2×', '4×', '8×'], 'min': 0.9, 'max': 9},
    'y': {'type': 'lin', 'label': 'detections, SANITY / CTRL_CRC', 'min': 0.4, 'max': 1.0, 'fmt': 'f3'},
    'series': [{'name': 'grid dummies', 'slot': 1, 'pts': [[pm(r), r['detection_ratio'], ['no dummies', 'k = 31, 1 per key', 'k = 30, 3 per key', 'k = 29, 7 per key'][i]] for i, r in enumerate(g)]},
               {'name': 'adjacent dummies', 'slot': 2, 'line': False, 'pts': [[pm(adjR), adjR['detection_ratio'], 'K+1'], [pm(adjB), adjB['detection_ratio'], 'K±1']]},
               {'name': 'shift', 'slot': 3, 'line': False, 'hollow': True, 'pts': [[1.0, e7_shift_ratio, 'stride-0 page-level ratio, E7']]},
               {'name': 'model (64−k_eff)/64', 'ref': True, 'pts': [[pm(r), r['predicted_ratio']] for r in g]}],
    'endLabels': False
}, lambda v: '%.2f×' % v, lambda v: '%.3f' % v)
c_x_tp = chart('c-x-tp', {
    'title': '(b) Real-key flips detected per run, grid arm',
    'aria': 'Line chart: real-key flip detections per run for SANITY and CTRL_CRC versus page multiplier under grid dummies.',
    'x': {'type': 'log', 'label': 'pages relative to plain stride-2^32 tree', 'ticks': [1, 2, 4, 8], 'tickLabels': ['1×', '2×', '4×', '8×'], 'min': 0.9, 'max': 9},
    'y': {'type': 'lin', 'label': 'real-key flips detected per run', 'min': 0, 'fmt': 'f1'},
    'series': [{'name': 'SANITY', 'slot': 2, 'pts': [[pm(r), r['n_keyflip_real_tp']] for r in g]},
               {'name': 'CTRL_CRC', 'slot': 3, 'pts': [[pm(r), r['n_keyflip_real_tp']] for r in gc]}]
}, lambda v: '%.2f×' % v, lambda v: f(v, 1))
hm = hsh[1]
c_x_sdc = chart('c-x-sdc', {
    'title': '(a) End-to-end SANITY silent-corruption rate',
    'aria': 'Chart: SANITY SDC rate versus page multiplier for grid dummies, adjacent dummies, shift and hash mapping.',
    'x': {'type': 'log', 'label': 'pages relative to the arm’s unpadded tree', 'ticks': [1, 2, 4, 8], 'tickLabels': ['1×', '2×', '4×', '8×'], 'min': 0.9, 'max': 9},
    'y': {'type': 'lin', 'label': 'SDC rate, SANITY (×10^-3)', 'min': 0, 'max': 2.0e-3, 'scale': 1e3, 'fmt': 'sci'},
    'series': [{'name': 'grid dummies', 'slot': 1, 'pts': [[pm(r), r['sdc'], ['no dummies', 'k = 31', 'k = 30', 'k = 29 (h = 4)'][i]] for i, r in enumerate(g)]},
               {'name': 'adjacent dummies', 'slot': 2, 'line': False, 'pts': [[pm(adjR), adjR['sdc'], 'K+1'], [pm(adjB), adjB['sdc'], 'K±1']]},
               {'name': 'shift', 'slot': 3, 'line': False, 'pts': [[1.0, shf['sdc'], 'K>>32']]},
               {'name': 'hash mapping', 'slot': 4, 'dash': True, 'pts': [[1.0, r64['sdc'], 'random64, unmapped'], [2.0, hm['sdc'], 'α = 0.5']]}],
    'endLabels': False
}, lambda v: '%.2f×' % v, sci)
c_x_lat = chart('c-x-lat', {
    'title': '(b) SANITY latency vs page cost',
    'aria': 'Chart: SANITY mean op latency multiplier versus page multiplier for each arm, with a proportional reference line.',
    'x': {'type': 'log', 'label': 'pages relative to the arm’s unpadded tree', 'ticks': [1, 2, 4, 8], 'tickLabels': ['1×', '2×', '4×', '8×'], 'min': 0.9, 'max': 9},
    'y': {'type': 'log', 'label': 'latency relative to plain SANITY', 'ticks': [1, 2, 4, 8], 'tickLabels': ['1×', '2×', '4×', '8×'], 'min': 0.9, 'max': 9, 'fmt': 'x2'},
    'series': [{'name': 'grid dummies', 'slot': 1, 'pts': [[pm(r), r['lat_multiplier_vs_sanity_1x']] for r in g]},
               {'name': 'adjacent dummies', 'slot': 2, 'line': False, 'pts': [[pm(adjR), adjR['lat_multiplier_vs_sanity_1x']], [pm(adjB), adjB['lat_multiplier_vs_sanity_1x']]]},
               {'name': 'shift', 'slot': 3, 'line': False, 'pts': [[1.0, shf['lat_multiplier_vs_sanity_1x'], 'vs stride-2^32 SANITY']]},
               {'name': 'hash mapping', 'slot': 4, 'dash': True, 'pts': [[1.0, 1.0, 'random64, unmapped'], [2.0, hm['lat_multiplier_vs_sanity_1x'], 'α = 0.5']]},
               {'name': 'latency ∝ pages', 'ref': True, 'pts': [[1, 1], [8, 8]]}],
    'endLabels': False
}, lambda v: '%.2f×' % v, lambda v: '%.2f×' % v)

def armname(r):
    a = r['arm']
    a = a.replace(' (=E13 mid, 1 dummy)', ', 1 dummy').replace(' (3 dummies)', ', 3 dummies').replace(' (7 dummies)', ', 7 dummies')
    a = a.replace(' (plain random64 baseline)', ', random64').replace(' (E13)', '').replace(' (E21)', '')
    return a
x_rows = []
for r in X:
    ratio = ''
    if r.get('detection_ratio') is not None:
        ratio = '%.3f' % r['detection_ratio']
        if r.get('predicted_ratio') is not None: ratio += ' <span class="mu">(%.3f)</span>' % r['predicted_ratio']
    x_rows.append([esc(armname(r)), r['scheme'],
                   '%s<br><span class="mu">%.2f×</span>' % (ints(r['pages']), r['page_multiplier']), ints(r['n_internal']), '%d' % r['tree_height'],
                   ints(r['shadow_bytes']), sd_sci(r['sdc'], r['sdc_sd']), '%s + %s' % (f(r['n_sdc_missing'], 1), f(r['n_sdc_value'], 1)), ratio or '—',
                   '%s<br><span class="mu">%.2f×</span>' % (f(r['lat_us'], 2), r['lat_multiplier_vs_sanity_1x'])])

# ================================================================ Figure 1
src = open(ROOT + '/figures/btree_bitflip_overview.html', encoding='utf8').read()
def rep(m):
    tag, attrs, inner, close = m.group(1), m.group(2), m.group(3), m.group(4)
    en = re.search(r'data-en="([^"]*)"', attrs)
    attrs2 = re.sub(r'\s*data-(zh|en)="[^"]*"', '', attrs)
    attrs2 = attrs2.replace(' class=""', '')
    return '<%s%s>%s</%s>' % (tag, attrs2, en.group(1), close)
s1 = re.sub(r'<(\w+)((?:\s[^>]*?)?data-zh="[^"]*"[^>]*)>([^<]*)</(\w+)>', rep, src)
s1 = re.sub(r'aria-label="[^"]*"(\s*)data-label-zh="[^"]*"\s*data-label-en="([^"]*)"', lambda m: 'aria-label="%s"' % m.group(2), s1)
svgs = re.findall(r'<div class="diagram">(<svg.*?</svg>)</div>', s1, re.S)
legend = re.search(r'<ul class="legend">.*?</ul>', s1, re.S).group(0)
outs = re.findall(r'<p class="outcome">.*?</p>', s1, re.S)
heads = re.findall(r'<div class="p-head">.*?</div>', s1, re.S)
fig1_inner = '<div class="f1">' + legend + ''.join(
    '<section class="f1p%s">%s<div class="diagram">%s</div>%s</section>' % (' is-bad' if i else '', heads[i], svgs[i], outs[i]) for i in range(2)) + '</div>'
assert not re.search(r'[　-鿿]', fig1_inner)
FNUM[0] += 1
fig1 = ('<figure class="fig" id="f1">%s<figcaption><span class="lbl">Figure 1.</span> The damage one DRAM bit flip does depends on the level it hits. '
        'Schematic of a three-level B+-tree (two keys per node); both panels show the same lookup, search(16). A flip in a leaf loses one key; '
        'a flip in a root separator misroutes the lookup and makes a whole subtree unreachable, and later inserts land in the wrong node.</figcaption></figure>') % fig1_inner

# ================================================================ derived numbers for prose
none_final_err = 113585; ctrl_final_err = 1438; flips_3e3 = n3['n_flip_events'] if 'n_flip_events' in n3 else 5194.8
fe_per_flip = none_final_err / 5194.8
dmg_none = n3['n_wrong_undetected'] / 5194.8; dmg_ctrl = c3['n_wrong_undetected'] / 5194.8
runs = D['common']['run_counts']
ext_extra = 40 + 35   # E13 arms (none, adjacent right/both, random64 x SANITY+CTRL_CRC = 8 arms x 5) + E21 (shift 5 + hash 6x5)
primary_runs = sum(runs.values()) + ext_extra
r2_runs = 84

PAGE_SIZE = 4096

# ================================================================ HTML
P = []
A = P.append

A('<header class="ph"><p class="venue">Workshop paper draft</p>'
  '<h1>Where Bit Flips Hurt: Per-Level Differential Protection for In-Memory B+-Trees</h1>'
  '<p class="author">Author — Institution</p></header>')

A('<section class="abstract" aria-label="Abstract"><h2 class="abs">Abstract</h2>'
  '<p>Bit flips in DRAM silently corrupt in-memory B+-tree indexes, and a corrupted routing node can misdirect or contaminate the entire subtree beneath it. '
  'Current practice protects every page uniformly, overpaying where it matters least and leaving gaps where it matters most. '
  'Using a fault-injection simulator over a B+-tree, DRAM cache and SSD stack, we quantify the case for differential protection across %s seed-matched runs.%s '
  'Without protection, each bit flip leaves %.1f keys wrong (against a ceiling of 1 if damage stayed local), and a checksum over the control plane alone '
  '(node header, keys, child pointers) removes 98.7 %% of that damage and %.1f %% of silent wrong answers at %.0f %% of the latency cost of a full-page checksum. '
  'The amplification is therefore a routing effect, not payload corruption. '
  'The reliable-memory budget has a closed-form optimum equal to the storage of the internal nodes, invariant across a %.0f× range of internal-node counts. '
  'Finally, the tree\'s key-ordering invariant is a free detector whose strength is a closed form in key sparsity, (64−k)/64, but internal separators are sparse by construction '
  'and so carry a structural blind spot on exactly the pages every traversal reads. Padding the key space with dummy keys buys about one bit of coverage per doubling of the tree; '
  'changing the key representation is far cheaper. '
  'Protection should therefore be allocated by level and field role, with parameters computable before deployment from fanout and key distribution.</p></section>'
  % ('{:,}'.format(primary_runs), fn('Run count = %s primary-backend runs after excluding header-only schemes (E1–E7 and the E22 grid arm: %s; plus %d runs of the E13/E21 arms reused in §4.8), not counting %d Ramulator2 replicates. '
                                    'An earlier abstract draft said “more than 1,500”, which included runs of the excluded header-only schemes.' % ('{:,}'.format(primary_runs), '{:,}'.format(sum(runs.values())), ext_extra, r2_runs)),
     fe_per_flip, red * 100, cost_ratio * 100, nint_range))

# ---------------------------------------------------------------- 1 Introduction
A('<section id="s1"><h2><span class="sn">1</span>Introduction</h2>'
  '<p>An in-memory B+-tree is a small routing structure on top of a large payload: the few internal nodes are read on every lookup, each leaf only when its keys are wanted. '
  'A DRAM bit flip in a leaf value damages one key; the same flip in an internal separator or child pointer misroutes every later lookup through it, and inserts that follow the wrong route land in the wrong subtree (Figure 1). '
  'Uniform page protection, such as a CRC over every page, pays the same verification cost for both.</p>'
  + fig1 +
  '<p>We ask how much protection each part of the tree deserves, and whether the answer can be computed in advance. Four schemes (none, a free structural check, a control-plane checksum, a full-page checksum) are compared across eight experiments. Contributions:</p>'
  '<ul class="contrib">'
  '<li><b>Attribution.</b> The control plane is about 35–38 %% of corruption events but carries almost all wrong answers. CTRL_CRC, a CRC over header, keys and child pointers, cuts the silent-corruption (SDC) rate by %.1f %% at %.0f %% of the latency overhead of FULL_CRC and the same reliable memory (§4.1).</li>'
  '<li><b>A closed-form budget.</b> With a level-aware eviction policy, SDC saturates at exactly the bytes needed to cover every internal node, B<sub>int</sub>, in all four tree shapes we test (131 to 16,076 internal nodes) (§4.2).</li>'
  '<li><b>Robustness.</b> Uniform faults are the worst case at scale (§4.3); periodic verification saves little once only the control plane is checked (§4.4); shrinking DRAM concentrates the resident set on internal nodes, so eviction is not free scrubbing (§4.5); the CTRL_CRC/FULL_CRC cost ratio follows the read-weighted control-plane length (§4.6).</li>'
  '<li><b>Key sparsity.</b> The ordering check detects a fraction (64−k)/64 of what a checksum detects when keys are 2<sup>k</sup> apart, and its blind zone follows the internal separator gap, so it is blind on the routing pages even for dense keys (§4.7). Grid dummy keys raise the ratio by about one bit per doubling of pages while end-to-end SDC worsens; adjacency, shifting and hashing are the useful alternatives (§4.8).</li>'
  '</ul></section>' % (red * 100, cost_ratio * 100))

# ---------------------------------------------------------------- 2 Schemes
t1 = tblock('Protection schemes. All checks run on every guarded DRAM read (EVERY_READ) unless §4.4 says otherwise; a failed check reloads a clean copy from SSD (100 µs + 100 ns). Reliable memory is per protected page.',
            ['scheme', 'what is verified', 'reliable memory / page', 'verification cost per read'],
            [['NONE', 'nothing', '0 B', '0'],
             ['SANITY', 'structural invariants of the parsed node: node type valid, n_keys ≤ order and arrays in bounds, header padding zero, keys strictly increasing, child pointers in range and not self, leaf link in range', '0 B', 't<sub>sanity</sub> = 50 ns'],
             ['CTRL_CRC', 'CRC32 over bytes [16, 16 + ctrl_len): node header, keys[], and children[] for internal nodes; leaf values[] and unused slack are excluded', '12 B' + fn('Accounted as 12 B per page so that budgets are comparable with FULL_CRC; an implementation also stores the 2-byte ctrl_len, i.e. 14 B per page (+17 %). This does not change any qualitative result.'), '20 ns + 0.5 ns × ctrl_len'],
             ['FULL_CRC', 'CRC32 over the whole 4,096-byte page', '12 B', '20 ns + 0.5 ns × 4,096 ≈ 2.07 µs']], 99)
A('<section id="s2"><h2><span class="sn">2</span>Protection schemes and the reliable-memory model</h2>'
  '<p><b>Page layout.</b> A node occupies one 4,096-byte page: bytes [0, 16) hold an SSD header, [16, 32) the node header (type, n_keys, leaf link), then keys[] (8 B each), then either children[] (internal nodes) or values[] (leaves); the rest is zero padding. '
  'The control plane is ctrl_len = 16 + 8n bytes for a leaf with n keys and 24 + 16n bytes for an internal node, which is the whole live content of an internal node. At order 253 a typical leaf holds about 174 keys, so its control plane is about 1,408 B, its values 1,392 B and its unused slack about 1,280 B.</p>'
  '<p><b>Schemes.</b> Table 1 lists the four schemes. A header-only CRC covers 16 of the 4,080 mutable bytes (under 1 % of a dense page); in our runs it left the SDC rate unchanged from no protection, which motivates extending the checksum to the full control plane (CTRL_CRC). '
  'SANITY needs no stored state: it is the set of invariants a B+-tree node must satisfy anyway.</p>'
  + t1 +
  '<p><b>Reliable memory and the shadow store.</b> Checksums live in a small reliable memory (e.g. ECC-protected or on-chip SRAM, 20 ns per access) organised as a shadow store of 12-byte entries keyed by page. Its capacity is a budget B in bytes. '
  'A page without an entry is read unverified. When the store is full, an eviction policy decides which pages keep entries: '
  '<span class="k">BY_LEVEL</span> admits a page only if its level is above the lowest level present and then evicts the oldest entry of the lowest level; '
  '<span class="k">LRU</span> evicts the least recently used entry; <span class="k">BY_HOTNESS</span> evicts the least frequently accessed (count without ageing); <span class="k">RANDOM</span> evicts uniformly at random. '
  'We write B<sub>int</sub> = n<sub>internal</sub> × 12 B for the bytes needed to cover every internal node and B<sub>full</sub> = pages × 12 B for full coverage.</p></section>')

# ---------------------------------------------------------------- 3 Method
A('<section id="s3"><h2><span class="sn">3</span>Experimental method</h2>'
  '<p><b>Simulator stack.</b> A B+-tree of order 253 (the largest that fits a 4,096-byte internal node: 32 + 253 × 8 + 254 × 8 = 4,088 B) stores 8-byte keys and values in pages cached in a simulated DRAM (fixed 100 ns access, capacity 8 × rows-per-bank pages) in front of an SSD (100 µs, write-through). '
  'Each node read passes a guarded-read layer that applies the scheme and, for scoring only, compares the page with an oracle image at zero cost.</p>'
  '<p><b>Fault injection.</b> The default model flips uniformly random bits in resident DRAM pages as a Poisson process of rate λ flips per page per second (default λ = 3×10<sup>−3</sup>, deliberately accelerated). '
  '§4.3 adds row hammer (0.7 events/s, each flipping bits with probability 10<sup>−4</sup> on two adjacent rows) and one-shot column faults at t = 150 s that flip the same (byte, bit) on 512 rows. The fault stream depends only on the seed, not on the scheme.</p>'
  '<p><b>Workload.</b> 1,000,000 dense integer keys, inserted in shuffled order, build a tree of about 5,763 pages (h = 3, 33 internal nodes). Then 30,000 operations (10 ms simulated each) run: 90 % searches, 5 % of them for absent keys, and 10 % ascending inserts, i.e. about 27,000 searches per run. The 16,384-page DRAM keeps the tree resident except in §4.5.</p>'
  '<p><b>Metrics.</b> SDC rate = undetected wrong answers per search, scored against a reference map. <i>Cost</i> = reliable memory (peak shadow-store bytes) and pages allocated; <i>time</i> = mean operation latency, with overhead relative to NONE at the same setting. '
  'We do not use recall: for SANITY and CTRL_CRC it is dominated by harmless misses on payload and slack bytes.</p>'
  '<p><b>Scale, seeds and pairing.</b> The 1 M-key, order-253 scale was chosen after smoke tests (worst run about 50 s). E1 and E5–E7 use 5 seeds, E2–E4 use 3 (Appendix A). The fault schedule depends only on the seed, so schemes are compared paired by seed; '
  'flip counts match exactly in 33 of 35 E1 cells (the other two differ by ≤ 0.04 %). Tables give mean ± sample SD over seeds; we report no bootstrap intervals in this draft and flag overlapping SDs in the text.</p>'
  '<p><b>Ramulator2 replication.</b> We re-ran E1 with a cycle-accurate DDR4-2400 backend (Ramulator2, ECC off; 4 schemes × 7 λ × 3 seeds = 84 runs). It picks flipped bits with its own generator, so it is an independent replicate. '
  'Every qualitative result holds: FULL_CRC has SDC = 0 in all runs and CTRL_CRC\'s SDC is within −17 % to +12 % of the main backend. Latency differs by only 0.2–0.4 % because SSD write-through dominates it (10 % inserts × 100 µs ≈ 10 µs per op). '
  'NONE differs by up to 440× at λ = 10<sup>−4</sup>, which is the heavy tail of §5, not a backend effect.</p></section>')

# ---------------------------------------------------------------- 4.1
fig2, F2 = figure([c_e1_sdc, c_e1_lat],
    'CTRL_CRC removes about 99 %% of silent corruption at every error rate and costs %.0f %% of FULL_CRC\'s latency overhead at λ = 3×10<sup>−3</sup>. '
    '(a) Log–log SDC rate; FULL_CRC is 0 in every run (not drawn), and SANITY and CTRL_CRC are 0 at λ = 10<sup>−5</sup> (not drawn). (b) Mean operation latency. 5 seeds.' % (cost_ratio * 100))
t_e1 = tblock('E1 cost and time at the verification floor (λ = 10<sup>−5</sup>), the working point (3×10<sup>−3</sup>) and the highest rate (3×10<sup>−2</sup>). All λ values are in the Figure %d data tables.' % F2,
              ['λ', 'scheme', 'SDC ± sd', 'rel. mem (B)', 'pages', 'latency µs ± sd', 'vs NONE'], e1_rows, 2)
t_attr = tblock('Where corruption events land (each event counted once, via FULL_CRC, which repairs on first read; 5 seeds). Data from the SUMMARY attribution analysis.' ,
                ['λ', 'events / run', 'control plane (CTRL_CRC-visible)', 'live values[]', 'unused slack', 'SSD header'],
                [['10<sup>−3</sup>', '1,609.6', '35.4 %', '34.6 %', '29.6 %', '0.40 %'],
                 ['3×10<sup>−3</sup>', '4,489.8', '38.5 %', '33.8 %', '27.3 %', '0.42 %'],
                 ['3×10<sup>−2</sup>', '19,826.8', '58.2 %', '26.7 %', '14.0 %', '1.00 %']], 1)
A('<section id="s4"><h2><span class="sn">4</span>Results</h2>'
  '<section id="s41"><h3><span class="sn">4.1</span>E1: error rate × scheme</h3>'
  '<p class="setup"><b>Setup.</b> λ ∈ {10<sup>−5</sup>, …, 3×10<sup>−2</sup>} (7 values) × 4 schemes × 5 seeds; budget ∞, EVERY_READ, 1 M keys.</p>'
  + fig2 + t_e1 +
  ('<p><b>Findings.</b> At λ = 3×10<sup>−3</sup>, NONE returns a silently wrong answer for %.1f %% of searches (SDC %s). CTRL_CRC lowers this to %s (−%.1f %%), SANITY to %s, and FULL_CRC to 0. '
  'Each flip costs NONE %.3f wrong answers and CTRL_CRC %.4f, a factor of %.0f; counted as keys wrong at the end of the run, NONE loses %.1f keys per flip and CTRL_CRC removes 98.7 %% of that.%s</p>'
  '@@ATTR@@<p>Table %d explains the leverage. Only 35–38 %% of corruption events at λ ≤ 3×10<sup>−3</sup> touch the control plane, about a third hit live values that CTRL_CRC by design cannot see, and about 27 %% hit padding that is never read. '
  'Yet the control-plane events produce nearly all wrong answers, because a damaged separator or child pointer is re-read and misroutes on every traversal, while a damaged value affects one key.</p>'
  '<p><b>Cost.</b> CTRL_CRC and FULL_CRC hold the same reliable memory (%s B, 12 B × pages), so the difference is all in time. At the verification floor (λ = 10<sup>−5</sup>, almost no recoveries) CTRL_CRC adds %s and FULL_CRC %s, a ratio of %.0f %%; at the working point the ratio is %.0f %% (%.2f vs %.2f µs).%s '
  'Latency grows with λ for every detecting scheme because each detection triggers a 100 µs SSD reload.</p>'
  '<p><b>SANITY.</b> With dense keys, SANITY\'s SDC is at most 26 %% above CTRL_CRC\'s up to λ = 10<sup>−2</sup>, at lower latency (+44 %% vs +69 %%). At λ = 3×10<sup>−2</sup> it degrades to %s ± %s, against CTRL_CRC\'s %s ± %s. §4.7 shows that the near-tie is a property of dense keys.</p></section>'
  % (n3['sdc'] * 100, sci(n3['sdc']), sci(c3['sdc']), red * 100, sci(s3['sdc']),
     dmg_none, dmg_ctrl, dmg_none / dmg_ctrl, fe_per_flip,
     fn('Keys wrong at end of run (final integrity scan): NONE 113,585 and CTRL_CRC 1,438 per run at λ = 3×10<sup>−3</sup> (SUMMARY §2). These come from the original CTRL_CRC rows; paper_data.json does not export this column.'),
     TNUM[0], ints(c3['shadow_bytes']), pct(c0['overhead_pct']), pct(f0['overhead_pct']), floor_ratio * 100, cost_ratio * 100,
     c3['lat_us'] - n3['lat_us'], f3['lat_us'] - n3['lat_us'],
     fn('E1 and E5–E7 use the later header-covering CTRL_CRC rerun packaged in paper_data.json (e.g. 17.698 µs, +68.5 %, at λ = 3×10<sup>−3</sup>). SUMMARY §2 and §9 quote the original rows (17.626 µs, +67.9 %, ratio 39 %). SDC is identical to three digits. We use paper_data throughout.'),
     sci(e1('SANITY', 3e-2)['sdc']), sci(e1('SANITY', 3e-2)['sdc_sd'], 2), sci(e1('CTRL_CRC', 3e-2)['sdc']), sci(e1('CTRL_CRC', 3e-2)['sdc_sd'], 2))).replace('@@ATTR@@', t_attr))

# ---------------------------------------------------------------- 4.2
fig3, F3 = figure([c_e2], 'BY_LEVEL reaches its floor at 512 B (0.7 %% of full coverage): once every internal node has an entry, more budget buys little. '
                  'CTRL_CRC, 1 M keys, 3 seeds, λ = 3×10<sup>−3</sup>. The ∞ budget equals the 69 K point (%s for all policies). FULL_CRC is within 3 %% of these curves below full coverage and 0 at full coverage (not drawn).' % sci(e2('CTRL_CRC', 'BY_LEVEL', 'inf')['sdc']))
fig4, F4 = figure(e2r_panels, 'In all four tree shapes the BY_LEVEL curve has its knee at exactly 1.00 × B<sub>int</sub>, the bytes needed to cover every internal node, although the number of internal nodes varies %.0f×. '
                  'FULL_CRC, 3 seeds. At B<sub>full</sub> and ∞ every policy has SDC = 0 (not drawn). Grid points are nominal multiples of the planned B<sub>int</sub>; the measured B<sub>int</sub> differs by ≤ 1 %%.' % nint_range)
t_e2 = tblock('E2 cost and time (CTRL_CRC, 1 M keys). Each policy cell gives SDC and, below it, mean latency (overhead vs NONE). Reliable memory used equals the budget (entries × 12 B).',
              ['budget', 'rel. mem (B)', 'pages', 'BY_LEVEL', 'LRU', 'BY_HOTNESS', 'RANDOM'], e2_rows, 1)
t_knee = tblock('Knee at 1.00 × B<sub>int</sub> for the four rescaled configurations (FULL_CRC). SDC per policy at the knee; latency (overhead vs budget 0, i.e. unprotected) for BY_LEVEL and LRU at the knee and for full coverage.',
                ['config', 'pages', 'n<sub>int</sub>', 'knee (B)', '% B<sub>full</sub>', 'BY_LEVEL', 'LRU', 'BY_HOT.', 'RANDOM', 'LRU / BY_LEVEL', 'BY_LEVEL µs', 'LRU µs', 'B<sub>full</sub> µs'], knee_rows, 1)
kr = D['E2']['knee']
A('<section id="s42"><h3><span class="sn">4.2</span>E2: budget × policy</h3>'
  '<p class="setup"><b>Setup.</b> (i) 1 M keys: CTRL_CRC and FULL_CRC × 4 policies × 9 budgets (0 B to ∞) × 3 seeds. (ii) Rescaled: four trees with 131 to 16,076 internal nodes (orders 253, 64, 32, 16), budgets in multiples of B<sub>int</sub>, FULL_CRC, 3 seeds.</p>'
  + fig3 + t_e2 +
  ('<p><b>Findings at 1 M keys.</b> BY_LEVEL with 512 B (42 entries, 0.7 %% of the 69 K needed for full coverage) lowers SDC from %s to %s (−%.1f %%), within 2.7× of full coverage. Its latency overhead is %s, against %s for full coverage. '
  'The knee is where the store first holds all %d internal nodes.%s LRU needs 4 KB to match (internal nodes stay recent because every search reads them). BY_HOTNESS and RANDOM barely help below 4 KB; BY_HOTNESS\'s counts never age, so early-hot leaves keep their entries over internal nodes created by later splits. '
  'Below full coverage CTRL_CRC and FULL_CRC agree within 3 %%: under a tight budget, <i>which</i> pages are protected matters more than how much of each.</p>'
  '@@F4@@'
  '<p><b>Findings, rescaled.</b> The knee sits at 1.00 × B<sub>int</sub> in every configuration, and extra budget does little (E2d: %s at 1×, %s at 4×). As a share of B<sub>full</sub> the knee grows from %.2f %% to %.2f %%, exactly the internal-node share of the tree: the rule is “budget = storage of the internal nodes”, not “about 1 %% of full”. '
  'BY_LEVEL leads LRU at every budget, but its lead at the knee shrinks from %.1f× to %.1f× as LRU retains more internal nodes on its own. '
  'The time cost grows with height, since each traversal verifies h − 1 internal nodes: %s (E2b, h = 3) to %s (E2e, h = 6) at the knee, against %s and %s for full coverage.</p></section>'
  % (sci(b0['sdc']), sci(b512['sdc']), (1 - b512['sdc'] / b0['sdc']) * 100, pct(b512['overhead_pct']), pct(e2('CTRL_CRC', 'BY_LEVEL', 'inf')['overhead_pct']), 33,
     fn('paper_data reports 33 internal nodes for the 1 M-key tree (CTRL_CRC rows). SUMMARY §6 estimates “about 24” and §15 says 35; any of these fits within 42 entries, so the explanation of the knee is unchanged. Similarly, the rescaled n<sub>int</sub> and B<sub>int</sub> in paper_data are seed means (e.g. 131.3 nodes, 1,576 B for E2b), while SUMMARY §15 lists 130 nodes and 1,560 B (and 16,044 nodes for E2e, hence its “123×” range; paper_data gives 122×).'),
     sci(next(r for r in RS['E2D']['rows'] if r['policy'] == 'BY_LEVEL' and r['budget_bytes'] == '49908')['sdc']),
     sci(next(r for r in RS['E2D']['rows'] if r['policy'] == 'BY_LEVEL' and r['budget_bytes'] == '199632')['sdc']),
     kr[0]['knee_pct_B_full'], kr[3]['knee_pct_B_full'], kr[0]['lru_over_by_level'], kr[3]['lru_over_by_level'],
     pct(next(r for r in RS['E2B']['rows'] if r['policy'] == 'BY_LEVEL' and r['budget_bytes'] == '1560')['overhead_pct']),
     pct(next(r for r in RS['E2E']['rows'] if r['policy'] == 'BY_LEVEL' and r['budget_bytes'] == '192528')['overhead_pct']),
     pct(next(r for r in RS['E2B']['rows'] if r['policy'] == 'BY_LEVEL' and r['budget_bytes'] == '352128')['overhead_pct']),
     pct(next(r for r in RS['E2E']['rows'] if r['policy'] == 'BY_LEVEL' and r['budget_bytes'] == '2326068')['overhead_pct']))).replace('@@F4@@', fig4 + t_knee))

# ---------------------------------------------------------------- 4.3
fig5, F5 = figure([c_e3], 'Uniform faults do the most damage per flip; clustered faults are diluted across a large tree. A column fault in keys[] is fully caught by CTRL_CRC; one in values[] is not. '
                  'Log scale, 3 seeds. Effective flips = FULL_CRC recoveries. FULL_CRC is 0 in every mode, and CTRL_CRC is 0 for the byte-128 column fault (neither drawn).')
t_e3 = tblock('E3 cost and time by fault mode. CTRL_CRC here is the original variant (no rerun exists for E3).',
              ['mode', 'scheme', 'eff. flips', 'SDC ± sd', 'undet. / eff. flip', 'rel. mem (B)', 'pages', 'latency µs ± sd', 'vs NONE'], e3_rows, 2)
A('<section id="s43"><h3><span class="sn">4.3</span>E3: fault spatial structure</h3>'
  '<p class="setup"><b>Setup.</b> Four fault modes (uniform λ = 3×10<sup>−3</sup>; row hammer; column fault at byte 128; column fault at byte 3000, all bit 3) × 4 schemes × 3 seeds, 1 M keys.</p>'
  + fig5 + t_e3 +
  '<p><b>Findings.</b> Per effective flip, uniform faults cause %.3f undetected wrong answers under NONE, hammer %.3f and column faults %.3f–%.3f, so uniform is about 43× worse than a column fault. '
  'A column fault hits 512 rows, which is 8.9 %% of a 5,767-page tree, and each damaged key byte affects one of about 174 keys in its leaf; uniform flips spread over every page and so meet far more lookups. '
  'This reverses the result at toy scale (order 8, 1,339 pages), where the same column fault reached 38 %% of the tree.</p>'
  '<p>The two column faults isolate CTRL_CRC\'s boundary. At order 253, byte 128 lies in a leaf\'s keys[]: CTRL_CRC detects all 512 flips and has SDC = 0, matching FULL_CRC at %s latency instead of %s. Byte 3000 lies in values[]: CTRL_CRC sees almost nothing and lowers SDC only %.0f %%, and SANITY is identical to NONE because values carry no invariant. '
  'This is the intended trade-off, not a defect; §5 discusses protecting values where they matter.</p></section>'
  % (e3('uniform', 'NONE')['wrong_per_eff_flip'], e3('hammer', 'NONE')['wrong_per_eff_flip'], e3('col_b3000', 'NONE')['wrong_per_eff_flip'], e3('col_b128', 'NONE')['wrong_per_eff_flip'],
     pct(e3('col_b128', 'CTRL_CRC')['overhead_pct']), pct(e3('col_b128', 'FULL_CRC')['overhead_pct']),
     (1 - e3('col_b3000', 'CTRL_CRC')['sdc'] / e3('col_b3000', 'NONE')['sdc']) * 100))

# ---------------------------------------------------------------- 4.4
fig6, F6 = figure([c_e4_sdc, c_e4_lat], 'Relaxing the verification period saves FULL_CRC up to 28 % of its latency but saves CTRL_CRC only 18 %, at the same loss of protection, so with CTRL_CRC the knee is at every read. '
                  '(a) Log scale; FULL_CRC is 0 at every read (not drawn). (b) The dashed line is NONE. 3 seeds, λ = 3×10<sup>−3</sup>.')
t_e4 = tblock('E4 cost and time by verification period θ. Overhead is relative to E1 NONE at λ = 3×10<sup>−3</sup>, seeds 1–3 (E4 has no NONE rows). Original CTRL_CRC variant.',
              ['θ (s)', 'scheme', 'SDC ± sd', 'recall', 'rel. mem (B)', 'pages', 'latency µs ± sd', 'Δ vs every read', 'vs NONE'], e4_rows, 2)
A('<section id="s44"><h3><span class="sn">4.4</span>E4: verification frequency</h3>'
  '<p class="setup"><b>Setup.</b> CTRL_CRC and FULL_CRC × verification period θ ∈ {every read, 0.1, 0.3, 1, 3, 10, 30, 100 s} × 3 seeds; a page is re-verified only if θ has passed since its last check.</p>'
  + fig6 + t_e4 +
  '<p><b>Findings.</b> FULL_CRC\'s knee is at θ ≈ 1–3 s (recall 0.936 → 0.833): with 5,763 pages and about 3.1 M guarded reads per run, each page is read about 1.8 times per second, so short periods still verify most reads. '
  'At θ = 100 s, FULL_CRC saves %.1f %% of latency (%.2f µs) and CTRL_CRC %.1f %% (%.2f µs), while their SDC rates are almost equal (%s vs %s). CTRL_CRC has less to save because each check already costs about half a page. '
  'Its recall barely moves (0.0019 → 0.0014) while SDC grows 57×: recall is dominated by harmless payload misses and is the wrong metric for this scheme.</p></section>'
  % (-e4k('FULL_CRC', '100')['dlat_vs_every_read_pct'], e4k('FULL_CRC', 'EVERY_READ')['lat_us'] - e4k('FULL_CRC', '100')['lat_us'],
     -e4k('CTRL_CRC', '100')['dlat_vs_every_read_pct'], e4k('CTRL_CRC', 'EVERY_READ')['lat_us'] - e4k('CTRL_CRC', '100')['lat_us'],
     sci(e4k('FULL_CRC', '100')['sdc']), sci(e4k('CTRL_CRC', '100')['sdc'])))

# ---------------------------------------------------------------- 4.5
fig7, F7 = figure([c_e5_sdc, c_e5_lat], 'Shrinking DRAM makes each flip more harmful for NONE, not less, while CTRL_CRC reaches zero SDC; the FULL_CRC latency premium over CTRL_CRC shrinks from %.0f %% to %.0f %%. '
                  '(a) Undetected wrong answers per injected flip, log–log; CTRL_CRC is 0 at capacity ≤ 1,024 pages and FULL_CRC is 0 everywhere (not drawn). NONE at 1,024 pages includes one outlier seed. (b) Latency. 5 seeds.' % (gap_full * 100, gap_small * 100))
t_e5 = tblock('E5 cost and time by DRAM capacity (8 × rows-per-bank pages). Pages = tree pages. SDC/flip is computed per seed, then averaged.',
              ['capacity (pages)', 'scheme', 'flips', 'SDC ± sd', 'SDC / flip', 'rel. mem (B)', 'pages', 'latency µs ± sd', 'vs NONE'], e5_rows, 2)
A('<section id="s45"><h3><span class="sn">4.5</span>E5: DRAM capacity</h3>'
  '<p class="setup"><b>Setup.</b> DRAM capacity from 16,384 down to 256 pages (2.8× to 0.044× the tree) × 4 schemes × 5 seeds. Flips hit only resident pages, and evicted pages reload clean from SSD.</p>'
  + fig7 + t_e5 +
  '<p><b>Findings.</b> One might expect eviction to scrub corrupted pages for free. At this node density it does the opposite: NONE\'s damage per flip rises from %.2f at full residency to %.2f at 256 pages.%s Raw SDC still falls (%s → %s) only because 22× fewer flips land. '
  'The cause is targeting. Internal nodes are read on every search and so never leave the cache: the 33 internal nodes are 0.6 %% of the tree but 13 %% of a 256-page cache, so a larger share of flips lands on routing pages. '
  'Per-event attribution shows the same shift: the CTRL_CRC-visible share rises from 38.5 %% to 66.0 %% and the live-value share falls from 33.8 %% to 3.9 %%.%s</p>'
  '<p>The same shift helps CTRL_CRC. At capacity ≤ 1,024 pages it has SDC = 0 in all 15 runs, like FULL_CRC, and FULL_CRC\'s latency premium over it falls from %.1f %% to %.1f %%, since SSD misses dominate both (NONE itself goes from %.1f to %.1f µs). '
  'Trading DRAM for reliability is a bad deal at this scale: NONE pays 8.5× latency for a 58 %% SDC reduction, while CTRL_CRC removes 99.4 %% for +69 %%.%s</p></section>'
  % (e5('NONE', 2048)['sdc_per_flip'], e5('NONE', 32)['sdc_per_flip'],
     fn('paper_data computes SDC/flip per seed and then averages (0.524 → 4.906); SUMMARY §10 divides the means (0.527 → 4.99). At 1,024 pages one NONE seed has a damaged level-1 child pointer that routes nearly every query to a few pages (18,030 wrong answers); without it SDC/flip is 0.920 (SUMMARY §10.1).'),
     sci(e5('NONE', 2048)['sdc']), sci(e5('NONE', 32)['sdc']),
     fn('Attribution from SUMMARY §10.3 (FULL_CRC per-event view). We do not report ram_misses: the final integrity scan runs on a frozen clock, so 95–99 % of that counter comes from the scan. SDC, latency and flip counts are counted in the main loop only and are unaffected.'),
     gap_full * 100, gap_small * 100, e5('NONE', 2048)['lat_us'], e5('NONE', 32)['lat_us'],
     fn('SUMMARY §10.4 gives the full-residency premium as +62.0 % from the original CTRL_CRC rows; the header-covering rerun gives +61.4 %.')))

# ---------------------------------------------------------------- 4.6
fig8, F8 = figure([c_e6a_sdc, c_e6a_lat, c_e6b_sdc, c_e6b_lat],
                  'CTRL_CRC keeps SDC in a narrow band (6.1–8.3 × 10<sup>−4</sup>) across a 32× range of node order and a 25× range of tree size, while NONE varies by up to 19×. Its cost relative to FULL_CRC is smallest for sparse nodes. '
                  'FULL_CRC is 0 everywhere (not drawn). 5 seeds.')
t_e6 = tblock('E6 cost and time. CTRL/FULL = (lat<sub>CTRL</sub> − lat<sub>NONE</sub>) / (lat<sub>FULL</sub> − lat<sub>NONE</sub>); “model” = read-weighted ctrl_len / 4,096 from the measured per-level node counts. Reliable memory is the same for CTRL_CRC and FULL_CRC.',
              ['axis', 'setting', 'scheme', 'pages', 'h', 'n<sub>int</sub>', 'SDC ± sd', 'rel. mem (B)', 'latency µs', 'vs NONE', 'CTRL/FULL', 'model'], e6_rows, 3)
A('<section id="s46"><h3><span class="sn">4.6</span>E6: node density and scale</h3>'
  '<p class="setup"><b>Setup.</b> E6a: order ∈ {8, 32, 128, 253} with 200 K keys (h = 7, 4, 3, 3). E6b: order 253 with 200 K, 1 M, 3 M and 5 M keys (h = 3 throughout). NONE, CTRL_CRC and FULL_CRC × 5 seeds, fully resident.</p>'
  + fig8 + t_e6 +
  '<p><b>Findings.</b> The control plane\'s share of a page shrinks with order: at order 8, 96 %% of the bytes FULL_CRC hashes is padding that is never read, and with h = 7 it hashes seven full pages per lookup, so FULL_CRC costs %s against CTRL_CRC\'s %s. '
  'The CTRL/FULL cost ratio is %s for orders 8–253 and follows the byte model (read-weighted ctrl_len / 4,096: %s).%s '
  'Along the size axis the ratio rises from %.2f to %.2f because the root and level-1 nodes fill up as N grows while h stays 3; the byte model overestimates at 3–5 M keys (%.2f, %.2f) because the measured overheads also include recovery reloads. '
  'Across all eight trees CTRL_CRC holds SDC between %s and %s. NONE\'s run-to-run spread also narrows with size (SD/mean 0.73 at 1 M, 0.22 at 3–5 M), because a larger tree has more level-1 nodes and no single hit dominates.</p></section>'
  % (pct(e6a('FULL_CRC', 8)['overhead_pct']), pct(e6a('CTRL_CRC', 8)['overhead_pct']),
     ' / '.join('%.3f' % cra[o]['ctrl_over_full_cost_ratio'] for o in orders), ' / '.join('%.3f' % cra[o]['predicted_ratio_read_weighted_ctrl_len_over_4096'] for o in orders),
     fn('SUMMARY §11.3 reports 2.4 / 6.7 / 20.0 / 34.3 % (original CTRL_CRC rows) and a geometry-estimated model of 2.4 / 8.1 / 20.6 / 36.7 %. paper_data recomputes the model from measured per-level node counts (0.023 / 0.075 / 0.197 / 0.318) and the measured ratio from the rerun; the two sources differ by up to 5 pp at order 253. SUMMARY §12 gives 34.3 → 44.5 % for E6b; paper_data gives 0.347 → 0.449.'),
     crb[200000]['ctrl_over_full_cost_ratio'], crb[5000000]['ctrl_over_full_cost_ratio'],
     crb[3000000]['predicted_ratio_read_weighted_ctrl_len_over_4096'], crb[5000000]['predicted_ratio_read_weighted_ctrl_len_over_4096'],
     sci(min([e6a('CTRL_CRC', o)['sdc'] for o in orders] + [e6b('CTRL_CRC', k)['sdc'] for k in keysz])),
     sci(max([e6a('CTRL_CRC', o)['sdc'] for o in orders] + [e6b('CTRL_CRC', k)['sdc'] for k in keysz]))))

# ---------------------------------------------------------------- 4.7
fig9, F9 = figure([c_e7_ratio, c_e7_sdc], 'SANITY\'s detection relative to a checksum falls as (64−k)/64 when keys are 2<sup>k</sup> apart (all five points within %.1f pp), and its SDC grows 47 %% while CTRL_CRC\'s is unchanged. '
                  '(b) Log scale; FULL_CRC is 0 at every stride (not drawn). 5 seeds, λ = 3×10<sup>−3</sup>.' % (maxdev * 100))
t_e7 = tblock('E7 cost and time by key stride. tp = page-level detections per run; ratio = SANITY tp / CTRL_CRC tp at the same stride.',
              ['stride', 'scheme', 'SDC ± sd', 'tp', 'ratio', 'model', 'rel. mem (B)', 'pages', 'latency µs ± sd', 'vs NONE'], e7_rows, 2)
t_bz = tblock('SANITY\'s blind-zone edge (highest key bit with almost no detections, read-weighted) follows the internal separator gap, log<sub>2</sub>(leaf gap × fanout ≈ 174), not the leaf gap.',
              ['stride', 'measured edge bit', 'leaf gap (log<sub>2</sub>)', 'separator gap (log<sub>2</sub>)'], bz_rows, 1)
A('<section id="s47"><h3><span class="sn">4.7</span>E7: key sparsity</h3>'
  '<p class="setup"><b>Setup.</b> Keys = index × 2<sup>k</sup> for k ∈ {0, 8, 16, 24, 32} (k = 0 reproduces E1 exactly, 425 of 425 columns) × 4 schemes × 5 seeds.</p>'
  '<p><b>Model.</b> With adjacent keys 2<sup>k</sup> apart, flipping bit b &lt; k moves a key by 2<sup>b</sup> &lt; 2<sup>k</sup>, which cannot pass a neighbour, so the strict-order check stays satisfied. Only flips in the top 64 − k bits can break ordering, so SANITY should detect a fraction (64−k)/64 of what a checksum detects. A checksum ignores key semantics and should not change at all.</p>'
  + fig9 + t_e7 +
  ('<p><b>Findings.</b> The measured ratio is %s against the model\'s 1 / 0.875 / 0.750 / 0.625 / 0.500.%s CTRL_CRC and FULL_CRC are identical, bit for bit, at all five strides. This is the built-in control: the stride changes only key semantics, not injection or timing. '
  'SANITY\'s SDC grows from %s to %s; its latency falls (%.2f → %.2f µs) only because it detects, and therefore reloads, less. So E1\'s near-tie between SANITY and CTRL_CRC is a property of dense keys.</p>'
  '@@BZ@@'
  '<p>The bit-position histogram (Table %d) corrects the model in a way that matters more. The blind zone does not end at the leaf gap; it follows the gap between internal separators, which is the leaf gap times the fanout. '
  'Even with dense keys the low ~7 bits of every separator are invisible to SANITY, and separators sit on every search path: an undetected separator corruption is re-read 365–386× as often as a detected one. The free check is weakest exactly where damage is most expensive.</p></section>'
  % (' / '.join('%.3f' % e7('SANITY', k)['detection_ratio_vs_ctrl'] for k in ks),
     fn('SUMMARY §14.4 reports 0.990 / 0.867 / 0.754 / 0.633 / 0.515, computed against the original CTRL_CRC rows (tp 1,728.6 per run). paper_data uses the header-covering rerun (tp 1,745.6), which lowers each ratio by about 1 %; both lie within 2 pp of the model.'),
     sci(e7('SANITY', 0)['sdc']), sci(e7('SANITY', 32)['sdc']), e7('SANITY', 0)['lat_us'], e7('SANITY', 32)['lat_us'], TNUM[0])).replace('@@BZ@@', t_bz))

# ---------------------------------------------------------------- 4.8
fig10, F10 = figure([c_x_ratio, c_x_tp], 'Grid dummies raise SANITY\'s detection ratio by about one bit per doubling of pages, as the model predicts, but only because CTRL_CRC\'s count falls; SANITY detects no more real-key flips. Adjacent dummies reach 0.976 at 2× pages. '
                    'Stride-2<sup>32</sup> keys, 5 seeds. The shift point (hollow) is the E7 stride-0 page-level ratio, since the shift arm has no CTRL_CRC rows.')
fig11, F11 = figure([c_x_sdc, c_x_lat], 'End to end, grid dummies make SANITY worse, and they cost latency roughly in proportion to pages. Shift adds no pages and gives the lowest SDC; hash mapping is the option for irregular keys at about 2× pages and 2.3× latency. '
                    'Hash mapping is shown from its own unmapped random-key baseline (1×) to α = 0.5; α = 0.25 and 0.75 are in Table %d.' % (TNUM[0] + 1))
t_x = tblock('E7ext cost and time for every arm. Keys are stride 2<sup>32</sup> except the random64 and hash arms. Pages (× vs the unpadded tree of the same key set); rel. mem is 0 B for SANITY and NONE; missing + value = undetected wrong answers per run by kind; ratio = Σ SANITY / Σ CTRL_CRC real-key flip detections (model in parentheses); latency (× vs plain SANITY on the same key set).',
             ['arm', 'scheme', 'pages', 'n<sub>int</sub>', 'h', 'rel. mem (B)', 'SDC ± sd', 'missing + value', 'ratio (model)', 'latency µs'], x_rows, 2)
A('<section id="s48"><h3><span class="sn">4.8</span>Raising key density: grid dummies, shift and hash mapping</h3>'
  '<p class="setup"><b>Setup.</b> Stride-2<sup>32</sup> keys (1 M prefill plus about 2,977 appends), SANITY only, with CTRL_CRC run alongside as the reference for detection. '
  '<i>Grid dummies</i> insert sentinel keys K + j·2<sup>k</sup> (k = 31, 30, 29: 1, 3 or 7 per real key) through the normal insert path, so their cost is counted. <i>Adjacent dummies</i> insert K + 1 (and K − 1). '
  '<i>Shift</i> stores K ≫ 32, which removes the stride when it is known. <i>Hash mapping</i> maps random 64-bit keys into a dense range (load α; two tree entries per key). Geometry is scaled so every tree stays fully resident. 5 seeds per cell.</p>'
  + fig10 +
  ('<p><b>Grid dummies: the ratio rises, protection does not.</b> Each doubling of entries halves the gap, so the model predicts one more visible bit (+1.6 pp per doubling). '
  'The measured ratio rises %s → %s → %s → %s (+2.2, +1.5, +4.1 pp; model %s at 8×). But SANITY catches no more real-key flips: %s per run. '
  'The ratio rises because CTRL_CRC\'s count falls (%s) as real keys hold a shrinking share of each page. The gain is relative only.</p>'
  '@@F11@@'
  '<p><b>End to end it gets worse.</b> SANITY\'s SDC goes from %s with no dummies to %s, %s and %s (undetected answers per run 28.6 → %.1f, %.1f, %.1f; missing answers 10.2 → %.1f, %.1f, %.1f). '
  'More pages receive more flips (5,195 → 41,318 per run at 8×) and hold more internal nodes in the blind zone; the 8× tree is also taller (h = 4), a confound. With n = 5 the differences are within seed spread, but no grid arm beats the baseline. '
  'Cost scales with pages: %s pages give %s SANITY latency, and CTRL_CRC\'s reliable memory grows %s → %s B.</p>'
  '<p><b>Contrasts.</b> Adjacent dummies make every key\'s low bits matter to its neighbour: ratio %.3f at 2.00× pages and %.2f× latency, with SDC %s (about the baseline; missing answers fall to %.1f). '
  'Shift adds no pages or reliable memory and yields exactly the stride-0 tree, so SANITY behaves as at k = 0 (ratio %.3f, SDC %s, −%.0f %% vs the stride-2<sup>32</sup> baseline); its %.2f× latency is the cost of reloading the extra detected pages. It needs a known stride. '
  'For irregular keys, hash mapping lowers SANITY\'s SDC from %s (unmapped random keys, ratio %.3f) to %s–%s at about 2× pages and %.2f–%.2f× latency (%.2f–%.2f probes per hit), but gives up key order and hence range scans. E21 has no CTRL_CRC rows, so no ratio is reported.</p>'
  '<p><b>Verdict.</b> Grid dummies buy about one bit of SANITY coverage per doubling of the tree, which is the predicted rate and not worth paying. Where keys are sparse, change the representation (shift, or hash mapping when order is not needed) or use adjacency; otherwise checksum the control plane.</p></section></section>'
  % ('%.3f' % g[0]['detection_ratio'], '%.3f' % g[1]['detection_ratio'], '%.3f' % g[2]['detection_ratio'], '%.3f' % g[3]['detection_ratio'], '%.3f' % g[3]['predicted_ratio'],
     ' → '.join(f(r['n_keyflip_real_tp'], 0) for r in g), ' → '.join(f(r['n_keyflip_real_tp'], 0) for r in gc),
     sci(g[0]['sdc']), sci(g[1]['sdc']), sci(g[2]['sdc']), sci(g[3]['sdc']),
     g[1]['n_wrong_undetected'], g[2]['n_wrong_undetected'], g[3]['n_wrong_undetected'], g[1]['n_sdc_missing'], g[2]['n_sdc_missing'], g[3]['n_sdc_missing'],
     ' / '.join('%.0f×' % round(r['page_multiplier']) for r in g[1:]), ' / '.join('%.2f×' % r['lat_multiplier_vs_sanity_1x'] for r in g[1:]),
     ints(gc[0]['shadow_bytes']), ints(gc[3]['shadow_bytes']),
     adjR['detection_ratio'], adjR['lat_multiplier_vs_sanity_1x'], sci(adjR['sdc']), adjR['n_sdc_missing'],
     e7_shift_ratio, sci(shf['sdc']), (1 - shf['sdc'] / g[0]['sdc']) * 100, shf['lat_multiplier_vs_sanity_1x'],
     sci(r64['sdc']), r64['detection_ratio'], sci(min(h['sdc'] for h in hsh)), sci(max(h['sdc'] for h in hsh)),
     min(h['lat_multiplier_vs_sanity_1x'] for h in hsh), max(h['lat_multiplier_vs_sanity_1x'] for h in hsh),
     min(h['probes_per_hit'] for h in hsh), max(h['probes_per_hit'] for h in hsh))).replace('@@F11@@', fig11 + t_x))

# ---------------------------------------------------------------- 5, 6
A('<section id="s5"><h2><span class="sn">5</span>Discussion</h2>'
  '<p><b>What follows for differential protection.</b> The results reduce protection to quantities known before deployment. '
  '(1) <i>Where</i> to spend reliable memory: on internal nodes first, with a level-aware policy and a budget of B<sub>int</sub> = n<sub>internal</sub> × entry size, which follows from N and the fanout. '
  '(2) <i>What</i> to checksum: the control plane, whose cost relative to a full-page checksum is the read-weighted ctrl_len / 4,096, about 0.03 for sparse nodes and 0.35–0.45 at order 253. '
  '(3) <i>When</i> a free check suffices: the ordering invariant covers (64−k)/64 of key flips, nearly a checksum on dense leaves, but its separator blind zone leaves internal nodes needing a real checksum. '
  'Values stay unprotected under CTRL_CRC (about a third of events at order 253); a checksum on hot leaves is the natural next step, not evaluated here.</p>'
  '<p><b>Limitations.</b> '
  '<i>Accelerated λ.</i> λ = 3×10<sup>−3</sup> flips/page/s is far above field DRAM rates; the 3.5-decade sweep shows the ranking is stable, but absolute SDC rates are not field predictions. '
  '<i>DRAM-only flips.</i> We inject only into DRAM-resident pages: no SSD, controller, CPU-cache or reliable-memory faults, and ECC is off. '
  '<i>Single workload.</i> 90 % point searches and 10 % ascending inserts on integer keys, single-threaded, with no deletes and no range scans; latency comes from fixed constants and is dominated by SSD write-through. '
  '<i>Frozen-clock scan.</i> The end-of-run integrity scan does not advance the clock, degrading the LRU during the scan; we omit ram_misses in E5 (SDC, latency and flips are unaffected). '
  '<i>NONE heavy tail.</i> Unprotected SDC depends on whether a flip hits a busy level-1 node (SD ≈ 0.73 × mean at 1 M keys, 5 seeds); read NONE magnitudes as orders of magnitude. '
  '<i>E3 confounds.</i> Fault modes differ in flip count and timing as well as structure (column faults are one-shot at t = 150 s, 512 flips against about 4,470), so per-flip normalisation compares mechanisms only approximately. '
  'E2–E4 use 3 seeds and the original CTRL_CRC variant, and no bootstrap intervals are reported.</p></section>'
  '<section id="s6"><h2><span class="sn">6</span>Conclusion</h2>'
  '<p>In a dense in-memory B+-tree, silent corruption is a routing problem. A checksum over the control plane removes about 99 % of silent wrong answers at roughly 40 % of the time cost of checksumming whole pages, and a reliable-memory budget equal to the internal nodes\' storage captures nearly all of the benefit, in every tree shape we tried. '
  'The free ordering check is a useful complement whose strength is a closed form in key sparsity. Its blind spot on separators, and the poor return from padding keys with dummies, argue for checksumming internal nodes and fixing key representation instead. '
  'Each parameter (B<sub>int</sub>, the cost ratio, the ordering-check coverage) can be computed from fanout and key distribution before deployment.</p></section>')

# ---------------------------------------------------------------- Appendix
app_rows = [
    ['E1', 'λ (7) × scheme (4)', '5', '140', '1 M keys, order 253, budget ∞, EVERY_READ', 'header-covering rerun'],
    ['E2', 'policy (4) × budget (9) × {CTRL_CRC, FULL_CRC}', '3', '216', 'λ = 3×10<sup>−3</sup>', 'original'],
    ['E2b–E2e', 'policy (4) × budget (10) per config, FULL_CRC', '3', '480', 'orders 253/64/32/16; 5 M / 2 M / 2 M / 2 M keys', '—'],
    ['E3', 'fault mode (4) × scheme (4)', '3', '48', 'uniform, hammer, column at byte 128 / 3000', 'original'],
    ['E4', 'θ (8) × {CTRL_CRC, FULL_CRC}', '3', '48', 'PERIODIC verification', 'original'],
    ['E5', 'rows-per-bank (7) × scheme (4)', '5', '140', 'capacity 16,384 → 256 pages', 'header-covering rerun'],
    ['E6a', 'order (4) × {NONE, CTRL_CRC, FULL_CRC}', '5', '60', '200 K keys; SSD blocks per order; rows-per-bank 8,192', 'header-covering rerun'],
    ['E6b', 'keys (4) × {NONE, CTRL_CRC, FULL_CRC}', '5', '60', 'order 253; geometry scaled with N', 'header-covering rerun'],
    ['E7', 'stride (5) × scheme (4)', '5', '100', 'keys = index × 2<sup>k</sup>', 'header-covering rerun'],
    ['E7ext: grid (E22)', 'k (3) × {SANITY, CTRL_CRC} + NONE at k = 30, 29', '5', '40', 'stride 2<sup>32</sup>; geometry 2×/4×/8×', 'header-covering'],
    ['E7ext: adjacent, baselines (E13)', '4 arms × {SANITY, CTRL_CRC}', '5', '40', 'none, right, both (stride 2<sup>32</sup>); none (random64)', 'header-covering'],
    ['E7ext: shift, hash (E21)', 'shift (SANITY); hash α (3) × {SANITY, NONE}', '5', '35', 'K ≫ 32; random64 hash-mapped', '—'],
    ['Ramulator2', 'λ (7) × scheme (4)', '3', '84', 'DDR4-2400, ECC off; E1 replicate', 'original'],
]
t_app = tblock('Run counts and configurations. Common settings: order 253, 30,000 ops (90 % search, 5 % of searches miss, 10 % ascending insert), dt = 10 ms per op, λ = 3×10<sup>−3</sup>, EVERY_READ, budget ∞, SSD blocks 512 / rows-per-bank 2,048 (tree ≈ 35 % of SSD pages, fully resident), unless the row says otherwise. Header-only schemes are excluded from all counts.',
               ['experiment', 'sweep', 'seeds', 'runs', 'deviations', 'CTRL_CRC variant'],
               app_rows + [['<b>Total</b>', '', '', '<b>%s</b>' % '{:,}'.format(primary_runs + r2_runs), '%s primary + %d Ramulator2' % ('{:,}'.format(primary_runs), r2_runs), '']], 2, (4, 5))
A('<section id="sA"><h2><span class="sn">A</span>Appendix: run counts and configurations</h2>' + t_app + '</section>')

notes = '<section id="notes" class="notes"><h2>Notes</h2><ol>' + ''.join(
    '<li id="n%d">%s <a href="#r%d" class="back" aria-label="back to text">↩</a></li>' % (i + 1, t, i + 1) for i, t in enumerate(NOTES)) + '</ol>' \
    '<p class="src">Numbers are taken from <code>results/paper/paper_data.json</code> (cost and time tables as in <code>paper_tables.md</code>); prose observations from <code>SUMMARY_dbscale.md</code> §0–§15. Where the two disagree, paper_data is used and a note says so.</p></section>'

body = ''.join(P) + notes

# ================================================================ CSS & JS
CSS = open('/tmp/claude-1006/-home-u05/5fb1588a-3c19-4b30-8210-7e8862b03b08/scratchpad/pg/style.css').read()
JS = open('/tmp/claude-1006/-home-u05/5fb1588a-3c19-4b30-8210-7e8862b03b08/scratchpad/pg/charts.js').read()
data_js = 'const CHARTS=' + json.dumps(CHARTS, ensure_ascii=False, separators=(',', ':')) + ';\n'

doc = ('<title>Per-Level Differential Protection</title>\n'
       '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
       '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap">\n'
       '<style>\n' + CSS + '\n</style>\n'
       '<div class="page"><article class="paper">' + body + '</article></div>\n'
       '<script>\n' + data_js + JS + '\n</script>\n')
open(OUT, 'w', encoding='utf8').write(doc)
open('/tmp/claude-1006/-home-u05/5fb1588a-3c19-4b30-8210-7e8862b03b08/scratchpad/pg/script.js', 'w').write(data_js + JS)
print('wrote', OUT, len(doc.encode('utf8')), 'bytes;', FNUM[0], 'figures;', TNUM[0], 'tables;', len(NOTES), 'notes;', len(CHARTS), 'charts')
