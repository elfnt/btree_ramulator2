#!/usr/bin/env python3
"""analyze_e2large.py — E2b′/E2c′/E2d′（大內部節點數的 budget × policy）彙總與品管。

與 analyze_db.py 的分工：analyze_db.py 是 scheme × λ 那批的通用彙總；
本檔專門處理「預算軸是 B_int 的倍數」這件事——它從 CSV 的
`n_internal_total` / `n_pages_allocated` 直接算出 B_int / B_full，
再把每個 budget 換算成 B_int 的倍數與 B_full 的百分比。

用法：
    python3 scripts/analyze_e2large.py results/e2b_dbscale.csv ... --qc
    python3 scripts/analyze_e2large.py results/e2b_dbscale.csv ... --table
"""
import argparse, csv, math, sys
from collections import defaultdict

ENTRY_BYTES = 12          # FULL_CRC / CTRL_CRC 的 shadow entry 大小
ATTR = ["n_corrupt_reads_ctrl_only", "n_corrupt_reads_payload_only",
        "n_corrupt_reads_mixed", "n_corrupt_reads_ssd_header"]
POLICIES = ["BY_LEVEL", "LRU", "BY_HOTNESS", "RANDOM"]


def fnum(s):
    try:    return float(s)
    except (TypeError, ValueError): return float("nan")


def mean_std(v):
    v = [x for x in v if not math.isnan(x)]
    if not v: return float("nan"), float("nan")
    m = sum(v) / len(v)
    if len(v) < 2: return m, 0.0
    return m, math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def load(paths):
    rows = []
    for p in paths:
        with open(p, newline="") as f:
            for r in csv.DictReader(f):
                r["_src"] = p
                r["_cfg"] = "order%s/%sM" % (r["order"],
                                             float(r["prefill_keys"]) / 1e6)
                rows.append(r)
    return rows


def budget_of(r):
    b = r["budget_bytes"]
    return float("inf") if b == "inf" else float(b)


def cfg_geometry(rows):
    """每個組態的 B_int / B_full（用該組態全部 run 的中位數，並回報離散度）。"""
    g = {}
    by = defaultdict(list)
    for r in rows: by[r["_cfg"]].append(r)
    for c, rs in by.items():
        ints  = sorted(int(r["n_internal_total"])  for r in rs)
        pages = sorted(int(r["n_pages_allocated"]) for r in rs)
        # 預算軸的設計基準 = seed 1 的幾何（run_e2large_db.sh 就是照這個開的刻度），
        # 之後對該組態的每個 cell 固定不變；其他 seed 的幾何只回報離散度。
        s1 = [r for r in rs if r["seed"] == "1"] or rs
        s1i = sorted(int(r["n_internal_total"])  for r in s1)
        s1p = sorted(int(r["n_pages_allocated"]) for r in s1)
        g[c] = dict(n_int=s1i[len(s1i)//2], n_int_min=ints[0], n_int_max=ints[-1],
                    n_pages=s1p[len(s1p)//2], n_pages_min=pages[0],
                    n_pages_max=pages[-1],
                    height=int(rs[0]["tree_height"]),
                    levels=[int(s1[0]["n_nodes_level_%d" % i]) for i in range(8)],
                    order=int(rs[0]["order"]), keys=int(rs[0]["prefill_keys"]))
        g[c]["B_int"]  = g[c]["n_int"]   * ENTRY_BYTES
        g[c]["B_full"] = g[c]["n_pages"] * ENTRY_BYTES
        g[c]["int_share"] = 100.0 * g[c]["n_int"] / g[c]["n_pages"]
    return g


def cfg_order(geo):
    """組態的輸出順序 = 內部節點數由小到大（= 本節的自變數）。"""
    return sorted(geo, key=lambda c: geo[c]["n_int"])


def qc(rows, geo):
    print("## 資料品質檢查\n")
    n = len(rows)
    print("rows = %d；組態 = %s" % (n, sorted(set(r['_cfg'] for r in rows))))

    fp_bad = [r["run_id"] for r in rows if int(r["fp"]) != 0]
    print("1. fp == 0 ：%s (%d/%d)" % ("PASS" if not fp_bad else "FAIL %s" % fp_bad[:5],
                                       n - len(fp_bad), n))

    attr_bad, slack_bad = [], []
    for r in rows:
        s = sum(int(r[k]) for k in ATTR)
        if s != int(r["tp"]) + int(r["fn"]): attr_bad.append(r["run_id"])
        if int(r["n_corrupt_reads_slack_only"]) > int(r["n_corrupt_reads_payload_only"]):
            slack_bad.append(r["run_id"])
    print("2. 歸因不變量 sum(4類) == tp+fn ：%s (%d/%d)"
          % ("PASS" if not attr_bad else "FAIL %s" % attr_bad[:5], n - len(attr_bad), n))
    print("   slack_only <= payload_only ：%s"
          % ("PASS" if not slack_bad else "FAIL %s" % slack_bad[:5]))

    lvl_bad, h_bad, int_bad = [], [], []
    for r in rows:
        lv = [int(r["n_nodes_level_%d" % i]) for i in range(8)]
        if sum(lv) != int(r["n_pages_allocated"]): lvl_bad.append(r["run_id"])
        if sum(lv) - lv[0] != int(r["n_internal_total"]): int_bad.append(r["run_id"])
        top = max(i for i, v in enumerate(lv) if v) if any(lv) else 0
        if top + 1 != int(r["tree_height"]): h_bad.append(r["run_id"])
    print("3. Σ n_nodes_level_* == n_pages_allocated ：%s (%d/%d)"
          % ("PASS" if not lvl_bad else "FAIL %s" % lvl_bad[:5], n - len(lvl_bad), n))
    print("   n_internal_total == Σ_{l>=1} ：%s"
          % ("PASS" if not int_bad else "FAIL %s" % int_bad[:5]))
    print("   最高非零 level + 1 == tree_height ：%s"
          % ("PASS" if not h_bad else "FAIL %s" % h_bad[:5]))

    # flip 流配對：同組態、同 seed、同 budget，四個 policy 的 n_flip_events 應相同
    cells, mism = 0, []
    by = defaultdict(dict)
    for r in rows:
        by[(r["_cfg"], r["seed"], r["budget_bytes"])][r["policy"]] = int(r["n_flip_events"])
    for k, d in by.items():
        if len(d) < 2: continue
        cells += 1
        if len(set(d.values())) != 1: mism.append((k, d))
    print("4. flip 流跨 policy 配對（同 cfg/seed/budget）：%d/%d cell 完全相同%s"
          % (cells - len(mism), cells,
             "" if not mism else "\n   分歧：%s" % mism[:4]))

    # 全額覆蓋下 FULL_CRC 必須 recall=1、SDC=0。
    # ⚠️ 判準要用「該 run 自己的頁數」：B_full 這個刻度是用 seed 1 的幾何開的，
    # 其他 seed 的樹若略大，該格就不是真的全額覆蓋（見下方 short 計數）。
    full_bad, short = [], []
    for r in rows:
        if r["scheme"] != "FULL_CRC": continue
        b = budget_of(r)
        own_full = int(r["n_pages_allocated"]) * ENTRY_BYTES
        if b == float("inf") or b >= own_full:
            if fnum(r["recall"]) != 1.0 or int(r["n_wrong_undetected"]) != 0:
                full_bad.append((r["run_id"], r["recall"], r["n_wrong_undetected"]))
        elif b >= geo[r["_cfg"]]["B_full"]:
            short.append((r["run_id"], (own_full - int(b)) // ENTRY_BYTES,
                          r["recall"], int(r["n_wrong_undetected"])))
    print("5. FULL_CRC 於 budget >= 該 run 自己的 B_full 恆 recall=1 且 SDC=0 ：%s"
          % ("PASS" if not full_bad else "FAIL %s" % full_bad[:5]))
    if short:
        print("   ⚠️ 「B_full」刻度對 %d 個 run 其實少了 %d..%d 個 entry"
              "（樹比 seed 1 大）；這些 run recall %.3f..%.3f，但 SDC 仍全為 %s。"
              % (len(short), min(x[1] for x in short), max(x[1] for x in short),
                 min(fnum(x[2]) for x in short), max(fnum(x[2]) for x in short),
                 "0" if all(x[3] == 0 for x in short) else "非 0"))

    # 幾何離散度
    print("\n6. 幾何（同組態跨 run 的離散度）")
    for c in cfg_order(geo):
        g = geo[c]
        print("   %-14s pages %d..%d  internal %d..%d  h=%d  levels=%s"
              % (c, g["n_pages_min"], g["n_pages_max"], g["n_int_min"],
                 g["n_int_max"], g["height"],
                 "/".join(str(x) for x in g["levels"][:g["height"]])))

    # 已知問題（§10.1 / §13 item 23）：最終掃描不推進模擬時鐘
    rm = [int(r["ram_misses"]) for r in rows]
    print("\n7. ⚠️ ram_misses / ram_lru_evictions 由最終完整性掃描主導（§13 item 23）："
          "本批 ram_misses 範圍 %d..%d，不可解讀為主迴圈逐出壓力。"
          % (min(rm), max(rm)))


def table(rows, geo):
    by = defaultdict(list)
    for r in rows:
        by[(r["_cfg"], budget_of(r), r["policy"])].append(r)
    for c in cfg_order(geo):
        g = geo[c]
        print("\n### %s  (internal=%d, pages=%d, h=%d, B_int=%d B, B_full=%d B)"
              % (c, g["n_int"], g["n_pages"], g["height"], g["B_int"], g["B_full"]))
        budgets = sorted({budget_of(r) for r in rows if r["_cfg"] == c})
        hdr = ("| budget (B) | entries | ×B_int | %B_full | "
               + " | ".join(POLICIES) + " |")
        print(hdr)
        print("|" + "---|" * (4 + len(POLICIES)))
        for b in budgets:
            ent = "all" if b == float("inf") else int(b // ENTRY_BYTES)
            xint = "inf" if b == float("inf") else "%.2f" % (b / g["B_int"])
            pf = "100+" if b == float("inf") else "%.3f" % (100.0 * b / g["B_full"])
            cells = []
            for p in POLICIES:
                rs = by.get((c, b, p), [])
                m, s = mean_std([fnum(r["n_wrong_undetected"]) / fnum(r["n_searches"])
                                 for r in rs])
                cells.append("%.3e" % m if rs else "-")
            print("| %s | %s | %s | %s | %s |"
                  % ("inf" if b == float("inf") else "%d" % b, ent, xint, pf,
                     " | ".join(cells)))


def full_table(rows, geo):
    """每個 config × budget × policy 的完整 cell（3 seeds 平均；SDC 附樣本標準差）。"""
    by = defaultdict(list)
    for r in rows:
        by[(r["_cfg"], budget_of(r), r["policy"])].append(r)
    for c in cfg_order(geo):
        g = geo[c]
        print("\n#### %s  internal=%d  pages=%d  h=%d  B_int=%d B  B_full=%d B  "
              "internal 佔比 %.3f %%"
              % (c, g["n_int"], g["n_pages"], g["height"], g["B_int"], g["B_full"],
                 g["int_share"]))
        print("| budget (B) | ×B_int | %B_full | policy | SDC rate | ±std | recall | "
              "wrong_undet | wrong_total | final_err | crash | poisoned | recov | "
              "rejected | lat (µs) |")
        print("|" + "---|" * 15)
        for b in sorted({budget_of(r) for r in rows if r["_cfg"] == c}):
            for p in POLICIES:
                rs = by.get((c, b, p), [])
                if not rs:
                    continue
                m, sd = mean_std([fnum(r["n_wrong_undetected"]) / fnum(r["n_searches"])
                                  for r in rs])
                def av(k, scale=1.0):
                    return mean_std([fnum(r[k]) * scale for r in rs])[0]
                rc = mean_std([fnum(r["recall"]) for r in rs])[0]
                print("| %s | %s | %s | %s | %.4e | %.1e | %s | %.1f | %.1f | %.1f | "
                      "%.1f | %.1f | %.1f | %.1f | %.3f |"
                      % ("inf" if b == float("inf") else "%d" % b,
                         "inf" if b == float("inf") else "%.2f" % (b / g["B_int"]),
                         "100+" if b == float("inf")
                         else "%.3f" % (100.0 * b / g["B_full"]),
                         p, m, sd,
                         "-" if math.isnan(rc) else "%.4f" % rc,
                         av("n_wrong_undetected"), av("n_wrong_total"),
                         av("n_final_integrity_errors"), av("n_would_crash"),
                         av("n_poisoned_writes"), av("n_recoveries"),
                         av("n_shadow_rejected"),
                         av("mean_op_latency_s", 1e6)))


def knee(rows, geo):
    """膝點：SDC 相對 budget=0 下降達 95 % / 99 % 的最小預算。"""
    by = defaultdict(list)
    for r in rows:
        by[(r["_cfg"], budget_of(r), r["policy"])].append(r)
    print("\n### 膝點（SDC 相對 budget=0 的降幅門檻）\n")
    print("| config | policy | SDC(0) | 95 % 降幅 budget | ×B_int | %B_full | "
          "99 % 降幅 budget | ×B_int | %B_full | 飽和膝點(<=1.05×plateau) | "
          "plateau=SDC(4×B_int) | SDC(inf) |")
    print("|" + "---|" * 12)
    for c in cfg_order(geo):
        g = geo[c]
        budgets = sorted({budget_of(r) for r in rows if r["_cfg"] == c})
        for p in POLICIES:
            def sdc(b):
                rs = by.get((c, b, p), [])
                return mean_std([fnum(r["n_wrong_undetected"]) / fnum(r["n_searches"])
                                 for r in rs])[0] if rs else float("nan")
            s0 = sdc(0.0)
            sinf = sdc(float("inf"))
            plateau = sdc(budgets[-3]) if len(budgets) >= 3 else float("nan")
            out = []
            for thr in (0.05, 0.01):
                hit = None
                for b in budgets:
                    if not math.isnan(sdc(b)) and sdc(b) <= s0 * thr:
                        hit = b
                        break
                if hit is None:
                    out += ["—", "—", "—"]
                else:
                    out += ["inf" if hit == float("inf") else "%d" % hit,
                            "inf" if hit == float("inf") else "%.2f" % (hit / g["B_int"]),
                            "100+" if hit == float("inf")
                            else "%.3f" % (100.0 * hit / g["B_full"])]
            # 「飽和膝點」：SDC 落到自身 plateau（4xB_int 那格）的 1.05 倍以內
            sat = "—"
            for b in budgets:
                v = sdc(b)
                if not math.isnan(v) and not math.isnan(plateau) and v <= plateau * 1.05:
                    sat = ("inf" if b == float("inf")
                           else "%d (%.2fxB_int)" % (b, b / g["B_int"]))
                    break
            print("| %s | %s | %.4e | %s | %s | %.4e | %.4e |"
                  % (c, p, s0, " | ".join(out), sat, plateau, sinf))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--qc", action="store_true")
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--knee", action="store_true")
    a = ap.parse_args()
    rows = load(a.csv)
    geo = cfg_geometry(rows)
    if a.qc: qc(rows, geo)
    if a.table: table(rows, geo)
    if a.knee: knee(rows, geo)
    if a.full: full_table(rows, geo)
    if not (a.qc or a.table or a.full or a.knee):
        qc(rows, geo); table(rows, geo); knee(rows, geo); full_table(rows, geo)


if __name__ == "__main__":
    main()
