(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var SUP = { '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' };
  function sup(n) { return String(n).split('').map(function (c) { return SUP[c] || c; }).join(''); }
  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function sci(v) {
    if (v === 0) return '0';
    var e = Math.floor(Math.log10(Math.abs(v)));
    var m = v / Math.pow(10, e);
    if (Math.abs(m - 10) < 0.005) { m = 1; e += 1; }
    return m.toFixed(2) + '×10^' + String(e).replace('-', '−');
  }
  function fmt(v, f) {
    if (v === null || v === undefined) return '—';
    if (f === 'sci') return sci(v);
    if (f === 'f1') return v.toFixed(1);
    if (f === 'f2') return v.toFixed(2);
    if (f === 'f3') return v.toFixed(3);
    if (f === 'x2') return v.toFixed(2) + '×';
    return String(v);
  }
  function powLabel(v) {
    var e = Math.round(Math.log10(v));
    if (e === 0) return '1';
    if (e === 1) return '10';
    return '10^' + String(e).replace('-', '−');
  }
  function shortSci(v) {
    var e = Math.floor(Math.log10(v) + 1e-9), m = Math.round(v / Math.pow(10, e) * 100) / 100;
    return (m === 1 ? '' : m + '×') + '10^' + String(e).replace('-', '−');
  }
  // text with optional trailing ^exponent rendered as a raised tspan
  function setLabel(t, str) {
    str = String(str);
    var i = str.indexOf('^');
    if (i < 0) { t.textContent = str; return; }
    var m = /^\^([−\-]?[0-9]+)(.*)$/.exec(str.slice(i));
    if (!m) { t.textContent = str; return; }
    t.appendChild(document.createTextNode(str.slice(0, i)));
    var ts = el('tspan', { dy: '-0.45em', 'font-size': '0.78em' }, t); ts.textContent = m[1];
    if (m[2]) { var t2 = el('tspan', { dy: '0.45em' }, t); t2.textContent = m[2]; }
  }
  function supHtml(s) { return esc(s).replace(/\^([−\-]?[0-9]+)/g, '<sup>$1</sup>'); }
  function niceStep(span, n) {
    var raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw))), r = raw / p;
    return (r < 1.5 ? 1 : r < 3 ? 2 : r < 7 ? 5 : 10) * p;
  }
  function linTickFmt(v, step, scale) {
    if (Math.abs(v) < 1e-12) return '0';
    if (scale) { v = v * scale; step = step * scale; }
    var d = step >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(step)));
    return v.toFixed(d);
  }

  // marker shapes by slot: 1 circle, 2 square, 3 triangle, 4 diamond
  function marker(g, slot, x, y, r, cls, color, title) {
    var m;
    if (slot === 1) m = el('circle', { cx: x, cy: y, r: r }, g);
    else if (slot === 2) m = el('rect', { x: x - r * 0.9, y: y - r * 0.9, width: r * 1.8, height: r * 1.8, rx: 1 }, g);
    else if (slot === 3) m = el('path', { d: 'M' + x + ',' + (y - r * 1.15) + 'L' + (x + r * 1.05) + ',' + (y + r * 0.75) + 'L' + (x - r * 1.05) + ',' + (y + r * 0.75) + 'Z' }, g);
    else m = el('path', { d: 'M' + x + ',' + (y - r * 1.2) + 'L' + (x + r * 1.2) + ',' + y + 'L' + x + ',' + (y + r * 1.2) + 'L' + (x - r * 1.2) + ',' + y + 'Z' }, g);
    m.setAttribute('class', cls);
    m.style.fill = color;
    if (cls.indexOf('c-hollow') >= 0) m.style.stroke = color;
    return m;
  }
  function swatch(s) {
    var w = 26, h = 14, svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', w); svg.setAttribute('height', h); svg.setAttribute('aria-hidden', 'true');
    if (s.ref) {
      el('line', { x1: 1, y1: 7, x2: 25, y2: 7, 'class': 'c-ref' }, svg);
    } else {
      var col = 'var(--s' + s.slot + ')';
      if (s.line !== false) {
        var l = el('line', { x1: 1, y1: 7, x2: 25, y2: 7, 'class': 'c-ln' + (s.dash ? ' c-dash' : '') }, svg);
        l.style.stroke = col;
      }
      marker(svg, s.slot, 13, 7, 4, 'c-pt' + (s.hollow ? ' c-hollow' : ''), col);
    }
    return svg;
  }

  function draw(host, spec) {
    host.innerHTML = '';
    var W = Math.max(280, Math.floor(host.clientWidth));
    var narrow = W < 520;
    var H = spec.h || (narrow ? 230 : 260);
    var series = spec.series;
    var real = series.filter(function (s) { return !s.ref; });

    // legend
    if (series.length >= 2) {
      var ul = document.createElement('ul'); ul.className = 'legend';
      series.forEach(function (s) {
        var li = document.createElement('li');
        li.appendChild(swatch(s));
        var t = document.createElement('span'); t.textContent = s.name; li.appendChild(t);
        ul.appendChild(li);
      });
      host.appendChild(ul);
    }

    var endLabels = spec.endLabels !== false && !narrow && real.length >= 2;
    var mL = narrow ? 50 : 60, mR = endLabels ? 86 : 14, mT = 22, mB = 40;
    var pw = W - mL - mR, ph = H - mT - mB;

    // ---- domains
    var allX = [], allY = [];
    series.forEach(function (s) { s.pts.forEach(function (p) { allX.push(p[0]); if (p[1] !== null && p[1] !== undefined) allY.push(p[1]); }); });
    var xs = spec.x, ys = spec.y, X, xTicks = [], xTickLbl = [];
    if (xs.type === 'cat') {
      var n = xs.cats.length;
      X = function (i) { return mL + (i + 0.5) * pw / n; };
      for (var i = 0; i < n; i++) { xTicks.push(i); xTickLbl.push(xs.cats[i]); }
    } else if (xs.type === 'log') {
      var x0 = xs.min || Math.min.apply(null, allX), x1 = xs.max || Math.max.apply(null, allX);
      var lx0 = Math.log10(x0), lx1 = Math.log10(x1), padx = (lx1 - lx0) * 0.04;
      lx0 -= padx; lx1 += padx;
      X = function (v) { return mL + (Math.log10(v) - lx0) / (lx1 - lx0) * pw; };
      if (xs.ticks) { xTicks = xs.ticks; xTickLbl = xs.tickLabels || xs.ticks.map(String); }
      else {
        for (var e = Math.ceil(Math.log10(x0) - 1e-9); e <= Math.floor(Math.log10(x1) + 1e-9); e++) { xTicks.push(Math.pow(10, e)); xTickLbl.push(powLabel(Math.pow(10, e))); }
      }
    } else {
      var a0 = xs.min !== undefined ? xs.min : Math.min.apply(null, allX), a1 = xs.max !== undefined ? xs.max : Math.max.apply(null, allX);
      var pad = (a1 - a0) * 0.04;
      X = function (v) { return mL + (v - (a0 - pad)) / ((a1 + pad) - (a0 - pad)) * pw; };
      xTicks = xs.ticks; xTickLbl = xs.tickLabels;
    }
    var Y, yTicks = [], yTickLbl = [];
    if (ys.type === 'log') {
      var pos = allY.filter(function (v) { return v > 0; });
      var y0 = ys.min || Math.min.apply(null, pos), y1 = ys.max || Math.max.apply(null, pos);
      var ly0, ly1;
      if (ys.ticks) { ly0 = Math.log10(y0); ly1 = Math.log10(y1); yTicks = ys.ticks; yTickLbl = ys.tickLabels; }
      else {
        ly0 = Math.floor(Math.log10(y0) + 1e-9); ly1 = Math.ceil(Math.log10(y1) - 1e-9);
        if (ly1 - ly0 < 1) ly1 = ly0 + 1;
        var stepE = (ly1 - ly0) > 6 ? 2 : 1;
        for (var k = ly0; k <= ly1; k += stepE) { yTicks.push(Math.pow(10, k)); yTickLbl.push(powLabel(Math.pow(10, k))); }
      }
      Y = function (v) { return mT + ph - (Math.log10(v) - ly0) / (ly1 - ly0) * ph; };
    } else {
      var b0 = ys.min !== undefined ? ys.min : Math.min.apply(null, allY), b1 = ys.max !== undefined ? ys.max : Math.max.apply(null, allY) * 1.06;
      var st = niceStep(b1 - b0, narrow ? 4 : 5);
      if (ys.max === undefined) b1 = Math.ceil(b1 / st - 1e-9) * st;
      var yTop = ys.max !== undefined ? b1 * 1.02 + (b1 - b0) * 0.02 : b1;
      Y = function (v) { return mT + ph - (v - b0) / (yTop - b0) * ph; };
      for (var t = Math.ceil(b0 / st - 1e-9) * st; t <= b1 + st * 1e-6; t += st) { yTicks.push(t); yTickLbl.push(linTickFmt(t, st, ys.scale)); }
    }

    var wrap = document.createElement('div'); wrap.style.position = 'relative';
    host.appendChild(wrap);
    var svg = el('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': spec.aria, tabindex: '0' });
    wrap.appendChild(svg);

    // grid + y ticks
    var gg = el('g', {}, svg);
    yTicks.forEach(function (v, i) {
      var y = Math.round(Y(v)) + 0.5;
      el('line', { x1: mL, x2: mL + pw, y1: y, y2: y, 'class': 'c-grid' }, gg);
      var tx = el('text', { x: mL - 6, y: y + 4, 'text-anchor': 'end', 'class': 'c-ax' }, gg); setLabel(tx, yTickLbl[i]);
    });
    el('line', { x1: mL, x2: mL + pw, y1: mT + ph + 0.5, y2: mT + ph + 0.5, 'class': 'c-base' }, gg);
    // x ticks (thin out when crowded)
    var lastR = -1e9, prio = xs.mark;
    xTicks.forEach(function (v, i) {
      var x = X(v);
      el('line', { x1: x, x2: x, y1: mT + ph, y2: mT + ph + 4, 'class': 'c-base' }, gg);
      var lbl = String(xTickLbl[i]), w = lbl.replace('^', '').length * 6.7;
      // keep the next tick label free if it is the marked one
      var nextIsMark = prio !== undefined && i + 1 < xTicks.length && xTicks[i + 1] === prio;
      var nxL = nextIsMark ? X(xTicks[i + 1]) - String(xTickLbl[i + 1]).length * 3.4 : 1e9;
      if (v !== prio && (x - w / 2 < lastR + 6 || x + w / 2 > nxL - 6)) return;
      var tx = el('text', { x: x, y: mT + ph + 16, 'text-anchor': 'middle', 'class': 'c-ax' }, gg); setLabel(tx, lbl);
      lastR = x + w / 2;
    });
    var xl = el('text', { x: mL + pw / 2, y: H - 6, 'text-anchor': 'middle', 'class': 'c-axl' }, gg); xl.textContent = xs.label;
    var yl = el('text', { x: mL - (narrow ? 44 : 54), y: 11, 'class': 'c-axl' }, gg); setLabel(yl, '↑ ' + ys.label);
    if (xs.mark !== undefined) {
      var mx = X(xs.mark);
      el('line', { x1: mx, x2: mx, y1: mT + 12, y2: mT + ph, 'class': 'c-mark' }, gg);
      if (xs.markLabel) { var ml = el('text', { x: mx + 4, y: mT + 10, 'class': 'c-markl' }, gg); ml.textContent = xs.markLabel; }
    }
    if (ys.refLine) {
      var ry = Y(ys.refLine.v);
      el('line', { x1: mL, x2: mL + pw, y1: ry, y2: ry, 'class': 'c-hline' }, gg);
      var rt = el('text', { x: mL + 4, y: ry - 4, 'class': 'c-ax' }, gg); rt.textContent = ys.refLine.label;
    }

    // series
    var sg = el('g', {}, svg), ends = [];
    var R = 4.5;
    series.forEach(function (s) {
      var pts = s.pts.filter(function (p) { return p[1] !== null && (ys.type !== 'log' || p[1] > 0); });
      if (s.ref) {
        el('path', { d: pts.map(function (p, i) { return (i ? 'L' : 'M') + X(p[0]) + ',' + Y(p[1]); }).join(''), 'class': 'c-ref' }, sg);
        return;
      }
      var col = 'var(--s' + s.slot + ')';
      if (s.line !== false && pts.length > 1) {
        var ln = el('path', { d: pts.map(function (p, i) { return (i ? 'L' : 'M') + X(p[0]) + ',' + Y(p[1]); }).join(''), 'class': 'c-ln' + (s.dash ? ' c-dash' : '') }, sg);
        ln.style.stroke = col;
      }
      pts.forEach(function (p) { marker(sg, s.slot, X(p[0]), Y(p[1]), R, 'c-pt' + (s.hollow ? ' c-hollow' : ''), col); });
      if (endLabels && pts.length) { var lp = pts[pts.length - 1]; ends.push({ y: Y(lp[1]), yTrue: Y(lp[1]), x: X(lp[0]), name: s.name }); }
    });
    // direct end labels with simple collision avoidance
    if (ends.length) {
      ends.sort(function (a, b) { return a.y - b.y; });
      for (var j = 1; j < ends.length; j++) if (ends[j].y - ends[j - 1].y < 13) ends[j].y = ends[j - 1].y + 13;
      var over = ends[ends.length - 1].y - (mT + ph);
      if (over > 0) ends.forEach(function (e) { e.y -= over; });
      var ok = ends.every(function (e) { return Math.abs(e.y - e.yTrue) <= 14; });
      if (ok) ends.forEach(function (e) {
        var t = el('text', { x: mL + pw + 8, y: e.y + 4, 'class': 'c-end' }, sg); t.textContent = e.name;
      });
    }

    // hover layer
    var hx = [];
    series.forEach(function (s) { s.pts.forEach(function (p) { if (hx.indexOf(p[0]) < 0) hx.push(p[0]); }); });
    hx.sort(function (a, b) { return X(a) - X(b); });
    var cross = el('line', { x1: 0, x2: 0, y1: mT, y2: mT + ph, 'class': 'c-cross', visibility: 'hidden' }, svg);
    var hit = el('rect', { x: mL, y: mT, width: pw, height: ph, fill: 'transparent' }, svg);
    var tip = document.createElement('div'); tip.className = 'tip'; tip.style.display = 'none'; tip.setAttribute('role', 'status');
    wrap.appendChild(tip);
    var cur = -1;
    function xlabel(v) {
      if (xs.type === 'cat') return xs.cats[v];
      if (xs.fmt === 'sci') return shortSci(v);
      if (spec.xfmt === 'mult' || (xs.tickLabels && String(xs.tickLabels[0]).slice(-1) === '×')) return v.toFixed(2) + '×';
      if (xs.type === 'log' && !xs.ticks) return String(v);
      if (xs.tickLabels) { var ix = xs.ticks.indexOf(v); if (ix >= 0) return xs.tickLabels[ix]; }
      return String(v);
    }
    function show(i) {
      if (i < 0 || i >= hx.length) return;
      cur = i;
      var v = hx[i], px = X(v);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.setAttribute('visibility', 'visible');
      var h = '<div class="th">' + esc(xs.label.split(' (')[0]) + ': ' + supHtml(xlabel(v)) + '</div>';
      series.forEach(function (s) {
        var p = null;
        for (var q = 0; q < s.pts.length; q++) if (s.pts[q][0] === v) p = s.pts[q];
        if (!p) return;
        var val = p[1] === 0 && ys.type === 'log' ? '0 (not drawn)' : fmt(p[1], ys.fmt);
        var sw = s.ref ? '<svg width="14" height="8" aria-hidden="true"><line x1="0" y1="4" x2="14" y2="4" class="c-ref"/></svg>'
          : '<svg width="10" height="10" aria-hidden="true"><rect width="10" height="10" rx="2" style="fill:var(--s' + s.slot + ')"/></svg>';
        h += '<div class="tr">' + sw + '<span>' + esc(s.name) + (p[2] ? ' <span class="mu">· ' + esc(p[2]) + '</span>' : '') + '</span><span class="tv">' + supHtml(val) + '</span></div>';
      });
      tip.innerHTML = h; tip.style.display = 'block';
      var tw = tip.offsetWidth, left = px + 14;
      if (left + tw > W) left = Math.max(0, px - tw - 14);
      tip.style.left = left + 'px'; tip.style.top = (mT + 4) + 'px';
    }
    function hide() { cross.setAttribute('visibility', 'hidden'); tip.style.display = 'none'; }
    function nearest(clientX) {
      var r = svg.getBoundingClientRect(), mx = clientX - r.left, best = 0, bd = 1e9;
      hx.forEach(function (v, i) { var d = Math.abs(X(v) - mx); if (d < bd) { bd = d; best = i; } });
      return best;
    }
    hit.addEventListener('mousemove', function (ev) { show(nearest(ev.clientX)); });
    hit.addEventListener('mouseleave', hide);
    hit.addEventListener('touchstart', function (ev) { if (ev.touches[0]) show(nearest(ev.touches[0].clientX)); }, { passive: true });
    svg.addEventListener('focus', function () { show(cur < 0 ? 0 : cur); });
    svg.addEventListener('blur', hide);
    svg.addEventListener('keydown', function (ev) {
      if (ev.key === 'ArrowRight') { show(Math.min(hx.length - 1, cur + 1)); ev.preventDefault(); }
      else if (ev.key === 'ArrowLeft') { show(Math.max(0, cur - 1)); ev.preventDefault(); }
      else if (ev.key === 'Escape') { hide(); }
    });
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  var hosts = document.querySelectorAll('[data-chart]');
  var widths = new Map();
  function render(h) {
    var w = Math.floor(h.clientWidth);
    if (widths.get(h) === w) return;
    widths.set(h, w);
    try { draw(h, CHARTS[+h.getAttribute('data-chart')]); } catch (e) { h.textContent = 'Chart failed to render; see the data table below.'; }
  }
  hosts.forEach(render);
  if ('ResizeObserver' in window) {
    var raf = 0, pending = new Set();
    var ro = new ResizeObserver(function (entries) {
      entries.forEach(function (en) { pending.add(en.target); });
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(function () { pending.forEach(render); pending.clear(); });
    });
    hosts.forEach(function (h) { ro.observe(h); });
  } else {
    window.addEventListener('resize', function () { hosts.forEach(render); });
  }
})();
