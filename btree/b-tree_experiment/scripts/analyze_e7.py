#!/usr/bin/env python3
"""analyze_e7.py — E7′（key 稀疏度軸）專用彙總。

與 analyze_db.py 的分工：analyze_db.py 對任何 DB 規模 CSV 做通用的
mean/std 分組表與資料品質檢查（e7_dbscale.csv 也照跑，新欄位它會忽略）；
本檔只處理 E7′ 新增的東西：

  1. headline  — 每個 key_stride_log2 的 SANITY vs CTRL_CRC 對照表
  2. bitrecall — 逐「翻轉位元位置」的偵測率（機制證據）
  3. qc        — E7′ 專屬的資料品質檢查（直方圖總和、FULL_CRC 恆等式、
                 跨 stride 的 flip 流配對）

用法：
    python3 scripts/analyze_e7.py results/e7_dbscale.csv --headline
    python3 scripts/analyze_e7.py results/e7_dbscale.csv --bitrecall
    python3 scripts/analyze_e7.py results/e7_dbscale.csv --qc
"""
import argparse
import csv
import math
from collections import defaultdict

NB = 64
SCHEMES = ["NONE", "SANITY", "HDR_CRC", "CTRL_CRC", "FULL_CRC"]


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return float("nan")


def mean_std(v):
    v = [x for x in v if not math.isnan(x)]
    if not v:
        return float("nan"), float("nan")
    m = sum(v) / len(v)
    if len(v) < 2:
        return m, 0.0
    return m, math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def load(paths):
    rows = []
    for p in paths:
        with open(p, newline="") as f:
            rows += list(csv.DictReader(f))
    return rows


def cells(rows):
    """(stride, scheme) -> list of run rows"""
    g = defaultdict(list)
    for r in rows:
        g[(int(fnum(r["key_stride_log2"])), r["scheme"])].append(r)
    return g


def hist(r, prefix):
    return [fnum(r["%s_%02d" % (prefix, b)]) for b in range(NB)]


def strides(rows):
    return sorted({int(fnum(r["key_stride_log2"])) for r in rows})


# ── 1. headline ──────────────────────────────────────────────────────────────
def headline(rows):
    g = cells(rows)
    print("stride  gap        scheme    tp        recall     SDCrate    wu     "
          "final_err   recov     %ofFULL   lat_us   flips")
    for k in strides(rows):
        full_tp = mean_std([fnum(r["tp"]) for r in g[(k, "FULL_CRC")]])[0]
        for s in SCHEMES:
            grp = g.get((k, s), [])
            if not grp:
                continue
            tp = mean_std([fnum(r["tp"]) for r in grp])
            rec = mean_std([fnum(r["recall"]) for r in grp])
            sdc = mean_std([fnum(r["n_wrong_undetected"]) / fnum(r["n_searches"])
                            for r in grp])
            wu = mean_std([fnum(r["n_wrong_undetected"]) for r in grp])
            fe = mean_std([fnum(r["n_final_integrity_errors"]) for r in grp])
            rv = mean_std([fnum(r["n_recoveries"]) for r in grp])
            lat = mean_std([fnum(r["mean_op_latency_s"]) * 1e6 for r in grp])
            fl = mean_std([fnum(r["n_flip_events"]) for r in grp])
            print("%-7d 2^%-8d %-9s %-9.1f %-10.5g %-10.4g %-6.1f %-11.1f "
                  "%-9.1f %-9.4g %-8.3f %.0f"
                  % (k, k, s, tp[0], rec[0], sdc[0], wu[0], fe[0], rv[0],
                     (rv[0] / full_tp if full_tp else float("nan")), lat[0], fl[0]))
        print()


# ── 2. bit-position recall ───────────────────────────────────────────────────
def bitrecall(rows, group=8):
    """Per-bit detection of single-bit flips inside keys[].

    Denominator = CTRL_CRC's kb_tp[b] (== its kb_seen[b]: keys[] lies wholly
    inside CTRL_CRC's coverage, so every such read is detected and repaired,
    i.e. each corruption event is counted exactly once).  This is the direct
    "did the free structural check see what the real checksum saw?" ratio.
    FULL_CRC's exposure count is printed for context; it is slightly larger
    because FULL_CRC also repairs payload corruption, so fewer of its reads
    carry a second, older differing byte (which disqualifies the read from
    the single-bit histogram)."""
    g = cells(rows)
    for k in strides(rows):
        def acc(scheme, prefix):
            h = [0.0] * NB
            for r in g.get((k, scheme), []):
                h = [a + b for a, b in zip(h, hist(r, prefix))]
            return [sum(h[i:i + group]) for i in range(0, NB, group)]

        ctrl = acc("CTRL_CRC", "kb_tp")
        full = acc("FULL_CRC", "kb_seen")
        print("=== key_stride_log2 = %d (gap 2^%d) ===" % (k, k))
        print("bits    " + "".join("%-9s" % ("%d-%d" % (i, i + group - 1))
                                   for i in range(0, NB, group)))
        print("CTRLev  " + "".join("%-9.0f" % e for e in ctrl))
        print("FULLev  " + "".join("%-9.0f" % e for e in full))
        for s in SCHEMES:
            if s in ("NONE", "HDR_CRC") or (k, s) not in g:
                continue
            det = acc(s, "kb_tp")
            print("%-8s" % s + "".join(
                "%-9.3f" % (d / e if e else float("nan"))
                for d, e in zip(det, ctrl)))
        print()


def bitrecall_fine(rows, scheme="SANITY"):
    """Full 64-bucket resolution for one scheme (event-weighted)."""
    g = cells(rows)
    ks = strides(rows)
    print("bit  " + "".join("  k=%-9d" % k for k in ks))
    tot = {}
    for k in ks:
        full = [0.0] * NB
        for r in g[(k, "CTRL_CRC")]:
            full = [a + b for a, b in zip(full, hist(r, "kb_tp"))]
        tp = [0.0] * NB
        for r in g[(k, scheme)]:
            tp = [a + b for a, b in zip(tp, hist(r, "kb_tp"))]
        tot[k] = (full, tp)
    for b in range(NB):
        line = "%-4d " % b
        for k in ks:
            full, tp = tot[k]
            line += "  %-11s" % ("%.3f(%d)" % (tp[b] / full[b], full[b])
                                 if full[b] else "-")
        print(line)


# ── 3. QC ────────────────────────────────────────────────────────────────────
def qc(rows):
    ok, warn = [], []

    bad = [r["run_id"] for r in rows
           if abs(sum(hist(r, "kb_seen")) - fnum(r["n_keyflip_single"])) > .5
           or abs(sum(hist(r, "kb_tp")) - fnum(r["n_keyflip_single_tp"])) > .5]
    (ok if not bad else warn).append(
        "keybit histogram sums == n_keyflip_single/_tp in all %d rows" % len(rows)
        if not bad else "histogram sum mismatch: %s" % bad[:5])

    for sch in ("FULL_CRC", "CTRL_CRC"):
        bad = [r["run_id"] for r in rows if r["scheme"] == sch
               and hist(r, "kb_seen") != hist(r, "kb_tp")]
        (ok if not bad else warn).append(
            "%s: kb_seen == kb_tp bucket-for-bucket "
            "(per-bit recall 1.0 on keys[], as the coverage implies)" % sch
            if not bad else "%s kb_seen != kb_tp: %s" % (sch, bad[:5]))

    bad = [r["run_id"] for r in rows
           if fnum(r["n_keyflip_single_tp"]) > fnum(r["tp"])]
    (ok if not bad else warn).append(
        "n_keyflip_single_tp <= tp in every row (subset of true positives)"
        if not bad else "keyflip_tp exceeds tp: %s" % bad[:5])

    # flip stream must pair across BOTH scheme and stride (same seed)
    g = defaultdict(set)
    for r in rows:
        g[r["seed"]].add(int(fnum(r["n_flip_events"])))
    unpaired = {k: sorted(v) for k, v in g.items() if len(v) > 1}
    (ok if not unpaired else warn).append(
        "n_flip_events identical across all schemes AND strides for each seed "
        "(%d seeds) -> strictly paired comparison" % len(g)
        if not unpaired else
        "flip stream diverges within seed: %s" % unpaired)

    # tree shape must be stride-invariant
    shapes = defaultdict(set)
    for r in rows:
        shapes[r["seed"]].add((r["n_pages_allocated"], r["tree_height"]))
    bad = {k: v for k, v in shapes.items() if len(v) > 1}
    (ok if not bad else warn).append(
        "tree shape (pages, height) identical across strides for each seed"
        if not bad else "tree shape varies with stride: %s" % bad)

    fp = [r["run_id"] for r in rows if fnum(r["fp"]) > 0]
    (ok if not fp else warn).append(
        "fp = 0 in all %d rows" % len(rows) if not fp else "fp > 0: %s" % fp[:5])

    ev = [r["run_id"] for r in rows if fnum(r["ram_lru_evictions"]) > 0
          or fnum(r["ram_misses"]) > 0]
    (ok if not ev else warn).append(
        "ram_misses = lru_evictions = 0 in every row (whole tree resident)"
        if not ev else "%d rows show RAM eviction/miss" % len(ev))

    print("== PASSED ==")
    for s in ok:
        print("  [ok]  " + s)
    print("== WARNINGS ==")
    if not warn:
        print("  (none)")
    for s in warn:
        print("  [!!]  " + s)
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--headline", action="store_true")
    ap.add_argument("--bitrecall", action="store_true")
    ap.add_argument("--fine", default=None,
                    help="full 64-bucket table for this scheme")
    ap.add_argument("--group", type=int, default=8)
    ap.add_argument("--qc", action="store_true")
    a = ap.parse_args()
    rows = load(a.csv)
    if a.qc:
        qc(rows)
    if a.headline:
        headline(rows)
    if a.bitrecall:
        bitrecall(rows, a.group)
    if a.fine:
        bitrecall_fine(rows, a.fine)


if __name__ == "__main__":
    main()
