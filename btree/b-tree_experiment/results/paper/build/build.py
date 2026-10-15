#!/usr/bin/env python3
"""Builds the paper page.

  BACKEND=r2 python3 build.py   -> results/paper/paper.html from results/paper_r2/paper_data.json (Ramulator2 backend)
                                   plus per-seed quantities (medians, final-integrity counts, attribution, blind-zone
                                   edges) read from the per-run CSVs in results/r2/.
  python3 build.py              -> the frozen C++-model page, results/paper/paper_cpp_model.html, from
                                   results/paper/paper_data.json (delegates to build_cpp.py; byte-identical).
OUT=<path> overrides the output file; SCRIPT_OUT=<path> also writes the inline script for `node --check`.
"""
import csv, json, os, re, sys, math, statistics as st, html as H

HERE = os.path.dirname(os.path.abspath(__file__))
if os.environ.get('BACKEND', 'ram') != 'r2':
    import runpy
    runpy.run_path(os.path.join(HERE, 'build_cpp.py'), run_name='__main__')
    sys.exit(0)

ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
D = json.load(open(ROOT + '/paper_r2/paper_data.json'))
DC = json.load(open(ROOT + '/paper/paper_data.json'))      # earlier C++-model pass, used only for the backend comparison in §3
OUT = os.environ.get('OUT', ROOT + '/paper/paper.html')

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

# ================================================================ per-run CSVs (results/r2) — per-seed quantities the JSON does not carry
# Every selection below is cross-checked against the JSON cell it belongs to (same n, same mean SDC and latency).
def _load(name):
    with open(ROOT + '/r2/' + name) as fh:
        return list(csv.DictReader(fh))
CSV = {k: _load(k + '_r2.csv') for k in ['e1', 'e3', 'e4', 'e5', 'e6a', 'e6b', 'e7', 'e13', 'e21', 'e22']}
def Fv(r, k): return float(r[k])
def rsdc(r): return Fv(r, 'n_wrong_undetected') / Fv(r, 'n_searches')
def rlat(r): return Fv(r, 'total_latency_s') / Fv(r, 'n_ops') * 1e6
def bseed(rows): return {r['seed']: r for r in rows}
def median(xs): return st.median(list(xs))
def where(rows, **kw): return [r for r in rows if all(r[k] == v for k, v in kw.items())]

def check(cell, rows):
    assert len(rows) == cell['n_seeds'], (cell, len(rows))
    for key, fn_ in (('sdc', rsdc), ('lat_us', rlat)):
        a, b = st.mean(map(fn_, rows)), cell[key]
        assert abs(a - b) <= 1e-5 * max(abs(b), 1e-9) + 1e-12, (key, a, b, {k: cell[k] for k in cell if k in ('scheme', 'lambda', 'arm')})
    cell['_rows'] = rows
    cell['sdc_med'] = median(map(rsdc, rows))
    cell['wrong_med'] = median(Fv(r, 'n_wrong_undetected') for r in rows)
    return cell

E3MODE = {'uniform': 'uniform', 'hammer': 'hammer', 'colctrl': 'col_b128', 'colpay': 'col_b3000'}
for c in D['E1']: check(c, [r for r in CSV['e1'] if r['scheme'] == c['scheme'] and float(r['lambda_page']) == c['lambda']])
for c in D['E3']: check(c, [r for r in CSV['e3'] if r['scheme'] == c['scheme'] and E3MODE[r['run_id'].split('_')[1]] == c['mode']])
for c in D['E5']: check(c, [r for r in CSV['e5'] if r['scheme'] == c['scheme'] and int(r['ram_rows_per_bank']) == c['ram_rows_per_bank']])
for c in D['E6a']['rows']: check(c, [r for r in CSV['e6a'] if r['scheme'] == c['scheme'] and int(r['order']) == c['order']])
for c in D['E6b']['rows']: check(c, [r for r in CSV['e6b'] if r['scheme'] == c['scheme'] and int(r['prefill_keys']) == c['keys']])
for c in D['E7']['rows']: check(c, [r for r in CSV['e7'] if r['scheme'] == c['scheme'] and int(r['key_stride_log2']) == c['stride_log2']])

def ext_csv_rows(c):
    a, s = c['arm'], c['scheme']
    e13, e21, e22 = CSV['e13'], CSV['e21'], CSV['e22']
    if a == 'none' and c['key_set'] == 'stride2^32': return where(e13, scheme=s, key_stride_log2='32', guard='none', ssd_blocks='512')
    if a.startswith('grid k=31'): return where(e13, scheme=s, key_stride_log2='32', guard='mid')
    if a.startswith('grid k='): return where(e22, scheme=s, guard='grid', guard_grid_log2=a.split('=')[1].split()[0])
    if a.startswith('adjacent right'): return where(e13, scheme=s, key_stride_log2='32', guard='right')
    if a.startswith('adjacent both'): return where(e13, scheme=s, key_stride_log2='32', guard='both')
    if a.startswith('shift'): return where(e21, scheme=s, key_map='shift')
    if a.startswith('none (plain random64'): return where(e13, scheme=s, key_dist='random64', guard='none', ssd_blocks='512')
    if a.startswith('hash'): return where(e21, scheme=s, key_map='hashdense', key_dist='random64', map_load=a.split('=')[1].split()[0])
    raise KeyError(a)
for c in D['E7ext']:
    rr = check(c, ext_csv_rows(c))['_rows']
    c['missing_med'] = median(Fv(r, 'n_sdc_missing') for r in rr)
    c['value_med'] = median(Fv(r, 'n_sdc_value') for r in rr)
    c['flips'] = st.mean(Fv(r, 'n_flip_events') for r in rr)

def paired_red(base, prot):
    """median over seeds of 1 - wrong(prot)/wrong(base), paired by seed (same fault schedule)."""
    b, p = bseed(base['_rows']), bseed(prot['_rows'])
    v = [1 - Fv(p[s], 'n_wrong_undetected') / Fv(b[s], 'n_wrong_undetected') for s in b if s in p and Fv(b[s], 'n_wrong_undetected') > 0]
    return median(v)

def attribution(rows):
    """per-event split from FULL_CRC rows (FULL_CRC repairs on first read, so each corruption event is counted once)."""
    ev = ctrl = live = slack = hdr = 0.0
    for r in rows:
        co, po, mx, sh, so = (Fv(r, 'n_corrupt_reads_' + k) for k in ('ctrl_only', 'payload_only', 'mixed', 'ssd_header', 'slack_only'))
        ev += co + po + mx + sh; ctrl += co + mx; live += po - so; slack += so; hdr += sh
    return {'events': ev / len(rows), 'ctrl': ctrl / ev * 100, 'live': live / ev * 100, 'slack': slack / ev * 100, 'hdr': hdr / ev * 100}

def p1(v): return '%.1f %%' % v
def p2(v): return ('%.2f %%' % v) if v < 1 else ('%.1f %%' % v)
def med_note(r):
    return '<br><span class="mu">median %s</span>' % sci(r['sdc_med'])
def sdc_cell(r):
    """data tables keep mean ± SD; NONE/SANITY also show the median (heavy tails, §3)."""
    return sd_sci(r['sdc'], r['sdc_sd']) + (med_note(r) if r['scheme'] in ('NONE', 'SANITY') else '')
def sdc_plot(r):
    """value plotted for an SDC-type metric: median for NONE/SANITY, mean otherwise."""
    return r['sdc_med'] if r['scheme'] in ('NONE', 'SANITY') else r['sdc']
def sname(s): return s + (' (median)' if s in ('NONE', 'SANITY') else '')

# ================================================================ E1
E1 = D['E1']
lams = sorted(set(r['lambda'] for r in E1))
def e1(s, l): return next(r for r in E1 if r['scheme'] == s and r['lambda'] == l)
def lamtxt(l):
    m, e = ('%.0e' % l).split('e'); e = int(e)
    return ('10<sup>−%d</sup>' % -e) if m == '1' else ('%s×10<sup>−%d</sup>' % (m, -e))

c_e1_sdc = chart('c-e1-sdc', {
    'title': '(a) Silent-corruption rate',
    'aria': 'Line chart, log-log: SDC rate versus flip rate lambda; median over seeds for NONE and SANITY, mean for CTRL_CRC.',
    'x': {'type': 'log', 'label': 'λ (flips / page / s)', 'min': 1e-5, 'max': 3e-2, 'fmt': 'sci'},
    'y': {'type': 'log', 'label': 'SDC rate (wrong answers / search)', 'fmt': 'sci'},
    'series': [{'name': sname(s), 'slot': SLOT[s], 'pts': [[l, sdc_plot(e1(s, l))] for l in lams]} for s in ['NONE', 'SANITY', 'CTRL_CRC']]
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
    return [lamtxt(l), s, sdc_cell(r), ints(r['shadow_bytes']), ints(r['pages']),
            f(r['lat_us'], 2) + ' ± ' + f(r['lat_sd'], 2), pct(r['overhead_pct'])]
e1_rows = [e1row(s, l) for l in [1e-5, 3e-3, 3e-2] for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']]

n3 = e1('NONE', 3e-3); c3 = e1('CTRL_CRC', 3e-3); s3 = e1('SANITY', 3e-3); f3 = e1('FULL_CRC', 3e-3)
red = paired_red(n3, c3)                                    # paired, median over seeds
red_hi = [paired_red(e1('NONE', l), e1('CTRL_CRC', l)) for l in lams if l >= 1e-3]
cost_ratio = (c3['lat_us'] - n3['lat_us']) / (f3['lat_us'] - n3['lat_us'])
n0 = e1('NONE', 1e-5); c0 = e1('CTRL_CRC', 1e-5); f0 = e1('FULL_CRC', 1e-5)
floor_ratio = (c0['lat_us'] - n0['lat_us']) / (f0['lat_us'] - n0['lat_us'])
# keys wrong at the end of the run (final integrity scan) per injected flip, means over seeds
def mcol(cell, col): return st.mean(Fv(r, col) for r in cell['_rows'])
flips3 = mcol(n3, 'n_flip_events')
fie_none, fie_ctrl = mcol(n3, 'n_final_integrity_errors'), mcol(c3, 'n_final_integrity_errors')
fe_per_flip = fie_none / flips3
fie_red = 1 - fie_ctrl / fie_none
dmg_none = median(Fv(r, 'n_wrong_undetected') / Fv(r, 'n_flip_events') for r in n3['_rows'])
dmg_ctrl = c3['n_wrong_undetected'] / flips3
# SANITY (median) vs CTRL_CRC (mean) for λ ≥ 1e-3
san_vs_ctrl = [e1('SANITY', l)['sdc_med'] / e1('CTRL_CRC', l)['sdc'] for l in lams if l >= 1e-3]
# heavy-tail illustration: SANITY at λ = 3e-3
s3w = sorted(((int(Fv(r, 'n_wrong_undetected')), r['seed']) for r in s3['_rows']), reverse=True)
hot_w, hot_seed = s3w[0]; rest_w = [w for w, _ in s3w[1:]]
# flip counts paired across schemes (same seed, same λ)
fm_cells = fm_match = 0; fm_maxdiff = 0.0
for l in lams:
    for sd_ in sorted({r['seed'] for r in CSV['e1']}):
        fl = [Fv(r, 'n_flip_events') for r in CSV['e1'] if float(r['lambda_page']) == l and r['seed'] == sd_]
        fm_cells += 1; fm_match += len(set(fl)) == 1
        fm_maxdiff = max(fm_maxdiff, (max(fl) - min(fl)) / max(fl) if max(fl) else 0)
ATTR = {l: attribution(e1('FULL_CRC', l)['_rows']) for l in [1e-3, 3e-3, 3e-2]}

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
nint = [RS[k]['n_internal'] for k in ['E2B', 'E2C', 'E2D', 'E2E']]
nint_range = round(nint[-1]) / round(nint[0])            # ratio of the counts as printed (131 → 16,076)
# CTRL_CRC vs FULL_CRC below full coverage (budgets 128 B … 16 KB), all policies
ctrl_full_dev = max(abs(e2('CTRL_CRC', p, b)['sdc'] / e2('FULL_CRC', p, b)['sdc'] - 1) for p in PSLOT for b in budgets[1:7])
# measured B_int vs the grid point used as "1.0 × B_int"
bint_dev = max(abs(kr_['knee_budget_bytes'] / kr_['B_int'] - 1) for kr_ in D['E2']['knee'])
full_bytes = int(budgets[7])
# ================================================================ E3
E3 = D['E3']
modes = ['uniform', 'hammer', 'col_b128', 'col_b3000']
mode_lbl = ['uniform', 'hammer', 'column, byte 128 (keys[])', 'column, byte 3000 (values[])']
mode_short = ['uniform', 'hammer', 'col. byte 128', 'col. byte 3000']
def e3(m, s): return next(r for r in E3 if r['mode'] == m and r['scheme'] == s)
for m in modes:      # per-seed damage per effective flip (effective flips = FULL_CRC recoveries of the same seed)
    eff = {r['seed']: Fv(r, 'n_recoveries') for r in e3(m, 'FULL_CRC')['_rows']}
    for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']:
        c = e3(m, s)
        c['wpef_med'] = median(Fv(r, 'n_wrong_undetected') / eff[r['seed']] for r in c['_rows'])
def e3plot(c): return c['wpef_med'] if c['scheme'] in ('NONE', 'SANITY') else c['wrong_per_eff_flip']
c_e3 = chart('c-e3', {
    'aria': 'Dot plot: undetected wrong answers per effective flip by fault mode; median over seeds for NONE and SANITY, mean for CTRL_CRC; log scale.',
    'x': {'type': 'cat', 'label': 'fault mode', 'cats': mode_short},
    'y': {'type': 'log', 'label': 'undetected wrong answers per effective flip', 'fmt': 'sci'},
    'series': [{'name': sname(s), 'slot': SLOT[s], 'line': False, 'pts': [[i, e3plot(e3(m, s))] for i, m in enumerate(modes)]} for s in ['NONE', 'SANITY', 'CTRL_CRC']],
    'endLabels': False
}, None, lambda v: sci(v))
e3_rows = []
for i, m in enumerate(modes):
    for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']:
        r = e3(m, s)
        e3_rows.append([mode_lbl[i] if s == 'NONE' else '', s, f(r['effective_flips'], 1), sdc_cell(r),
                        f(r['wrong_per_eff_flip'], 4), ints(r['shadow_bytes']), ints(r['pages']),
                        f(r['lat_us'], 2) + ' ± ' + f(r['lat_sd'], 2), pct(r['overhead_pct'])])
col_rows = int(Fv(e3('col_b128', 'NONE')['_rows'][0], 'colfault_rows'))
col_tp = [Fv(r, 'tp') for r in e3('col_b128', 'CTRL_CRC')['_rows']]
san_eq_none_b3000 = all(Fv(a, 'n_wrong_undetected') == Fv(bseed(e3('col_b3000', 'NONE')['_rows'])[a['seed']], 'n_wrong_undetected')
                        for a in e3('col_b3000', 'SANITY')['_rows'])
keys_per_leaf = D['common']['config']['prefill_keys'] / (e1('NONE', 3e-3)['pages'] - e1('NONE', 3e-3)['n_internal'])

# ================================================================ E4
E4 = D['E4']
thetas = ['EVERY_READ', '0.1', '0.3', '1', '3', '10', '30', '100']
th_lbl = ['every read', '0.1', '0.3', '1', '3', '10', '30', '100']
def e4k(s, t):
    for r in E4:
        if r['scheme'] != s: continue
        ts = str(r['theta_s'])
        if ts == t or (t != 'EVERY_READ' and ts != 'EVERY_READ' and abs(float(ts) - float(t)) < 1e-9): return r
    raise KeyError((s, t))
_er = e4k('CTRL_CRC', 'EVERY_READ')
none_ref = _er['lat_us'] / (1 + _er['overhead_pct'] / 100)       # E1 NONE λ=3e-3, seeds 1–3 (the E4 overhead base)
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
    'y': {'type': 'lin', 'label': 'mean op latency (µs)', 'min': 0, 'fmt': 'f2', 'refLine': {'v': round(none_ref, 3), 'label': 'NONE %.2f µs' % none_ref}},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[i, e4k(s, t)['lat_us']] for i, t in enumerate(thetas)]} for s in ['CTRL_CRC', 'FULL_CRC']]
}, None, lambda v: f(v, 2))
e4_rows = []
for s in ['CTRL_CRC', 'FULL_CRC']:
    for i, t in enumerate(thetas):
        r = e4k(s, t)
        e4_rows.append([th_lbl[i], s, sd_sci(r['sdc'], r['sdc_sd']), f(r['recall'], 4), ints(r['shadow_bytes']), ints(r['pages']),
                        f(r['lat_us'], 2) + ' ± ' + f(r['lat_sd'], 2), pct(r['dlat_vs_every_read_pct']) if r['dlat_vs_every_read_pct'] else '(base)', pct(r['overhead_pct'])])
_e4er = [r for r in CSV['e4'] if r['verify_mode'] == 'EVERY_READ' and r['scheme'] == 'FULL_CRC']
reads_per_run = st.mean(Fv(r, 'n_guarded_reads') for r in _e4er)
sim_s = D['common']['config']['n_ops'] * D['common']['config']['dt_op_s']
reads_per_page_s = reads_per_run / st.mean(Fv(r, 'n_pages_allocated') for r in _e4er) / sim_s
# FULL_CRC knee: first θ whose recall drops below 0.95, and the next point
_fth = [t for t in thetas if t != 'EVERY_READ']
_k = next(i for i, t in enumerate(_fth) if e4k('FULL_CRC', t)['recall'] < 0.95)
knee_lo, knee_hi = _fth[_k], _fth[_k + 1]

# ================================================================ E5
E5 = D['E5']
rpbs = [2048, 720, 512, 256, 128, 64, 32]
def e5(s, rpb): return next(r for r in E5 if r['scheme'] == s and r['ram_rows_per_bank'] == rpb)
for c in E5:
    c['spf_med'] = median(Fv(r, 'n_wrong_undetected') / Fv(r, 'n_flip_events') for r in c['_rows'])
def e5plot(c): return c['spf_med'] if c['scheme'] in ('NONE', 'SANITY') else c['sdc_per_flip']
def capfmt(c): return '{:,}'.format(int(c))
tree_pages = e5('NONE', 2048)['pages']
c_e5_sdc = chart('c-e5-sdc', {
    'title': '(a) Damage per injected flip',
    'aria': 'Line chart, log-log: undetected wrong answers per injected flip versus DRAM capacity in pages; median over seeds for NONE and SANITY, mean for CTRL_CRC.',
    'x': {'type': 'log', 'label': 'DRAM capacity (pages; tree ≈ %s)' % ints(tree_pages), 'ticks': [256, 1024, 4096, 16384], 'tickLabels': ['256', '1 K', '4 K', '16 K']},
    'y': {'type': 'log', 'label': 'undetected wrong answers per flip', 'fmt': 'sci'},
    'series': [{'name': sname(s), 'slot': SLOT[s], 'pts': [[e5(s, rpb)['capacity_pages'], e5plot(e5(s, rpb))] for rpb in sorted(rpbs)]} for s in ['NONE', 'SANITY', 'CTRL_CRC']]
}, capfmt, lambda v: sci(v))
c_e5_lat = chart('c-e5-lat', {
    'title': '(b) Mean operation latency',
    'aria': 'Line chart: mean op latency versus DRAM capacity for the four schemes.',
    'x': {'type': 'log', 'label': 'DRAM capacity (pages; tree ≈ %s)' % ints(tree_pages), 'ticks': [256, 1024, 4096, 16384], 'tickLabels': ['256', '1 K', '4 K', '16 K']},
    'y': {'type': 'lin', 'label': 'mean op latency (µs)', 'min': 0, 'fmt': 'f2'},
    'series': [{'name': s, 'slot': SLOT[s], 'pts': [[e5(s, rpb)['capacity_pages'], e5(s, rpb)['lat_us']] for rpb in sorted(rpbs)]} for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']]
}, capfmt, lambda v: f(v, 2))
e5_rows = []
for rpb in rpbs:
    for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']:
        r = e5(s, rpb)
        e5_rows.append([capfmt(r['capacity_pages']) if s == 'NONE' else '', s, f(r['n_flip_events'], 1), sdc_cell(r),
                        f(r['sdc_per_flip'], 4), ints(r['shadow_bytes']), ints(r['pages']),
                        f(r['lat_us'], 2) + ' ± ' + f(r['lat_sd'], 2), pct(r['overhead_pct'])])
gap_full = e5('FULL_CRC', 2048)['lat_us'] / e5('CTRL_CRC', 2048)['lat_us'] - 1
gap_small = e5('FULL_CRC', 32)['lat_us'] / e5('CTRL_CRC', 32)['lat_us'] - 1
small = [rpb for rpb in rpbs if 8 * rpb / tree_pages <= 0.18]          # capacities that hold ≤ 17.7 % of the tree
small_ctrl = [Fv(r, 'n_wrong_undetected') for rpb in small for r in e5('CTRL_CRC', rpb)['_rows']]
small_ctrl_max_sdc = max(e5('CTRL_CRC', rpb)['sdc'] for rpb in small)
small_frac = 8 * max(small) / tree_pages
E5ATTR = {rpb: attribution(e5('FULL_CRC', rpb)['_rows']) for rpb in (2048, 32)}
n_int1 = e5('NONE', 2048)['n_internal']
miss_free = all(Fv(r, 'ram_misses') == 0 for c in E1 for r in c['_rows'])   # E1 never misses (fully resident)

# ================================================================ E6
E6a = D['E6a']['rows']; E6b = D['E6b']['rows']
orders = [8, 32, 128, 253]; keysz = [200000, 1000000, 3000000, 5000000]
def e6a(s, o): return next(r for r in E6a if r['scheme'] == s and r['order'] == o)
def e6b(s, k): return next(r for r in E6b if r['scheme'] == s and r['keys'] == k)
klbl = {200000: '200 K', 1000000: '1 M', 3000000: '3 M', 5000000: '5 M'}
c_e6a_sdc = chart('c-e6a-sdc', {
    'title': '(a) E6a: SDC rate vs node order (200 K keys)',
    'aria': 'Line chart: SDC rate versus B+tree order; NONE median over seeds, CTRL_CRC mean; log scale.',
    'x': {'type': 'log', 'label': 'order (max keys per node)', 'ticks': orders, 'tickLabels': [str(o) for o in orders]},
    'y': {'type': 'log', 'label': 'SDC rate', 'fmt': 'sci'},
    'series': [{'name': sname(s), 'slot': SLOT[s], 'pts': [[o, sdc_plot(e6a(s, o))] for o in orders]} for s in ['NONE', 'CTRL_CRC']]
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
    'aria': 'Line chart: SDC rate versus number of keys; NONE median over seeds, CTRL_CRC mean; log scale.',
    'x': {'type': 'log', 'label': 'keys', 'ticks': keysz, 'tickLabels': [klbl[k] for k in keysz]},
    'y': {'type': 'log', 'label': 'SDC rate', 'fmt': 'sci'},
    'series': [{'name': sname(s), 'slot': SLOT[s], 'pts': [[k, sdc_plot(e6b(s, k))] for k in keysz]} for s in ['NONE', 'CTRL_CRC']]
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
                        ints(r['n_internal']) if r['n_internal'] else '—', sdc_cell(r), ints(r['shadow_bytes']),
                        f(r['lat_us'], 2), pct(r['overhead_pct']),
                        ('%.3f' % cr['ctrl_over_full_cost_ratio']) if cr else '', ('%.3f' % cr['predicted_ratio_read_weighted_ctrl_len_over_4096']) if cr else ''])
for k in keysz:
    for s in ['NONE', 'CTRL_CRC', 'FULL_CRC']:
        r = e6b(s, k)
        cr = crb[k] if s == 'CTRL_CRC' else None
        e6_rows.append(['E6b' if (k == 200000 and s == 'NONE') else '', ('%s keys' % klbl[k]) if s == 'NONE' else '', s, ints(r['pages']), '%d' % r['tree_height'],
                        ints(r['n_internal']) if r['n_internal'] else '—', sdc_cell(r), ints(r['shadow_bytes']),
                        f(r['lat_us'], 2), pct(r['overhead_pct']),
                        ('%.3f' % cr['ctrl_over_full_cost_ratio']) if cr else '', ('%.3f' % cr['predicted_ratio_read_weighted_ctrl_len_over_4096']) if cr else ''])
e6_ctrl = [e6a('CTRL_CRC', o)['sdc'] for o in orders] + [e6b('CTRL_CRC', k)['sdc'] for k in keysz]
e6_none_med = [e6a('NONE', o)['sdc_med'] for o in orders] + [e6b('NONE', k)['sdc_med'] for k in keysz]
e6_none_cv = [r['sdc_sd'] / r['sdc'] for r in [e6a('NONE', o) for o in orders] + [e6b('NONE', k) for k in keysz]]
order_range = orders[-1] / orders[0]; size_range = keysz[-1] / keysz[0]

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
    'aria': 'Line chart: SDC rate versus key stride exponent; median over seeds for NONE and SANITY, mean for CTRL_CRC; log scale.',
    'x': {'type': 'lin', 'label': 'key stride exponent k', 'min': 0, 'max': 32, 'ticks': ks, 'tickLabels': [str(k) for k in ks]},
    'y': {'type': 'log', 'label': 'SDC rate', 'fmt': 'sci'},
    'series': [{'name': sname(s), 'slot': SLOT[s], 'pts': [[k, sdc_plot(e7(s, k))] for k in ks]} for s in ['NONE', 'SANITY', 'CTRL_CRC']]
}, str, sci)
e7_rows = []
for k in ks:
    for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']:
        r = e7(s, k)
        e7_rows.append([('2<sup>%d</sup>' % k) if s == 'NONE' else '', s, sdc_cell(r), f(r['tp'], 1),
                        ('%.3f' % r['detection_ratio_vs_ctrl']) if s == 'SANITY' else '', ('%.3f' % r['predicted_ratio']) if s == 'SANITY' else '',
                        ints(r['shadow_bytes']), ints(r['pages']), f(r['lat_us'], 2) + ' ± ' + f(r['lat_sd'], 2), pct(r['overhead_pct'])])
maxdev = max(abs(e7('SANITY', k)['detection_ratio_vs_ctrl'] - (64 - k) / 64) for k in ks)
# checksums ignore key semantics: CTRL_CRC and FULL_CRC runs identical across strides?
def _sig(c): return [tuple(r[x] for x in ('n_wrong_undetected', 'tp', 'total_latency_s', 'n_recoveries')) for r in sorted(c['_rows'], key=lambda r: r['seed'])]
crc_identical = all(len({str(_sig(e7(s, k))) for k in ks}) == 1 for s in ['CTRL_CRC', 'FULL_CRC'])
# E7 stride 0 reproduces E1 at λ = 3e-3 column for column
_e7c = _e1c = 0; _shared = [c for c in CSV['e7'][0] if c != 'run_id' and c in CSV['e1'][0]]
e7_same = e7_tot = 0
for s in ['NONE', 'SANITY', 'CTRL_CRC', 'FULL_CRC']:
    a, b = bseed(e7(s, 0)['_rows']), bseed(e1(s, 3e-3)['_rows'])
    for sd_ in a:
        e7_tot += 1; e7_same += all(a[sd_][c] == b[sd_][c] for c in _shared)
# SANITY blind zone, event-based: low key bits where SANITY catches < 5 % of the key-flip events CTRL_CRC caught
BZ_THR = 0.05
def kb_ratio(k, b):
    S, C = e7('SANITY', k)['_rows'], e7('CTRL_CRC', k)['_rows']
    ct = sum(Fv(r, 'kb_tp_%02d' % b) for r in C)
    return (sum(Fv(r, 'kb_tp_%02d' % b) for r in S) / ct) if ct else None
bz_edge = {}
for k in ks:
    e = -1
    for b in range(64):
        q = kb_ratio(k, b)
        if q is not None and q < BZ_THR: e = b
        else: break
    bz_edge[k] = e
    assert not any((q := kb_ratio(k, b)) is not None and q < BZ_THR for b in range(e + 1, 64)), 'non-contiguous blind bits'
# the read-weighted estimator used in the C++ pass (SANITY kb_tp / kb_seen < 5 %, largest such bit) collapses on this backend
def rw_edge(k):
    S = e7('SANITY', k)['_rows']; bl = []
    for b in range(64):
        seen = sum(Fv(r, 'kb_seen_%02d' % b) for r in S)
        if seen and sum(Fv(r, 'kb_tp_%02d' % b) for r in S) / seen < BZ_THR: bl.append(b)
    return max(bl) if bl else None
rw_edges = sorted({rw_edge(k) for k in ks})
fanout_leaf = keys_per_leaf
E11 = {(r['level'], r['stride_log2']): r['n_blind_bits'] for r in D['E7']['blind_zone_event_based_E11']['rows']}
def bits_txt(e): return 'none' if e < 0 else ('0–%d' % e)
bz_rows = [['2<sup>%d</sup>' % k, bits_txt(bz_edge[k]), '%d' % k, '%.1f' % (k + math.log2(fanout_leaf)),
            ('%d' % E11[('leaf', k)]) if ('leaf', k) in E11 else '—', ('%d' % E11[('internal', k)]) if ('internal', k) in E11 else '—'] for k in ks]
e11_extra = sorted({E11[('internal', k)] - E11[('leaf', k)] for k in (0, 16, 32)})

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
shift_same_as_k0 = all(Fv(a, 'n_wrong_undetected') == Fv(bseed(e7('SANITY', 0)['_rows'])[a['seed']], 'n_wrong_undetected') for a in shf['_rows'])
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
_xs_max = max([r['sdc_med'] for r in g + [adjR, adjB, shf, r64, hm]])
c_x_sdc = chart('c-x-sdc', {
    'title': '(a) End-to-end SANITY silent-corruption rate (median)',
    'aria': 'Chart: SANITY SDC rate, median over seeds, versus page multiplier for grid dummies, adjacent dummies, shift and hash mapping.',
    'x': {'type': 'log', 'label': 'pages relative to the arm’s unpadded tree', 'ticks': [1, 2, 4, 8], 'tickLabels': ['1×', '2×', '4×', '8×'], 'min': 0.9, 'max': 9},
    'y': {'type': 'lin', 'label': 'SDC rate, SANITY median (×10^-3)', 'min': 0, 'max': math.ceil(_xs_max * 1.15 / 5e-4) * 5e-4, 'scale': 1e3, 'fmt': 'sci'},
    'series': [{'name': 'grid dummies', 'slot': 1, 'pts': [[pm(r), r['sdc_med'], ['no dummies', 'k = 31', 'k = 30', 'k = 29 (h = 4)'][i]] for i, r in enumerate(g)]},
               {'name': 'adjacent dummies', 'slot': 2, 'line': False, 'pts': [[pm(adjR), adjR['sdc_med'], 'K+1'], [pm(adjB), adjB['sdc_med'], 'K±1']]},
               {'name': 'shift', 'slot': 3, 'line': False, 'pts': [[1.0, shf['sdc_med'], 'K>>32']]},
               {'name': 'hash mapping', 'slot': 4, 'dash': True, 'pts': [[1.0, r64['sdc_med'], 'random64, unmapped'], [pm(hm), hm['sdc_med'], 'α = 0.5']]}],
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
               {'name': 'hash mapping', 'slot': 4, 'dash': True, 'pts': [[1.0, 1.0, 'random64, unmapped'], [pm(hm), hm['lat_multiplier_vs_sanity_1x'], 'α = 0.5']]},
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
    mv = '%s + %s' % (f(r['n_sdc_missing'], 1), f(r['n_sdc_value'], 1))
    if r['scheme'] in ('NONE', 'SANITY'): mv += '<br><span class="mu">median %s + %s</span>' % (f(r['missing_med'], 0), f(r['value_med'], 0))
    x_rows.append([esc(armname(r)), r['scheme'],
                   '%s<br><span class="mu">%.2f×</span>' % (ints(r['pages']), r['page_multiplier']), ints(r['n_internal']), '%d' % r['tree_height'],
                   ints(r['shadow_bytes']), sdc_cell(r), mv, ratio or '—',
                   '%s<br><span class="mu">%.2f×</span>' % (f(r['lat_us'], 2), r['lat_multiplier_vs_sanity_1x'])])
grid_dpp = [(g[i + 1]['detection_ratio'] - g[i]['detection_ratio']) * 100 for i in range(3)]
model_dpp = (g[1]['predicted_ratio'] - g[0]['predicted_ratio']) * 100
hash_miss = [h['missing_med'] for h in hsh]

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


# ================================================================ run counts and the backend comparison
runs = D['common']['run_counts']
n_e1_7 = sum(v for k, v in runs.items() if k != 'E22')
n_e22 = runs['E22']
assert n_e22 == sum(r['n_seeds'] for r in X if r['arm'].startswith(('grid k=30', 'grid k=29')))
n_e13 = sum(r['n_seeds'] for r in X if r['arm'] in ('none', 'adjacent right (E13)', 'adjacent both (E13)', 'none (plain random64 baseline)') or r['arm'].startswith('grid k=31'))
n_e21_rep = sum(r['n_seeds'] for r in X if r['arm'].startswith(('shift', 'hash')))
n_e21 = len(CSV['e21'])                       # includes the hash-mapped stride-key arm that is not reported
assert n_e13 == len(CSV['e13']) and n_e22 == len(CSV['e22'])
primary_runs = n_e1_7 + n_e13 + n_e22 + n_e21
def _pairs(k):
    a, b = DC[k], D[k]
    if isinstance(a, dict): a, b = (a['rows'], b['rows']) if 'rows' in a else (a['main'], b['main'])
    return list(zip(a, b))
lat_d = [(y['lat_us'] / x['lat_us'] - 1) * 100 for k in ['E1', 'E2', 'E3', 'E4', 'E6a', 'E6b', 'E7'] for x, y in _pairs(k)]
lat_d5 = [(y['lat_us'] / x['lat_us'] - 1) * 100 for x, y in _pairs('E5')]
lat_med, lat_lo, lat_hi = median(lat_d), min(lat_d), max(lat_d)
lat_e5_max = max(lat_d5, key=abs)

PAGE_SIZE = 4096
def us(v): return '%.2f µs' % v
def sg(v, d=1): return ('%+.*f' % (d, v)).replace('-', '−')

# ================================================================ HTML
P = []
A = P.append

A('<header class="ph"><p class="venue">Workshop paper draft</p>'
  '<h1>Where Bit Flips Hurt: Per-Level Differential Protection for In-Memory B+-Trees</h1>'
  '<p class="author">Author — Institution</p></header>')

_fn_runs = fn(f'Run count = E1–E7 including the rescaled E2b–E2e sweeps ({n_e1_7:,}), the E13 and E22 dummy-key arms ({n_e13 + n_e22}) and the E21 shift and '
              f'hash-mapping arms ({n_e21}, of which {n_e21 - n_e21_rep} runs of a hash-mapped stride-key arm are not reported), all on the Ramulator2 backend; '
              'header-only schemes are excluded. The earlier pass on a fixed-latency C++ DRAM model (§3) is not counted.')
A('<section class="abstract" aria-label="Abstract"><h2 class="abs">Abstract</h2>'
  '<p>Bit flips in DRAM silently corrupt in-memory B+-tree indexes, and a corrupted routing node can misdirect or contaminate the entire subtree beneath it. '
  'Current practice protects every page uniformly, overpaying where it matters least and leaving gaps where it matters most. '
  f'Using a fault-injection simulator over a B+-tree, a cycle-accurate DDR4 model (Ramulator2) and an SSD, we quantify the case for differential protection across {primary_runs:,} seed-matched runs.{_fn_runs} '
  f'Without protection, each bit flip leaves {fe_per_flip:.1f} keys wrong (against a ceiling of 1 if damage stayed local), and a checksum over the control plane alone '
  f'(node header, keys, child pointers) removes {fie_red * 100:.1f} % of that damage and {red * 100:.1f} % of silent wrong answers at {cost_ratio * 100:.0f} % of the latency cost of a full-page checksum. '
  'The amplification is therefore a routing effect, not payload corruption. '
  f'The reliable-memory budget has a closed-form optimum equal to the storage of the internal nodes, invariant across a {nint_range:.0f}× range of internal-node counts. '
  'Finally, the tree\'s key-ordering invariant is a free detector whose strength is a closed form in key sparsity, (64−k)/64, but internal separators are sparse by construction '
  'and so carry a structural blind spot on exactly the pages every traversal reads. Padding the key space with dummy keys buys about one bit of coverage per doubling of the tree; '
  'changing the key representation is far cheaper. '
  'Protection should therefore be allocated by level and field role, with parameters computable before deployment from fanout and key distribution.</p></section>')

# ---------------------------------------------------------------- 1 Introduction
_att_lo = min(ATTR[l]['ctrl'] for l in (1e-3, 3e-3)); _att_hi = max(ATTR[l]['ctrl'] for l in (1e-3, 3e-3))
A('<section id="s1"><h2><span class="sn">1</span>Introduction</h2>'
  '<p>An in-memory B+-tree is a small routing structure on top of a large payload: the few internal nodes are read on every lookup, each leaf only when its keys are wanted. '
  'A DRAM bit flip in a leaf value damages one key; the same flip in an internal separator or child pointer misroutes every later lookup through it, and inserts that follow the wrong route land in the wrong subtree (Figure 1). '
  'Uniform page protection, such as a CRC over every page, pays the same verification cost for both.</p>'
  + fig1 +
  '<p>We ask how much protection each part of the tree deserves, and whether the answer can be computed in advance. Four schemes (none, a free structural check, a control-plane checksum, a full-page checksum) are compared across eight experiments. Contributions:</p>'
  '<ul class="contrib">'
  f'<li><b>Attribution.</b> The control plane is about {_att_lo:.0f}–{_att_hi:.0f} % of corruption events but carries almost all wrong answers. CTRL_CRC, a CRC over header, keys and child pointers, cuts the silent-corruption (SDC) rate by {red * 100:.1f} % at {cost_ratio * 100:.0f} % of the latency overhead of FULL_CRC and the same reliable memory (§4.1).</li>'
  f'<li><b>A closed-form budget.</b> With a level-aware eviction policy, SDC saturates at exactly the bytes needed to cover every internal node, B<sub>int</sub>, in all four tree shapes we test ({ints(nint[0])} to {ints(nint[-1])} internal nodes) (§4.2).</li>'
  '<li><b>Robustness.</b> Uniform faults are the worst case at scale (§4.3); periodic verification saves little once only the control plane is checked (§4.4); shrinking DRAM concentrates the resident set on internal nodes, so eviction is not free scrubbing (§4.5); the CTRL_CRC/FULL_CRC cost ratio follows the read-weighted control-plane length (§4.6).</li>'
  '<li><b>Key sparsity.</b> The ordering check detects a fraction (64−k)/64 of what a checksum detects when keys are 2<sup>k</sup> apart, and is blind on exactly the low k bits of a leaf key; internal separators are sparser by the fanout, so it is blind on the routing pages even for dense keys (§4.7). Grid dummy keys raise the ratio by about one bit per doubling of pages without improving end-to-end SDC; adjacency, shifting and hashing are the useful alternatives (§4.8).</li>'
  '</ul></section>')

# ---------------------------------------------------------------- 2 Schemes
t1 = tblock('Protection schemes. All checks run on every guarded DRAM read (EVERY_READ) unless §4.4 says otherwise; a failed check reloads a clean copy from SSD (t<sub>ssd</sub> = 100 µs). Reliable memory is per protected page.',
            ['scheme', 'what is verified', 'reliable memory / page', 'verification cost per read'],
            [['NONE', 'nothing', '0 B', '0'],
             ['SANITY', 'structural invariants of the parsed node: node type valid, n_keys ≤ order and arrays in bounds, header padding zero, keys strictly increasing, child pointers in range and not self, leaf link in range', '0 B', 't<sub>sanity</sub> = 50 ns'],
             ['CTRL_CRC', 'CRC32 over bytes [0, 16 + ctrl_len): SSD header, node header, keys[], and children[] for internal nodes; leaf values[] and unused slack are excluded', '12 B' + fn('Accounted as 12 B per page so that budgets are comparable with FULL_CRC; an implementation also stores the 2-byte ctrl_len, i.e. 14 B per page (+17 %). This does not change any qualitative result.'), '20 ns + 0.5 ns × (16 + ctrl_len)'],
             ['FULL_CRC', 'CRC32 over the whole 4,096-byte page', '12 B', '20 ns + 0.5 ns × 4,096 ≈ 2.07 µs']], 99)
_kpl = round(keys_per_leaf)
_ctrl_leaf = 16 + 8 * _kpl; _vals = 8 * _kpl; _slack = PAGE_SIZE - 16 - _ctrl_leaf - _vals
A('<section id="s2"><h2><span class="sn">2</span>Protection schemes and the reliable-memory model</h2>'
  '<p><b>Page layout.</b> A node occupies one 4,096-byte page: bytes [0, 16) hold an SSD header, [16, 32) the node header (type, n_keys, leaf link), then keys[] (8 B each), then either children[] (internal nodes) or values[] (leaves); the rest is zero padding. '
  f'The control plane is ctrl_len = 16 + 8n bytes for a leaf with n keys and 24 + 16n bytes for an internal node, which is the whole live content of an internal node. At order 253 a typical leaf holds about {_kpl} keys, so its control plane is about {_ctrl_leaf:,} B, its values {_vals:,} B and its unused slack about {_slack:,} B.</p>'
  '<p><b>Schemes.</b> Table 1 lists the four schemes. A header-only CRC covers 16 of the 4,080 mutable bytes (under 1 % of a dense page); in our runs it left the SDC rate unchanged from no protection, which motivates extending the checksum to the full control plane (CTRL_CRC). '
  'SANITY needs no stored state: it is the set of invariants a B+-tree node must satisfy anyway.</p>'
  + t1 +
  '<p><b>Reliable memory and the shadow store.</b> Checksums live in a small reliable memory (e.g. ECC-protected or on-chip SRAM, 20 ns per access) organised as a shadow store of 12-byte entries keyed by page. Its capacity is a budget B in bytes. '
  'A page without an entry is read unverified. When the store is full, an eviction policy decides which pages keep entries: '
  '<span class="k">BY_LEVEL</span> admits a page only if its level is above the lowest level present and then evicts the oldest entry of the lowest level; '
  '<span class="k">LRU</span> evicts the least recently used entry; <span class="k">BY_HOTNESS</span> evicts the least frequently accessed (count without ageing); <span class="k">RANDOM</span> evicts uniformly at random. '
  'We write B<sub>int</sub> = n<sub>internal</sub> × 12 B for the bytes needed to cover every internal node and B<sub>full</sub> = pages × 12 B for full coverage.</p></section>')

# ---------------------------------------------------------------- 3 Method
_cfg = D['common']['config']
A('<section id="s3"><h2><span class="sn">3</span>Experimental method</h2>'
  '<p><b>Simulator stack.</b> A B+-tree of order 253 (the largest that fits a 4,096-byte internal node: 32 + 253 × 8 + 254 × 8 = 4,088 B) stores 8-byte keys and values in pages cached in DRAM in front of an SSD (t<sub>ssd</sub> = 100 µs, write-through). '
  'DRAM is simulated by Ramulator2, configured as DDR4-2400 (DDR4_8Gb_x8) with its ECC plugin off; capacity is 8 × rows-per-bank pages. '
  'Ramulator2 governs two things here: the timing of DRAM read hits and which bit of a page a flip lands on. Writes are charged a fixed write-through cost, and with 10 % inserts × 100 µs ≈ 10 µs per operation the SSD dominates mean latency. '
  'Each node read passes a guarded-read layer that applies the scheme and, for scoring only, compares the page with an oracle image at zero cost. '
  'One modelling fix was needed: on a DRAM miss the Ramulator2 adapter reloaded the page from SSD but did not charge the SSD access, so the harness now adds t<sub>ssd</sub> to every miss. '
  + ('Only E5 has misses (every other experiment keeps the tree resident), so only E5 latencies are affected.</p>' if miss_free else 'This matters mainly for E5, the only experiment designed to miss.</p>') +
  '<p><b>Fault injection.</b> The default model flips uniformly random bits in resident DRAM pages as a Poisson process of rate λ flips per page per second (default λ = 3×10<sup>−3</sup>, deliberately accelerated). '
  '§4.3 adds row hammer (0.7 events/s, each flipping bits with probability 10<sup>−4</sup> on two adjacent rows) and one-shot column faults at t = 150 s that flip the same (byte, bit) on 512 rows. The fault stream depends only on the seed, not on the scheme.</p>'
  f'<p><b>Workload.</b> {_cfg["prefill_keys"]:,} dense integer keys, inserted in shuffled order, build a tree of about {ints(n3["pages"])} pages (h = {n3["tree_height"]:.0f}, {n3["n_internal"]:.0f} internal nodes). '
  f'Then {_cfg["n_ops"]:,} operations ({_cfg["dt_op_s"] * 1000:.0f} ms simulated each) run: {_cfg["read_ratio"] * 100:.0f} % searches, {_cfg["miss_ratio"] * 100:.0f} % of them for absent keys, and {100 - _cfg["read_ratio"] * 100:.0f} % ascending inserts, i.e. about 27,000 searches per run. The 16,384-page DRAM keeps the tree resident except in §4.5.</p>'
  '<p><b>Metrics.</b> SDC rate = undetected wrong answers per search, scored against a reference map. <i>Cost</i> = reliable memory (peak shadow-store bytes) and pages allocated; <i>time</i> = mean operation latency, with overhead relative to NONE at the same setting. '
  'We do not use recall: for SANITY and CTRL_CRC it is dominated by harmless misses on payload and slack bytes. '
  f'<i>Heavy tails.</i> NONE and SANITY leave corruption in place, so one flip in a hot internal node can dominate a run: at λ = 3×10<sup>−3</sup> one SANITY seed returns {hot_w} wrong answers against {min(rest_w)}–{max(rest_w)} for the other four. '
  'Wherever the text or a figure reports a wrong-answer count or SDC rate for NONE or SANITY, it is therefore the <b>median over seeds</b>; the data tables keep mean ± SD and add the median. '
  'CTRL_CRC and FULL_CRC, whose seeds agree closely, are reported as means. Reductions relative to NONE are computed per seed (paired) and summarised by their median.</p>'
  '<p><b>Scale, seeds and pairing.</b> The 1 M-key, order-253 scale was chosen after smoke tests as the largest that keeps the full sweep tractable. E1 and E5–E7 use 5 seeds, E2–E4 use 3 (Appendix A). The fault schedule depends only on the seed, so schemes are compared paired by seed; '
  f'flip counts match exactly in {fm_match} of {fm_cells} E1 cells (the others differ by ≤ {fm_maxdiff * 100:.2f} %). Tables give mean ± sample SD over seeds; we report no bootstrap intervals in this draft and flag overlapping SDs in the text.</p>'
  f'<p><b>Earlier C++ model.</b> An earlier pass of every experiment used a pure C++ DRAM model with a fixed 100 ns access time and gave the same conclusions. Mean latencies on Ramulator2 are {-lat_med:.1f} % lower in the median '
  f'({sg(lat_lo)} % to {sg(lat_hi)} % over all cells of E1–E4, E6 and E7; up to {sg(lat_e5_max, 0)} % in E5, where misses dominate), because a DDR4 read hit is faster than 100 ns and everything else is the same fixed SSD cost. '
  'SDC rates differ by about the seed-to-seed spread, since different bits flip. That version of this page is kept as <code>paper_cpp_model.html</code>.</p></section>')

# ---------------------------------------------------------------- 4.1
def zero_list(pairs):
    """pairs: [(label, value)] -> labels whose plotted value is 0."""
    return [l for l, v in pairs if v == 0]
_z1 = zero_list([(s, sdc_plot(e1(s, 1e-5))) for s in ['NONE', 'SANITY']])
_z1c = sdc_plot(e1('CTRL_CRC', 1e-5)) == 0
_z1txt = ((', and the ' + ' and '.join(_z1) + (' median is' if len(_z1) == 1 else ' medians are')) if _z1 else '') + (' and CTRL_CRC' if _z1c else '') + (' 0 at λ = 10<sup>−5</sup>' if (_z1 or _z1c) else '')
fig2, F2 = figure([c_e1_sdc, c_e1_lat],
    f'CTRL_CRC removes {min(red_hi) * 100:.0f}–{max(red_hi) * 100:.0f} % of silent corruption at every λ ≥ 10<sup>−3</sup> and costs {cost_ratio * 100:.0f} % of FULL_CRC\'s latency overhead at λ = 3×10<sup>−3</sup>. '
    f'(a) Log–log SDC rate: median over seeds for NONE and SANITY (heavy tails, §3), mean for CTRL_CRC; FULL_CRC is 0 in every run{_z1txt} (not drawn). (b) Mean operation latency. 5 seeds.')
t_e1 = tblock(f'E1 cost and time at the verification floor (λ = 10<sup>−5</sup>), the working point (3×10<sup>−3</sup>) and the highest rate (3×10<sup>−2</sup>). SDC is mean ± SD over 5 seeds, with the median for NONE and SANITY. All λ values are in the Figure {F2} data tables.',
              ['λ', 'scheme', 'SDC ± sd', 'rel. mem (B)', 'pages', 'latency µs ± sd', 'vs NONE'], e1_rows, 2)
t_attr = tblock('Where corruption events land, from the per-event counters of the FULL_CRC runs (FULL_CRC repairs on first read, so each event is counted once; 5 seeds). The SSD header is inside CTRL_CRC\'s range too.',
                ['λ', 'events / run', 'control plane (CTRL_CRC-visible)', 'live values[]', 'unused slack', 'SSD header'],
                [[lamtxt(l), f(ATTR[l]['events'], 1), p1(ATTR[l]['ctrl']), p1(ATTR[l]['live']), p1(ATTR[l]['slack']), p2(ATTR[l]['hdr'])] for l in (1e-3, 3e-3, 3e-2)], 1)
_fn_fie = fn(f'Keys wrong at the end of the run (final integrity scan), means over 5 seeds at λ = 3×10<sup>−3</sup>: NONE {fie_none:,.0f} and CTRL_CRC {fie_ctrl:,.0f} per run, over {flips3:,.1f} injected flips. '
             'Read from the per-run CSV (<code>results/r2/e1_r2.csv</code>); paper_data.json does not export this column.')
A('<section id="s4"><h2><span class="sn">4</span>Results</h2>'
  '<section id="s41"><h3><span class="sn">4.1</span>E1: error rate × scheme</h3>'
  '<p class="setup"><b>Setup.</b> λ ∈ {10<sup>−5</sup>, …, 3×10<sup>−2</sup>} (7 values) × 4 schemes × 5 seeds; budget ∞, EVERY_READ, 1 M keys.</p>'
  + fig2 + t_e1 +
  f'<p><b>Findings.</b> At λ = 3×10<sup>−3</sup>, the median NONE run returns a silently wrong answer for {n3["sdc_med"] * 100:.1f} % of searches (SDC {sci(n3["sdc_med"])}). CTRL_CRC lowers this to {sci(c3["sdc"])} (−{red * 100:.1f} %, paired by seed), SANITY to {sci(s3["sdc_med"])}, and FULL_CRC to 0. '
  f'Each flip costs NONE {dmg_none:.3f} wrong answers and CTRL_CRC {dmg_ctrl:.4f}, a factor of {dmg_none / dmg_ctrl:.0f}; counted as keys wrong at the end of the run, NONE loses {fe_per_flip:.1f} keys per flip and CTRL_CRC removes {fie_red * 100:.1f} % of that.{_fn_fie}</p>'
  + t_attr +
  f'<p>Table {TNUM[0]} explains the leverage. Only {_att_lo:.0f}–{_att_hi:.0f} % of corruption events at λ ≤ 3×10<sup>−3</sup> touch the control plane, about a third ({p1(ATTR[3e-3]["live"])}) hit live values that CTRL_CRC by design cannot see, and about {ATTR[3e-3]["slack"]:.0f} % hit padding that is never read. '
  'Yet the control-plane events produce nearly all wrong answers, because a damaged separator or child pointer is re-read and misroutes on every traversal, while a damaged value affects one key.</p>'
  f'<p><b>Cost.</b> CTRL_CRC and FULL_CRC hold the same reliable memory ({ints(c3["shadow_bytes"])} B, 12 B × pages), so the difference is all in time. At the verification floor (λ = 10<sup>−5</sup>, almost no recoveries) CTRL_CRC adds {pct(c0["overhead_pct"])} and FULL_CRC {pct(f0["overhead_pct"])}, a ratio of {floor_ratio * 100:.0f} %; at the working point the ratio is {cost_ratio * 100:.0f} % ({c3["lat_us"] - n3["lat_us"]:.2f} vs {f3["lat_us"] - n3["lat_us"]:.2f} µs). '
  'Latency grows with λ for every detecting scheme because each detection triggers a 100 µs SSD reload.</p>'
  f'<p><b>SANITY.</b> With dense keys, SANITY\'s median SDC is {min(san_vs_ctrl):.2f}–{max(san_vs_ctrl):.2f}× CTRL_CRC\'s for λ ≥ 10<sup>−3</sup>, at lower latency ({pct(s3["overhead_pct"])} vs {pct(c3["overhead_pct"])} at the working point). '
  f'Its mean is pulled far above the median by single seeds: at λ = 3×10<sup>−3</sup> seed {hot_seed} returns {hot_w} wrong answers against {min(rest_w)}–{max(rest_w)} for the other seeds (mean {sci(s3["sdc"])}, median {sci(s3["sdc_med"])}), because an undetected flip sits in a hot internal node. '
  '§4.7 shows that the near-tie with CTRL_CRC is a property of dense keys.</p></section>')

# ---------------------------------------------------------------- 4.2
b_inf = e2('CTRL_CRC', 'BY_LEVEL', 'inf')
assert b512['sdc'] == e2('CTRL_CRC', 'BY_LEVEL', '1024')['sdc'] and e2('CTRL_CRC', 'BY_LEVEL', '256')['sdc'] > 5 * b512['sdc']   # 512 B is the knee
assert e2('CTRL_CRC', 'LRU', '4096')['sdc'] <= 1.05 * e2('CTRL_CRC', 'BY_LEVEL', '4096')['sdc'] and e2('CTRL_CRC', 'LRU', '1024')['sdc'] > 10 * b512['sdc']
_hr_best = min(e2('CTRL_CRC', p, b)['sdc'] for p in ('BY_HOTNESS', 'RANDOM') for b in budgets[:7])
fig3, F3 = figure([c_e2], f'BY_LEVEL reaches its floor at 512 B ({512 / full_bytes * 100:.1f} % of full coverage): once every internal node has an entry, more budget buys little. '
                  f'CTRL_CRC, 1 M keys, 3 seeds, λ = 3×10<sup>−3</sup>. The ∞ budget equals the 69 K point ({sci(b_inf["sdc"])} for all policies). FULL_CRC agrees with these curves within {ctrl_full_dev * 100:.0f} % below full coverage and is 0 at full coverage (not drawn).')
fig4, F4 = figure(e2r_panels, f'In all four tree shapes the BY_LEVEL curve has its knee at exactly 1.00 × B<sub>int</sub>, the bytes needed to cover every internal node, although the number of internal nodes varies {nint_range:.0f}×. '
                  f'FULL_CRC, 3 seeds. At B<sub>full</sub> and ∞ every policy has SDC = 0 (not drawn). Grid points are nominal multiples of the planned B<sub>int</sub>; the measured B<sub>int</sub> differs by ≤ {max(1, round(bint_dev * 100))} %.')
t_e2 = tblock('E2 cost and time (CTRL_CRC, 1 M keys). Each policy cell gives SDC and, below it, mean latency (overhead vs NONE). Reliable memory used equals the budget (entries × 12 B).',
              ['budget', 'rel. mem (B)', 'pages', 'BY_LEVEL', 'LRU', 'BY_HOTNESS', 'RANDOM'], e2_rows, 1)
t_knee = tblock('Knee at 1.00 × B<sub>int</sub> for the four rescaled configurations (FULL_CRC). SDC per policy at the knee; latency (overhead vs budget 0, i.e. unprotected) for BY_LEVEL and LRU at the knee and for full coverage.',
                ['config', 'pages', 'n<sub>int</sub>', 'knee (B)', '% B<sub>full</sub>', 'BY_LEVEL', 'LRU', 'BY_HOT.', 'RANDOM', 'LRU / BY_LEVEL', 'BY_LEVEL µs', 'LRU µs', 'B<sub>full</sub> µs'], knee_rows, 1)
for _cfg_ in ['E2B', 'E2C', 'E2D', 'E2E']:
    for _r in RS[_cfg_]['rows']:
        if _r['policy'] == 'BY_LEVEL' and _r['budget_bytes'] not in ('0', 'inf') and _r['sdc'] > 0:
            _l = next(q for q in RS[_cfg_]['rows'] if q['policy'] == 'LRU' and q['budget_bytes'] == _r['budget_bytes'])
            assert _r['sdc'] <= _l['sdc'], (_cfg_, _r['budget_bytes'])
kr = D['E2']['knee']
def rs_at(cfg, mult_idx, pol='BY_LEVEL'):
    rows = RS[cfg]['rows']
    xs = sorted(set(r['x_B_int'] for r in rows if r['budget_bytes'] != 'inf'))
    return next(r for r in rows if r['policy'] == pol and r['x_B_int'] == xs[mult_idx])
def rs_full(cfg, pol='BY_LEVEL'):
    return max((r for r in RS[cfg]['rows'] if r['policy'] == pol and r['budget_bytes'] != 'inf'), key=lambda r: float(r['budget_bytes']))
A('<section id="s42"><h3><span class="sn">4.2</span>E2: budget × policy</h3>'
  f'<p class="setup"><b>Setup.</b> (i) 1 M keys: CTRL_CRC and FULL_CRC × 4 policies × 9 budgets (0 B to ∞) × 3 seeds. (ii) Rescaled: four trees with {ints(nint[0])} to {ints(nint[-1])} internal nodes (orders 253, 64, 32, 16), budgets in multiples of B<sub>int</sub>, FULL_CRC, 3 seeds.</p>'
  + fig3 + t_e2 +
  f'<p><b>Findings at 1 M keys.</b> BY_LEVEL with 512 B ({b512["entries"]:.0f} entries, {512 / full_bytes * 100:.1f} % of the {full_bytes:,} B needed for full coverage) lowers SDC from {sci(b0["sdc"])} to {sci(b512["sdc"])} (−{(1 - b512["sdc"] / b0["sdc"]) * 100:.1f} %), within {b512["sdc"] / b_inf["sdc"]:.1f}× of full coverage. Its latency overhead is {pct(b512["overhead_pct"])}, against {pct(b_inf["overhead_pct"])} for full coverage. '
  f'The knee is where the store first holds all {b0["n_internal"] or n3["n_internal"]:.0f} internal nodes. LRU needs 4 KB to match (internal nodes stay recent because every search reads them). BY_HOTNESS and RANDOM barely help at any budget below full coverage (SDC ≥ {sci(_hr_best)}); BY_HOTNESS\'s counts never age, so early-hot leaves keep their entries over internal nodes created by later splits. '
  f'Below full coverage CTRL_CRC and FULL_CRC agree within {ctrl_full_dev * 100:.0f} %: under a tight budget, <i>which</i> pages are protected matters more than how much of each.</p>'
  + fig4 + t_knee +
  f'<p><b>Findings, rescaled.</b> The knee sits at 1.00 × B<sub>int</sub> in every configuration, and extra budget does little (E2d: {sci(rs_at("E2D", 5)["sdc"])} at 1×, {sci(rs_at("E2D", 7)["sdc"])} at 4×). As a share of B<sub>full</sub> the knee grows from {kr[0]["knee_pct_B_full"]:.2f} % to {kr[3]["knee_pct_B_full"]:.2f} %, exactly the internal-node share of the tree: the rule is “budget = storage of the internal nodes”, not “about 1 % of full”. '
  f'BY_LEVEL leads LRU at every budget, but its lead at the knee shrinks from {kr[0]["lru_over_by_level"]:.1f}× to {kr[3]["lru_over_by_level"]:.1f}× as LRU retains more internal nodes on its own. '
  f'The time cost grows with height, since each traversal verifies h − 1 internal nodes: {pct(rs_at("E2B", 5)["overhead_pct"])} (E2b, h = {RS["E2B"]["tree_height"]:.0f}) to {pct(rs_at("E2E", 5)["overhead_pct"])} (E2e, h = {RS["E2E"]["tree_height"]:.0f}) at the knee, against {pct(rs_full("E2B")["overhead_pct"])} and {pct(rs_full("E2E")["overhead_pct"])} for full coverage.</p></section>')

# ---------------------------------------------------------------- 4.3
_u = e3('uniform', 'NONE')['wpef_med']; _h = e3('hammer', 'NONE')['wpef_med']
_cols = sorted([e3('col_b128', 'NONE')['wpef_med'], e3('col_b3000', 'NONE')['wpef_med']])
_z3 = [lbl for lbl, c in (('SANITY\'s median', e3('col_b128', 'SANITY')), ('CTRL_CRC', e3('col_b128', 'CTRL_CRC'))) if e3plot(c) == 0]
assert all(t == col_rows for t in col_tp) and e3('col_b128', 'CTRL_CRC')['sdc'] == 0 and san_eq_none_b3000
fig5, F5 = figure([c_e3], 'Uniform faults do the most damage per flip; clustered faults are diluted across a large tree. A column fault in keys[] is fully caught by CTRL_CRC; one in values[] is not. '
                  'Log scale, 3 seeds; NONE and SANITY plot the median over seeds, CTRL_CRC the mean. Effective flips = FULL_CRC recoveries. '
                  f'FULL_CRC is 0 in every mode, and {" and ".join(_z3)} {"are" if len(_z3) > 1 else "is"} 0 for the byte-128 column fault (not drawn).')
t_e3 = tblock('E3 cost and time by fault mode. SDC is mean ± SD over 3 seeds, with the median for NONE and SANITY; undet. / eff. flip is the mean.',
              ['mode', 'scheme', 'eff. flips', 'SDC ± sd', 'undet. / eff. flip', 'rel. mem (B)', 'pages', 'latency µs ± sd', 'vs NONE'], e3_rows, 2)
_e3p = e3('uniform', 'NONE')['pages']
A('<section id="s43"><h3><span class="sn">4.3</span>E3: fault spatial structure</h3>'
  f'<p class="setup"><b>Setup.</b> Four fault modes (uniform λ = 3×10<sup>−3</sup>; row hammer; column fault at byte 128; column fault at byte 3000, all bit 3) × 4 schemes × 3 seeds, 1 M keys.</p>'
  + fig5 + t_e3 +
  f'<p><b>Findings.</b> Per effective flip, uniform faults cause {_u:.3f} undetected wrong answers under NONE, hammer {_h:.3f} and column faults {_cols[0]:.4f}–{_cols[1]:.4f}, so uniform is {_u / _cols[1]:.0f}–{_u / _cols[0]:.0f}× worse than a column fault. '
  f'A column fault hits {col_rows} rows, which is {col_rows / _e3p * 100:.1f} % of a {ints(_e3p)}-page tree, and each damaged key byte affects one of about {keys_per_leaf:.0f} keys in its leaf; uniform flips spread over every page and so meet far more lookups.</p>'
  f'<p>The two column faults isolate CTRL_CRC\'s boundary. At order 253, byte 128 lies in a leaf\'s keys[]: CTRL_CRC detects all {col_rows} flips in every seed and has SDC = 0, matching FULL_CRC at {pct(e3("col_b128", "CTRL_CRC")["overhead_pct"])} latency instead of {pct(e3("col_b128", "FULL_CRC")["overhead_pct"])}. '
  f'Byte 3000 lies in values[]: CTRL_CRC sees almost nothing ({e3("col_b3000", "CTRL_CRC")["recoveries"]:.1f} detections per run) and lowers SDC by only {paired_red(e3("col_b3000", "NONE"), e3("col_b3000", "CTRL_CRC")) * 100:.0f} % (paired median), and SANITY is identical to NONE because values carry no invariant. '
  'This is the intended trade-off, not a defect; §5 discusses protecting values where they matter.</p></section>')

# ---------------------------------------------------------------- 4.4
_f100, _c100, _fer, _cer = e4k('FULL_CRC', '100'), e4k('CTRL_CRC', '100'), e4k('FULL_CRC', 'EVERY_READ'), e4k('CTRL_CRC', 'EVERY_READ')
fig6, F6 = figure([c_e4_sdc, c_e4_lat], f'Relaxing the verification period saves FULL_CRC up to {-_f100["dlat_vs_every_read_pct"]:.1f} % of its latency but saves CTRL_CRC only {-_c100["dlat_vs_every_read_pct"]:.1f} %, at the same loss of protection, so with CTRL_CRC the knee is at every read. '
                  '(a) Log scale; FULL_CRC is 0 at every read (not drawn). (b) The dashed line is NONE. 3 seeds, λ = 3×10<sup>−3</sup>.')
t_e4 = tblock('E4 cost and time by verification period θ. Overhead is relative to E1 NONE at λ = 3×10<sup>−3</sup>, seeds 1–3 (E4 has no NONE rows).',
              ['θ (s)', 'scheme', 'SDC ± sd', 'recall', 'rel. mem (B)', 'pages', 'latency µs ± sd', 'Δ vs every read', 'vs NONE'], e4_rows, 2)
A('<section id="s44"><h3><span class="sn">4.4</span>E4: verification frequency</h3>'
  '<p class="setup"><b>Setup.</b> CTRL_CRC and FULL_CRC × verification period θ ∈ {every read, 0.1, 0.3, 1, 3, 10, 30, 100 s} × 3 seeds; a page is re-verified only if θ has passed since its last check.</p>'
  + fig6 + t_e4 +
  f'<p><b>Findings.</b> FULL_CRC\'s knee is at θ ≈ {knee_lo}–{knee_hi} s (recall {e4k("FULL_CRC", knee_lo)["recall"]:.3f} → {e4k("FULL_CRC", knee_hi)["recall"]:.3f}): with {ints(_fer["pages"])} pages and about {reads_per_run / 1e6:.1f} M guarded reads per run, each page is read about {reads_per_page_s:.1f} times per second, so short periods still verify most reads. '
  f'At θ = 100 s, FULL_CRC saves {-_f100["dlat_vs_every_read_pct"]:.1f} % of latency ({_fer["lat_us"] - _f100["lat_us"]:.2f} µs) and CTRL_CRC {-_c100["dlat_vs_every_read_pct"]:.1f} % ({_cer["lat_us"] - _c100["lat_us"]:.2f} µs), while their SDC rates are almost equal ({sci(_f100["sdc"])} vs {sci(_c100["sdc"])}). '
  f'CTRL_CRC has less to save because each check already covers only about a third of a page ({_ctrl_leaf:,} of 4,096 bytes for a typical leaf). '
  f'Its recall barely moves ({_cer["recall"]:.4f} → {_c100["recall"]:.4f}) while SDC grows {_c100["sdc"] / _cer["sdc"]:.0f}×: recall is dominated by harmless payload misses and is the wrong metric for this scheme.</p></section>')

# ---------------------------------------------------------------- 4.5
_n2048, _n32 = e5('NONE', 2048), e5('NONE', 32)
_z5 = [capfmt(e5('CTRL_CRC', rpb)['capacity_pages']) for rpb in sorted(rpbs) if e5plot(e5('CTRL_CRC', rpb)) == 0]
fig7, F7 = figure([c_e5_sdc, c_e5_lat], f'Shrinking DRAM makes each flip more harmful for NONE, not less, while CTRL_CRC approaches zero SDC; the FULL_CRC latency premium over CTRL_CRC shrinks from {gap_full * 100:.0f} % to {gap_small * 100:.0f} %. '
                  '(a) Undetected wrong answers per injected flip, log–log; median over seeds for NONE and SANITY, mean for CTRL_CRC; '
                  f'zero values (CTRL_CRC at {" and ".join(_z5)} pages, FULL_CRC everywhere) are not drawn. (b) Latency; every DRAM miss is charged t<sub>ssd</sub>. 5 seeds.')
t_e5 = tblock('E5 cost and time by DRAM capacity (8 × rows-per-bank pages). Pages = tree pages. SDC is mean ± SD, with the median for NONE and SANITY; SDC / flip is computed per seed, then averaged.',
              ['capacity (pages)', 'scheme', 'flips', 'SDC ± sd', 'SDC / flip', 'rel. mem (B)', 'pages', 'latency µs ± sd', 'vs NONE'], e5_rows, 2)
_fn_e5 = fn(f'SDC/flip is computed per seed; the text and Figure {FNUM[0]}a use the median over seeds, Table {TNUM[0]} the mean ({_n2048["sdc_per_flip"]:.3f} → {_n32["sdc_per_flip"]:.3f} for NONE). '
            'We do not report ram_misses: the final integrity scan runs on a frozen clock, so most of that counter comes from the scan. SDC, latency and flip counts are counted in the main loop only and are unaffected.')
_small_zero = sum(1 for w in small_ctrl if w == 0); _small_nz = sorted({int(w) for w in small_ctrl if w})
_e5red = 1 - _n32['sdc_med'] / _n2048['sdc_med']
A('<section id="s45"><h3><span class="sn">4.5</span>E5: DRAM capacity</h3>'
  f'<p class="setup"><b>Setup.</b> DRAM capacity from 16,384 down to 256 pages ({16384 / tree_pages:.1f}× to {256 / tree_pages:.3f}× the tree) × 4 schemes × 5 seeds. Flips hit only resident pages, evicted pages reload clean from SSD, and each miss costs t<sub>ssd</sub> (§3).</p>'
  + fig7 + t_e5 +
  f'<p><b>Findings.</b> One might expect eviction to scrub corrupted pages for free. At this node density it does the opposite: NONE\'s damage per flip rises from {_n2048["spf_med"]:.2f} at full residency to {_n32["spf_med"]:.2f} at 256 pages.{_fn_e5} Raw SDC still falls slightly ({sci(_n2048["sdc_med"])} → {sci(_n32["sdc_med"])}) only because {_n2048["n_flip_events"] / _n32["n_flip_events"]:.0f}× fewer flips land. '
  f'The cause is targeting. Internal nodes are read on every search and so never leave the cache: the {n_int1:.0f} internal nodes are {n_int1 / tree_pages * 100:.1f} % of the tree but {n_int1 / 256 * 100:.0f} % of a 256-page cache, so a larger share of flips lands on routing pages. '
  f'Per-event attribution (FULL_CRC) shows the same shift: the CTRL_CRC-visible share rises from {p1(E5ATTR[2048]["ctrl"])} to {p1(E5ATTR[32]["ctrl"])} and the live-value share falls from {p1(E5ATTR[2048]["live"])} to {p1(E5ATTR[32]["live"])}, although only {E5ATTR[32]["events"]:.0f} events per run remain at 256 pages.</p>'
  f'<p>The same shift helps CTRL_CRC. At capacity ≤ {capfmt(8 * max(small))} pages ({small_frac * 100:.1f} % of the tree or less) its SDC is at most {sci(small_ctrl_max_sdc)}: {_small_zero} of {len(small_ctrl)} runs have no wrong answer and the other {len(small_ctrl) - _small_zero} have {" or ".join(str(v) for v in _small_nz)} each, close to FULL_CRC\'s 0. '
  f'FULL_CRC\'s latency premium over it falls from {gap_full * 100:.1f} % to {gap_small * 100:.1f} %, since SSD misses dominate both (NONE itself goes from {_n2048["lat_us"]:.1f} to {_n32["lat_us"]:.1f} µs). '
  f'Trading DRAM for reliability is a bad deal at this scale: NONE pays {_n32["lat_us"] / _n2048["lat_us"]:.1f}× latency for a {_e5red * 100:.0f} % reduction in median SDC, while CTRL_CRC at full residency removes {red * 100:.1f} % for {pct(c3["overhead_pct"])}.</p></section>')

# ---------------------------------------------------------------- 4.6
fig8, F8 = figure([c_e6a_sdc, c_e6a_lat, c_e6b_sdc, c_e6b_lat],
                  f'CTRL_CRC keeps SDC in a narrow band ({min(e6_ctrl) * 1e4:.1f}–{max(e6_ctrl) * 1e4:.1f} × 10<sup>−4</sup>) across a {order_range:.0f}× range of node order and a {size_range:.0f}× range of tree size, while the NONE median varies {max(e6_none_med) / min(e6_none_med):.0f}×. Its cost relative to FULL_CRC is smallest for sparse nodes. '
                  'NONE plots the median over seeds, CTRL_CRC the mean. FULL_CRC is 0 everywhere (not drawn). 5 seeds.')
t_e6 = tblock('E6 cost and time. CTRL/FULL = (lat<sub>CTRL</sub> − lat<sub>NONE</sub>) / (lat<sub>FULL</sub> − lat<sub>NONE</sub>); “model” = read-weighted ctrl_len / 4,096 from the measured per-level node counts. Reliable memory is the same for CTRL_CRC and FULL_CRC. SDC is mean ± SD, with the median for NONE.',
              ['axis', 'setting', 'scheme', 'pages', 'h', 'n<sub>int</sub>', 'SDC ± sd', 'rel. mem (B)', 'latency µs', 'vs NONE', 'CTRL/FULL', 'model'], e6_rows, 3)
_h8 = e6a('NONE', 8)['tree_height']
A('<section id="s46"><h3><span class="sn">4.6</span>E6: node density and scale</h3>'
  f'<p class="setup"><b>Setup.</b> E6a: order ∈ {{8, 32, 128, 253}} with 200 K keys (h = {", ".join("%d" % e6a("NONE", o)["tree_height"] for o in orders)}). E6b: order 253 with 200 K, 1 M, 3 M and 5 M keys (h = 3 throughout). NONE, CTRL_CRC and FULL_CRC × 5 seeds, fully resident.</p>'
  + fig8 + t_e6 +
  f'<p><b>Findings.</b> The control plane\'s share of a page shrinks with order: at order 8 only {cra[8]["predicted_ratio_read_weighted_ctrl_len_over_4096"] * 100:.1f} % of the bytes FULL_CRC hashes per lookup are control plane (read-weighted), and with h = {_h8:.0f} it hashes {_h8:.0f} full pages per lookup, so FULL_CRC costs {pct(e6a("FULL_CRC", 8)["overhead_pct"])} against CTRL_CRC\'s {pct(e6a("CTRL_CRC", 8)["overhead_pct"])}. '
  f'The CTRL/FULL cost ratio is {" / ".join("%.3f" % cra[o]["ctrl_over_full_cost_ratio"] for o in orders)} for orders 8–253 and follows the byte model (read-weighted ctrl_len / 4,096: {" / ".join("%.3f" % cra[o]["predicted_ratio_read_weighted_ctrl_len_over_4096"] for o in orders)}). '
  f'Along the size axis the ratio rises from {crb[200000]["ctrl_over_full_cost_ratio"]:.2f} to {crb[5000000]["ctrl_over_full_cost_ratio"]:.2f} because the root and level-1 nodes fill up as N grows while h stays 3; the byte model overestimates at 3–5 M keys ({crb[3000000]["predicted_ratio_read_weighted_ctrl_len_over_4096"]:.2f}, {crb[5000000]["predicted_ratio_read_weighted_ctrl_len_over_4096"]:.2f}) because the measured overheads also include recovery reloads. '
  f'Across all eight trees CTRL_CRC holds SDC between {sci(min(e6_ctrl))} and {sci(max(e6_ctrl))}. NONE\'s run-to-run spread is large in every tree (SD/mean {min(e6_none_cv):.2f}–{max(e6_none_cv):.2f}): whether a flip hits a busy level-1 node decides the run.</p></section>')

# ---------------------------------------------------------------- 4.7
_sg = e7('SANITY', 32)['sdc_med'] / e7('SANITY', 0)['sdc_med'] - 1
assert crc_identical and e7_same == e7_tot and [bz_edge[k] for k in ks] == [k - 1 for k in ks]
fig9, F9 = figure([c_e7_ratio, c_e7_sdc], f'SANITY\'s detection relative to a checksum falls as (64−k)/64 when keys are 2<sup>k</sup> apart (all five points within {maxdev * 100:.1f} pp), and its median SDC grows {_sg * 100:.0f} % while CTRL_CRC\'s is unchanged. '
                  '(b) Log scale; median over seeds for NONE and SANITY, mean for CTRL_CRC; FULL_CRC is 0 at every stride (not drawn). 5 seeds, λ = 3×10<sup>−3</sup>.')
t_e7 = tblock('E7 cost and time by key stride. tp = page-level detections per run; ratio = SANITY tp / CTRL_CRC tp at the same stride. SDC is mean ± SD, with the median for NONE and SANITY.',
              ['stride', 'scheme', 'SDC ± sd', 'tp', 'ratio', 'model', 'rel. mem (B)', 'pages', 'latency µs ± sd', 'vs NONE'], e7_rows, 2)
_lgf = math.log2(fanout_leaf)
t_bz = tblock(f'SANITY\'s blind zone. Measured: key bits where SANITY catches &lt; {BZ_THR * 100:.0f} % of the key-flip events CTRL_CRC catches (E7, Ramulator2, all levels pooled); it is exactly the low k bits. '
              f'Separator gap: analytic, k + log<sub>2</sub>(fanout ≈ {fanout_leaf:.0f}). The last two columns count blind low bits under single-level injection (E11): <b>C++ DRAM model, not rerun on Ramulator2</b>; E11 ran strides 0, 16 and 32 only.',
              ['stride', 'blind bits (measured)', 'leaf gap (log<sub>2</sub>)', 'separator gap (log<sub>2</sub>)', 'E11 leaf (C++)', 'E11 internal (C++)'], bz_rows, 2)
_fn_rw = fn(f'The C++ pass located the edge with a read-weighted estimator (largest bit with SANITY kb_tp / kb_seen &lt; {BZ_THR * 100:.0f} %). On Ramulator2 that estimator is dominated by the hot-node SANITY seed (§3), whose single undetected flip is re-read on many searches and outweighs every other event, '
            f'and it returns bit {" / ".join(str(e) for e in rw_edges)} at every stride; we therefore count events instead.')
A('<section id="s47"><h3><span class="sn">4.7</span>E7: key sparsity</h3>'
  f'<p class="setup"><b>Setup.</b> Keys = index × 2<sup>k</sup> for k ∈ {{0, 8, 16, 24, 32}} (k = 0 reproduces E1 exactly: all {len(_shared)} shared columns in all {e7_tot} runs) × 4 schemes × 5 seeds.</p>'
  '<p><b>Model.</b> With adjacent keys 2<sup>k</sup> apart, flipping bit b &lt; k moves a key by 2<sup>b</sup> &lt; 2<sup>k</sup>, which cannot pass a neighbour, so the strict-order check stays satisfied. Only flips in the top 64 − k bits can break ordering, so SANITY should detect a fraction (64−k)/64 of what a checksum detects. A checksum ignores key semantics and should not change at all.</p>'
  + fig9 + t_e7 +
  f'<p><b>Findings.</b> The measured ratio is {" / ".join("%.3f" % e7("SANITY", k)["detection_ratio_vs_ctrl"] for k in ks)} against the model\'s 1 / 0.875 / 0.750 / 0.625 / 0.500. CTRL_CRC and FULL_CRC are identical, run for run, at all five strides. This is the built-in control: the stride changes only key semantics, not injection or timing. '
  f'SANITY\'s median SDC grows from {sci(e7("SANITY", 0)["sdc_med"])} to {sci(e7("SANITY", 32)["sdc_med"])}; its latency falls ({e7("SANITY", 0)["lat_us"]:.2f} → {e7("SANITY", 32)["lat_us"]:.2f} µs) only because it detects, and therefore reloads, less. So E1\'s near-tie between SANITY and CTRL_CRC is a property of dense keys.</p>'
  + t_bz +
  f'<p>Table {TNUM[0]} locates the blind zone directly. Per key bit, we count the key-flip events SANITY caught as a share of those CTRL_CRC caught. The blind bits are exactly 0 … k − 1 at every stride ({", ".join(bits_txt(bz_edge[k]) for k in ks)}), as the model predicts.{_fn_rw} '
  f'Internal separators are sparser than leaf keys by the fanout: adjacent separators are about {fanout_leaf:.0f} leaf keys apart, so their blind zone should extend about log<sub>2</sub> {fanout_leaf:.0f} ≈ {_lgf:.1f} bits further. E7 pools all levels and cannot isolate this; '
  f'the single-level injection experiment E11, run on the C++ DRAM model and not rerun on Ramulator2, confirms it, with {" / ".join(str(E11[("internal", k)]) for k in (0, 16, 32))} blind bits on internal separators against {" / ".join(str(E11[("leaf", k)]) for k in (0, 16, 32))} on leaf keys at k = 0 / 16 / 32, i.e. {" / ".join(str(v) for v in e11_extra)} bits more. '
  'So even with dense keys the low ~7 bits of every separator are invisible to SANITY, and separators sit on every search path. The free check is weakest exactly where damage is most expensive.</p></section>')

# ---------------------------------------------------------------- 4.8
assert all(g[i + 1]['n_keyflip_real_tp'] <= g[i]['n_keyflip_real_tp'] for i in range(3)) and all(gc[i + 1]['n_keyflip_real_tp'] < gc[i]['n_keyflip_real_tp'] for i in range(3))
assert shift_same_as_k0 and adjR['sdc_med'] < shf['sdc_med'] < g[0]['sdc_med'] and max(h['sdc_med'] for h in hsh) < min(shf['sdc_med'], adjR['sdc_med'])
fig10, F10 = figure([c_x_ratio, c_x_tp], 'Grid dummies raise SANITY\'s detection ratio by about one bit per doubling of pages, as the model predicts, but only because CTRL_CRC\'s count falls; SANITY detects no more real-key flips. '
                    f'Adjacent dummies reach {adjR["detection_ratio"]:.3f} at {pm(adjR):.0f}× pages. Stride-2<sup>32</sup> keys, 5 seeds. The shift point (hollow) is the E7 stride-0 page-level ratio, since the shift arm has no CTRL_CRC rows.')
fig11, F11 = figure([c_x_sdc, c_x_lat], f'End to end, grid dummies do not improve SANITY, and they cost latency roughly in proportion to pages. Shift adds no pages and lowers the median SDC by {(1 - shf["sdc_med"] / g[0]["sdc_med"]) * 100:.0f} %; adjacent dummies do slightly better at {pm(adjR):.0f}× pages; '
                    f'hash mapping gives the lowest SDC and is the option for irregular keys, at about 2× pages and {hm["lat_multiplier_vs_sanity_1x"]:.1f}× latency. (a) Median over 5 seeds. '
                    f'Hash mapping is shown from its own unmapped random-key baseline (1×) to α = 0.5; α = 0.25 and 0.75 are in Table {TNUM[0] + 1}.')
t_x = tblock('E7ext cost and time for every arm. Keys are stride 2<sup>32</sup> except the random64 and hash arms. Pages (× vs the unpadded tree of the same key set); rel. mem is 0 B for SANITY and NONE; SDC is mean ± SD, with the median for SANITY and NONE; missing + value = undetected wrong answers per run by kind (mean; median below); ratio = Σ SANITY / Σ CTRL_CRC real-key flip detections (model in parentheses); latency (× vs plain SANITY on the same key set).',
             ['arm', 'scheme', 'pages', 'n<sub>int</sub>', 'h', 'rel. mem (B)', 'SDC ± sd', 'missing + value', 'ratio (model)', 'latency µs'], x_rows, 2)
A('<section id="s48"><h3><span class="sn">4.8</span>Raising key density: grid dummies, shift and hash mapping</h3>'
  f'<p class="setup"><b>Setup.</b> Stride-2<sup>32</sup> keys (1 M prefill plus about {g[0]["real_keys"] - 1e6:,.0f} appends), SANITY only, with CTRL_CRC run alongside as the reference for detection. '
  '<i>Grid dummies</i> insert sentinel keys K + j·2<sup>k</sup> (k = 31, 30, 29: 1, 3 or 7 per real key) through the normal insert path, so their cost is counted. <i>Adjacent dummies</i> insert K + 1 (and K − 1). '
  '<i>Shift</i> stores K ≫ 32, which removes the stride when it is known. <i>Hash mapping</i> maps random 64-bit keys into a dense range (load α; two tree entries per key). Geometry is scaled so every tree stays fully resident. 5 seeds per cell.</p>'
  + fig10 +
  '<p><b>Grid dummies: the ratio rises, protection does not.</b> Each doubling of entries halves the gap, so the model predicts one more visible bit '
  f'(+{model_dpp:.1f} pp per doubling). The measured ratio rises {" → ".join("%.3f" % r["detection_ratio"] for r in g)} ({", ".join(sg(d) for d in grid_dpp)} pp; model {g[3]["predicted_ratio"]:.3f} at 8×). '
  f'But SANITY catches no more real-key flips, in fact fewer: {" → ".join(f(r["n_keyflip_real_tp"], 0) for r in g)} per run. '
  f'The ratio rises because CTRL_CRC\'s count falls faster ({" → ".join(f(r["n_keyflip_real_tp"], 0) for r in gc)}) as real keys hold a shrinking share of each page. The gain is relative only.</p>'
  + fig11 + t_x +
  f'<p><b>End to end nothing improves.</b> SANITY\'s median SDC goes from {sci(g[0]["sdc_med"])} with no dummies to {sci(g[1]["sdc_med"])}, {sci(g[2]["sdc_med"])} and {sci(g[3]["sdc_med"])} '
  f'(median undetected answers per run {g[0]["wrong_med"]:.0f} → {g[1]["wrong_med"]:.0f}, {g[2]["wrong_med"]:.0f}, {g[3]["wrong_med"]:.0f}; missing answers {g[0]["missing_med"]:.0f} → {g[1]["missing_med"]:.0f}, {g[2]["missing_med"]:.0f}, {g[3]["missing_med"]:.0f}). '
  f'More pages receive more flips ({g[0]["flips"]:,.0f} → {g[3]["flips"]:,.0f} per run at 8×) and hold more internal nodes in the blind zone; the 8× tree is also taller (h = {g[3]["tree_height"]:.0f}), a confound. With n = 5 the differences are within seed spread, and no grid arm clearly beats the baseline. '
  f'Cost scales with pages: {" / ".join("%.0f×" % round(r["page_multiplier"]) for r in g[1:])} pages give {" / ".join("%.2f×" % r["lat_multiplier_vs_sanity_1x"] for r in g[1:])} SANITY latency, and CTRL_CRC\'s reliable memory grows {ints(gc[0]["shadow_bytes"])} → {ints(gc[3]["shadow_bytes"])} B.</p>'
  f'<p><b>Contrasts.</b> Adjacent dummies make every key\'s low bits matter to its neighbour: ratio {adjR["detection_ratio"]:.3f} at {adjR["page_multiplier"]:.2f}× pages and {adjR["lat_multiplier_vs_sanity_1x"]:.2f}× latency, with median SDC {sci(adjR["sdc_med"])} ({(1 - adjR["sdc_med"] / g[0]["sdc_med"]) * 100:.0f} % below the baseline; median missing answers fall to {adjR["missing_med"]:.0f}). '
  f'Shift adds no pages or reliable memory and yields exactly the stride-0 tree, so SANITY behaves as at k = 0 (ratio {e7_shift_ratio:.3f}, median SDC {sci(shf["sdc_med"])}, −{(1 - shf["sdc_med"] / g[0]["sdc_med"]) * 100:.0f} % vs the stride-2<sup>32</sup> baseline); its {shf["lat_multiplier_vs_sanity_1x"]:.2f}× latency is the cost of reloading the extra detected pages. It needs a known stride. '
  f'For irregular keys, hash mapping lowers SANITY\'s median SDC from {sci(r64["sdc_med"])} (unmapped random keys, ratio {r64["detection_ratio"]:.3f}) to {sci(min(h["sdc_med"] for h in hsh))}–{sci(max(h["sdc_med"] for h in hsh))} at about 2× pages and {min(h["lat_multiplier_vs_sanity_1x"] for h in hsh):.2f}–{max(h["lat_multiplier_vs_sanity_1x"] for h in hsh):.2f}× latency ({min(h["probes_per_hit"] for h in hsh):.2f}–{max(h["probes_per_hit"] for h in hsh):.2f} probes per hit); '
  f'median missing answers fall from {r64["missing_med"]:.0f} to {min(hash_miss):.0f}–{max(hash_miss):.0f} per run. It gives up key order and hence range scans. E21 has no CTRL_CRC rows, so no ratio is reported.</p>'
  '<p><b>Verdict.</b> Grid dummies buy about one bit of SANITY coverage per doubling of the tree, which is the predicted rate and not worth paying. Where keys are sparse, change the representation (shift, or hash mapping when order is not needed) or use adjacency; otherwise checksum the control plane.</p></section></section>')

# ---------------------------------------------------------------- 5, 6
_e3unif = e3('uniform', 'FULL_CRC')['effective_flips']
A('<section id="s5"><h2><span class="sn">5</span>Discussion</h2>'
  '<p><b>What follows for differential protection.</b> The results reduce protection to quantities known before deployment. '
  '(1) <i>Where</i> to spend reliable memory: on internal nodes first, with a level-aware policy and a budget of B<sub>int</sub> = n<sub>internal</sub> × entry size, which follows from N and the fanout. '
  f'(2) <i>What</i> to checksum: the control plane, whose cost relative to a full-page checksum is the read-weighted ctrl_len / 4,096, about {cra[8]["ctrl_over_full_cost_ratio"]:.2f} for sparse nodes and {crb[200000]["ctrl_over_full_cost_ratio"]:.2f}–{crb[5000000]["ctrl_over_full_cost_ratio"]:.2f} at order 253. '
  '(3) <i>When</i> a free check suffices: the ordering invariant covers (64−k)/64 of key flips, nearly a checksum on dense leaves, but its separator blind zone leaves internal nodes needing a real checksum. '
  f'Values stay unprotected under CTRL_CRC (about a third of events at order 253, {p1(ATTR[3e-3]["live"])}); a checksum on hot leaves is the natural next step, not evaluated here.</p>'
  '<p><b>Limitations.</b> '
  '<i>Accelerated λ.</i> λ = 3×10<sup>−3</sup> flips/page/s is far above field DRAM rates; the 3.5-decade sweep shows the ranking is stable, but absolute SDC rates are not field predictions. '
  '<i>DRAM-only flips.</i> We inject only into DRAM-resident pages: no SSD, controller, CPU-cache or reliable-memory faults, and Ramulator2\'s ECC plugin is off. '
  '<i>Single workload.</i> 90 % point searches and 10 % ascending inserts on integer keys, single-threaded, with no deletes and no range scans; Ramulator2 times DRAM reads, but writes use a fixed write-through cost and SSD write-through dominates latency. '
  '<i>Frozen-clock scan.</i> The end-of-run integrity scan does not advance the clock, degrading the LRU during the scan; we omit ram_misses in E5 (SDC, latency and flips are unaffected). '
  f'<i>Heavy tails.</i> NONE and SANITY SDC depend on whether a flip hits a busy internal node: one SANITY seed returns {hot_w} wrong answers where the others return {min(rest_w)}–{max(rest_w)}, and NONE\'s SD reaches {max(e6_none_cv):.2f}× its mean (E6). We report medians for these schemes and read their magnitudes as orders of magnitude. '
  f'<i>E3 confounds.</i> Fault modes differ in flip count and timing as well as structure (column faults are one-shot at t = 150 s, {col_rows} flips against about {_e3unif:,.0f}), so per-flip normalisation compares mechanisms only approximately. '
  '<i>Mixed provenance.</i> E2–E4 use 3 seeds, the level split of the blind zone (E11) comes from the earlier C++ model, and no bootstrap intervals are reported.</p></section>'
  '<section id="s6"><h2><span class="sn">6</span>Conclusion</h2>'
  f'<p>In a dense in-memory B+-tree, silent corruption is a routing problem. A checksum over the control plane removes about {red * 100:.0f} % of silent wrong answers at roughly {cost_ratio * 100:.0f} % of the time cost of checksumming whole pages, and a reliable-memory budget equal to the internal nodes\' storage captures nearly all of the benefit, in every tree shape we tried. '
  'The free ordering check is a useful complement whose strength is a closed form in key sparsity. Its blind spot on separators, and the poor return from padding keys with dummies, argue for checksumming internal nodes and fixing key representation instead. '
  'Each parameter (B<sub>int</sub>, the cost ratio, the ordering-check coverage) can be computed from fanout and key distribution before deployment.</p></section>')

# ---------------------------------------------------------------- Appendix
def rc(k): return '{:,}'.format(runs[k])
n_e2r = sum(runs[k] for k in ('E2B', 'E2C', 'E2D', 'E2E'))
_seeds = D['common']['seeds']
def ns(k): return str(len(_seeds[k]))
_xs = {r['n_seeds'] for r in X}; assert len(_xs) == 1; _xseeds = str(_xs.pop())
app_rows = [
    ['E1', 'λ (7) × scheme (4)', ns('E1'), rc('E1'), '1 M keys, order 253, budget ∞, EVERY_READ'],
    ['E2', 'policy (4) × budget (9) × {CTRL_CRC, FULL_CRC}', ns('E2'), rc('E2'), 'λ = 3×10<sup>−3</sup>'],
    ['E2b–E2e', 'policy (4) × budget (10) per config, FULL_CRC', ns('E2b-e'), '{:,}'.format(n_e2r), 'orders 253/64/32/16; 5 M / 2 M / 2 M / 2 M keys'],
    ['E3', 'fault mode (4) × scheme (4)', ns('E3'), rc('E3'), 'uniform, hammer, column at byte 128 / 3000'],
    ['E4', 'θ (8) × {CTRL_CRC, FULL_CRC}', ns('E4'), rc('E4'), 'PERIODIC verification'],
    ['E5', 'rows-per-bank (7) × scheme (4)', ns('E5'), rc('E5'), 'capacity 16,384 → 256 pages; t<sub>ssd</sub> charged on every miss'],
    ['E6a', 'order (4) × {NONE, CTRL_CRC, FULL_CRC}', ns('E6a'), rc('E6A'), '200 K keys; SSD blocks per order; rows-per-bank 8,192'],
    ['E6b', 'keys (4) × {NONE, CTRL_CRC, FULL_CRC}', ns('E6b'), rc('E6B'), 'order 253; geometry scaled with N'],
    ['E7', 'stride (5) × scheme (4)', ns('E7'), rc('E7'), 'keys = index × 2<sup>k</sup>'],
    ['E7ext: grid (E22)', 'k ∈ {30, 29} × {NONE, SANITY, CTRL_CRC}', ns('E22'), '{:,}'.format(n_e22), 'stride 2<sup>32</sup>; geometry 4× / 8×'],
    ['E7ext: grid k = 31, adjacent, baselines (E13)', '5 arms × {SANITY, CTRL_CRC}', _xseeds, '{:,}'.format(n_e13), 'none, grid k = 31, right, both (stride 2<sup>32</sup>); none (random64)'],
    ['E7ext: shift, hash (E21)', 'shift (SANITY); hash α (3) × {SANITY, NONE}; hash on stride keys (SANITY)', _xseeds, '{:,}'.format(n_e21), f'K ≫ 32; random64 hash-mapped; the stride-key hash arm ({n_e21 - n_e21_rep} runs) is not reported'],
]
assert n_e1_7 == sum(runs[k] for k in ('E1', 'E2', 'E3', 'E4', 'E5', 'E6A', 'E6B', 'E7')) + n_e2r
t_app = tblock('Run counts and configurations, all on the Ramulator2 backend (DDR4-2400, DDR4_8Gb_x8, ECC plugin off) with the header-covering CTRL_CRC. Common settings: order 253, 30,000 ops (90 % search, 5 % of searches miss, 10 % ascending insert), dt = 10 ms per op, λ = 3×10<sup>−3</sup>, EVERY_READ, budget ∞, SSD blocks 512 / rows-per-bank 2,048 (tree ≈ 35 % of SSD pages, fully resident), unless the row says otherwise. Header-only schemes are excluded from all counts.',
               ['experiment', 'sweep', 'seeds', 'runs', 'deviations'],
               app_rows + [['<b>Total</b>', '', '', '<b>%s</b>' % '{:,}'.format(primary_runs), f'E1–E7 {n_e1_7:,} + E13/E22 {n_e13 + n_e22} + E21 {n_e21}']], 2, (4,))
A('<section id="sA"><h2><span class="sn">A</span>Appendix: run counts and configurations</h2>' + t_app + '</section>')

notes = '<section id="notes" class="notes"><h2>Notes</h2><ol>' + ''.join(
    '<li id="n%d">%s <a href="#r%d" class="back" aria-label="back to text">↩</a></li>' % (i + 1, t, i + 1) for i, t in enumerate(NOTES)) + '</ol>' \
    '<p class="src">Numbers are taken from <code>results/paper_r2/paper_data.json</code> (Ramulator2 backend; cost and time tables as in <code>results/paper_r2/paper_tables.md</code>). ' \
    'Medians over seeds, final-integrity counts, the corruption attribution and the blind-zone edges are computed from the per-run CSVs in <code>results/r2/</code>, cross-checked against the JSON means. ' \
    'The E11 level split is from the earlier C++ DRAM model (<code>results/e11_dbscale.csv</code>). The C++-model version of this page is <code>results/paper/paper_cpp_model.html</code>.</p></section>'

body = ''.join(P) + notes

# ================================================================ CSS & JS
CSS = open(HERE + '/style.css').read()
JS = open(HERE + '/charts.js').read()
data_js = 'const CHARTS=' + json.dumps(CHARTS, ensure_ascii=False, separators=(',', ':')) + ';\n'

doc = ('<title>Per-Level Differential Protection</title>\n'
       '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
       '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap">\n'
       '<style>\n' + CSS + '\n</style>\n'
       '<div class="page"><article class="paper">' + body + '</article></div>\n'
       '<script>\n' + data_js + JS + '\n</script>\n')
open(OUT, 'w', encoding='utf8').write(doc)
if os.environ.get('SCRIPT_OUT'): open(os.environ['SCRIPT_OUT'], 'w').write(data_js + JS)
print('wrote', OUT, len(doc.encode('utf8')), 'bytes;', FNUM[0], 'figures;', TNUM[0], 'tables;', len(NOTES), 'notes;', len(CHARTS), 'charts')
