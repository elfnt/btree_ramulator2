#!/usr/bin/env python3
"""analyze_db.py — DB 規模（E1'–E4'）結果的彙總與資料品質檢查。

與既有的 analyze.py 的分工：
  analyze.py    通用、對任何 CSV 做 mean/std 分組表 + f1 折線圖（沿用不動）
  analyze_db.py 針對 DB 規模這批，額外做三件 analyze.py 不做的事：
     1. 衍生指標：SDC rate、每 flip 傷害、control-vs-payload 歸因比例
     2. 資料品質檢查（fp=0、歸因總和 == tp+fn、flip 流跨 scheme 配對…）
     3. 直接吐出 SUMMARY_dbscale.md 用得上的表格形狀

用法：
    python3 scripts/analyze_db.py results/e1_dbscale.csv --group scheme lambda_page
    python3 scripts/analyze_db.py results/e1_dbscale.csv --qc
"""
import argparse
import csv
import math
import sys
from collections import OrderedDict, defaultdict

ATTR = ["n_corrupt_reads_ctrl_only", "n_corrupt_reads_payload_only",
        "n_corrupt_reads_mixed", "n_corrupt_reads_ssd_header"]
# payload_only 的子集（不進四類總和）：相異位元組全在未使用補零 slack。
SLACK = "n_corrupt_reads_slack_only"


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return float("nan")


def mean_std(vals):
    v = [x for x in vals if not math.isnan(x)]
    if not v:
        return float("nan"), float("nan")
    m = sum(v) / len(v)
    if len(v) < 2:
        return m, 0.0
    return m, math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def derive(r):
    """Add derived per-run metrics to a row dict (as floats under new keys)."""
    ns = fnum(r.get("n_searches"))
    nf = fnum(r.get("n_flip_events"))
    wu = fnum(r.get("n_wrong_undetected"))
    tp, fn = fnum(r.get("tp")), fnum(r.get("fn"))
    d = {}
    d["sdc_rate"] = wu / ns if ns else float("nan")
    d["dmg_per_flip"] = wu / nf if nf else float("nan")
    d["lat_us"] = fnum(r.get("mean_op_latency_s")) * 1e6
    corrupt = tp + fn                      # truth_corrupt 的讀取總數
    d["corrupt_reads"] = corrupt
    attr = {k: fnum(r.get(k)) for k in ATTR}
    d.update(attr)
    d["attr_sum"] = sum(attr.values())
    slack = fnum(r.get(SLACK))
    d[SLACK] = slack
    # 真正打到 values[] 的毀損 = payload_only 扣掉純 slack 的部分
    d["payload_live"] = attr[ATTR[1]] - slack if not math.isnan(slack) else float("nan")
    if corrupt > 0:
        # CTRL_CRC 原理上「看得見」的比例 = (ctrl_only + mixed) / corrupt
        d["frac_ctrl_visible"] = (attr[ATTR[0]] + attr[ATTR[2]]) / corrupt
        d["frac_payload_only"] = attr[ATTR[1]] / corrupt
        d["frac_ssd_header"] = attr[ATTR[3]] / corrupt
        d["frac_slack_only"] = slack / corrupt
        d["frac_payload_live"] = d["payload_live"] / corrupt
    else:
        d["frac_ctrl_visible"] = d["frac_payload_only"] = d["frac_ssd_header"] = float("nan")
        d["frac_slack_only"] = d["frac_payload_live"] = float("nan")
    return d


DERIVED = ["sdc_rate", "dmg_per_flip", "lat_us", "corrupt_reads",
           "frac_ctrl_visible", "frac_payload_only", "frac_ssd_header",
           "frac_slack_only", "frac_payload_live", "payload_live"]

RAW = ["recall", "precision", "f1", "n_flip_events", "n_wrong_undetected",
       "n_wrong_total", "n_final_integrity_errors", "n_would_crash",
       "n_poisoned_writes", "n_recoveries", "tp", "fp", "fn",
       "shadow_bytes_used_max", "n_shadow_rejected", "n_pages_allocated",
       "tree_height", "ram_misses", "ram_lru_evictions", "n_guarded_reads"] + ATTR + [SLACK]


def load(paths):
    rows = []
    for p in paths:
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                r["_src"] = p
                r["_d"] = derive(r)
                rows.append(r)
    return rows


def qc(rows):
    """Data-quality checks. Returns (passed[], warnings[])."""
    ok, warn = [], []

    fp_bad = [r["run_id"] for r in rows if fnum(r.get("fp")) > 0]
    (ok if not fp_bad else warn).append(
        "fp = 0 in all %d rows (precision = 1.0 wherever defined)" % len(rows)
        if not fp_bad else
        "fp > 0 in %d rows: %s" % (len(fp_bad), fp_bad[:5]))

    bad_attr = [(r["run_id"], r["_d"]["attr_sum"], r["_d"]["corrupt_reads"])
                for r in rows
                if abs(r["_d"]["attr_sum"] - r["_d"]["corrupt_reads"]) > 0.5]
    (ok if not bad_attr else warn).append(
        "attribution invariant holds in all %d rows "
        "(ctrl_only+payload_only+mixed+ssd_header == tp+fn)" % len(rows)
        if not bad_attr else
        "attribution invariant BROKEN in %d rows: %s" % (len(bad_attr), bad_attr[:5]))

    slack_bad = [r["run_id"] for r in rows
                 if not math.isnan(r["_d"][SLACK])
                 and r["_d"][SLACK] > r["_d"][ATTR[1]] + 0.5]
    (ok if not slack_bad else warn).append(
        "slack_only <= payload_only in every row (subset relation holds)"
        if not slack_bad else
        "slack_only EXCEEDS payload_only in %d rows: %s" % (len(slack_bad), slack_bad[:5]))

    none_bad = [r["run_id"] for r in rows if r.get("scheme") == "NONE"
                and fnum(r.get("n_wrong_undetected")) != fnum(r.get("n_wrong_total"))]
    (ok if not none_bad else warn).append(
        "NONE: n_wrong_undetected == n_wrong_total in every row (no alarms -> all SDC)"
        if not none_bad else
        "NONE rows where undetected != total: %s" % none_bad[:5])

    ev = [r["run_id"] for r in rows
          if fnum(r.get("ram_lru_evictions")) > 0 or fnum(r.get("ram_misses")) > 0]
    (ok if not ev else warn).append(
        "ram_misses = lru_evictions = 0 in every row "
        "(whole tree resident -> no natural scrubbing confound)"
        if not ev else
        "%d rows show RAM eviction/miss (scrubbing confound): %s" % (len(ev), ev[:5]))

    # flip-stream pairing: same (everything but scheme) -> same n_flip_events
    keys = ["lambda_page", "seed", "hammer_rate_per_s", "colfault_time_s",
            "colfault_byte", "budget_bytes", "policy", "verify_mode", "theta_s",
            "prefill_keys", "order"]
    g = defaultdict(set)
    for r in rows:
        g[tuple(r.get(k, "") for k in keys)].add(int(fnum(r.get("n_flip_events"))))
    unpaired = {k: v for k, v in g.items() if len(v) > 1}
    (ok if not unpaired else warn).append(
        "flip stream is identical across schemes for every (lambda, seed, mode) cell "
        "-> cross-scheme comparisons are strictly paired (%d cells)" % len(g)
        if not unpaired else
        "flip stream DIVERGES across schemes in %d/%d cells, e.g. %s"
        % (len(unpaired), len(g),
           [(k[:3], sorted(v)) for k in list(unpaired)[:3] for v in [unpaired[k]]]))

    full = [r for r in rows if r.get("scheme") == "FULL_CRC"
            and r.get("budget_bytes") == "inf"
            and r.get("verify_mode") == "EVERY_READ"]
    bad_full = [r["run_id"] for r in full
                if fnum(r.get("recall")) != 1.0 or fnum(r.get("n_wrong_undetected")) != 0]
    if full:
        (ok if not bad_full else warn).append(
            "FULL_CRC (budget=inf, EVERY_READ): recall = 1.0 and SDC = 0 in all %d rows"
            % len(full) if not bad_full else
            "FULL_CRC imperfect in %d rows: %s" % (len(bad_full), bad_full[:5]))

    heights = {int(fnum(r.get("tree_height"))) for r in rows}
    pages = {int(fnum(r.get("n_pages_allocated"))) for r in rows}
    ok.append("tree height %s, pages allocated %s across all rows"
              % (sorted(heights), "%d-%d" % (min(pages), max(pages))))
    return ok, warn


def table(rows, group_cols, metrics):
    groups = OrderedDict()
    for r in rows:
        groups.setdefault(tuple(r.get(c, "") for c in group_cols), []).append(r)

    def gsort(k):
        out = []
        for v in k:
            f = fnum(v)
            out.append((0, f, "") if not math.isnan(f) else (1, 0.0, v))
        return tuple(out)

    hdr = list(group_cols) + ["n"] + metrics
    lines = [hdr]
    for k in sorted(groups, key=gsort):
        grp = groups[k]
        row = list(k) + [str(len(grp))]
        for m in metrics:
            vals = [(r["_d"][m] if m in r["_d"] else fnum(r.get(m))) for r in grp]
            mu, sd = mean_std(vals)
            row.append("-" if math.isnan(mu) else
                       ("%.6g" % mu if sd == 0 else "%.6g±%.3g" % (mu, sd)))
        lines.append(row)
    w = [max(len(r[i]) for r in lines) for i in range(len(hdr))]
    out = ["  ".join(c.ljust(w[i]) for i, c in enumerate(lines[0])),
           "  ".join("-" * x for x in w)]
    out += ["  ".join(c.ljust(w[i]) for i, c in enumerate(r)) for r in lines[1:]]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--group", nargs="*", default=["scheme", "lambda_page"])
    ap.add_argument("--metrics", nargs="*", default=None)
    ap.add_argument("--qc", action="store_true")
    a = ap.parse_args()

    rows = load(a.csv)
    if not rows:
        print("no rows", file=sys.stderr)
        return 1

    if a.qc:
        ok, warn = qc(rows)
        print("== PASSED ==")
        for s in ok:
            print("  [ok]  " + s)
        print("== WARNINGS ==")
        if not warn:
            print("  (none)")
        for s in warn:
            print("  [!!]  " + s)
        print()

    metrics = a.metrics or ["recall", "f1", "sdc_rate", "dmg_per_flip",
                            "n_wrong_undetected", "n_final_integrity_errors",
                            "n_would_crash", "n_poisoned_writes", "n_recoveries",
                            "lat_us", "n_flip_events",
                            "frac_ctrl_visible", "frac_payload_only", "frac_ssd_header"]
    print(table(rows, a.group, metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
