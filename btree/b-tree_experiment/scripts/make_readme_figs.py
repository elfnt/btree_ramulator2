#!/usr/bin/env python3
"""Draw the README figures (no new runs).

  python3 scripts/make_readme_figs.py              # ram backend  → results/figures/readme/
  BACKEND=r2 python3 scripts/make_readme_figs.py   # Ramulator2   → results/figures/readme_r2/

Data: results/paper[_r2]/paper_data.json for means (latency, pages, detection ratios) and the raw CSVs
for medians of wrong-answer counts. SANITY / NONE have heavy-tailed seeds (one seed can hit a hot
internal node and produce hundreds of wrong answers), so wrong-answer counts and SDC are shown as the
median over seeds; latency is the mean (it is stable across seeds).
"""
import csv, json, os
from statistics import median
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.environ.get("BACKEND", "ram")
R2 = BACKEND == "r2"
D = json.load(open(os.path.join(ROOT, "results", "paper_r2" if R2 else "paper", "paper_data.json")))
OUT = os.path.join(ROOT, "results/figures", "readme_r2" if R2 else "readme")
os.makedirs(OUT, exist_ok=True)
TAG = "Ramulator2 DDR4-2400" if R2 else "C++ DRAM model"


def csvrows(name_ram, name_r2):
    p = os.path.join(ROOT, "results", ("r2/" + name_r2) if R2 else name_ram)
    return list(csv.DictReader(open(p)))


def med(rows, col="n_wrong_undetected"):
    return median(float(r[col]) for r in rows) if rows else float("nan")


def med_sdc(rows):
    return median(float(r["n_wrong_undetected"]) / float(r["n_searches"]) for r in rows)


C = {"NONE": "#e34948", "SANITY": "#2a78d6", "CTRL_CRC": "#eb6834", "FULL_CRC": "#4a3aa7"}
M = {"NONE": "o", "SANITY": "s", "CTRL_CRC": "^", "FULL_CRC": "D"}
INK, MUTED, GRID = "#1d2430", "#6b7482", "#e3e7ec"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": "#c3c9d2", "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "figure.dpi": 150,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
})
LW, MS = 2, 6.5


def line(ax, x, y, s, label=None, **kw):
    ax.plot(x, y, color=C[s], marker=M[s], lw=LW, ms=MS, mec="white", mew=1.2, label=label or s, **kw)


def save(fig, name):
    fig.text(0.995, 0.005, TAG, ha="right", va="bottom", fontsize=8, color=MUTED)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, name), bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ── Fig 1: E1 SDC (median over seeds) and latency vs error rate ─────────────
e1csv = csvrows("e1_dbscale.csv", "e1_r2.csv")
if not R2:  # ram: CTRL_CRC from the header-covering rerun
    e1csv = [r for r in e1csv if r["scheme"] != "CTRL_CRC"] + list(csv.DictReader(open(os.path.join(ROOT, "results/e1_ctrlhdr.csv"))))
lams = sorted({float(r["lambda_page"]) for r in e1csv})
fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.8))
for s in ["NONE", "SANITY", "CTRL_CRC"]:
    pts = [(l, med_sdc([r for r in e1csv if r["scheme"] == s and float(r["lambda_page"]) == l])) for l in lams]
    pts = [(l, v) for l, v in pts if v > 0]
    line(a, [p[0] for p in pts], [p[1] for p in pts], s)
a.set_xscale("log"); a.set_yscale("log")
a.set_xlabel("bit-flip rate λ (flips / page / s)"); a.set_ylabel("SDC rate (median of 5 seeds)")
a.set_title("(a) Silent data corruption")
a.text(0.98, 0.04, "FULL_CRC: SDC = 0 in every run", transform=a.transAxes, ha="right", color=MUTED, fontsize=9)
a.legend(loc="upper left")
for s in ["NONE", "SANITY", "CTRL_CRC", "FULL_CRC"]:
    rows = sorted([r for r in D["E1"] if r["scheme"] == s], key=lambda r: r["lambda"])
    line(b, [r["lambda"] for r in rows], [r["lat_us"] for r in rows], s)
b.set_xscale("log"); b.set_xlabel("bit-flip rate λ (flips / page / s)"); b.set_ylabel("mean latency per op (µs)")
b.set_title("(b) Time cost"); b.legend(loc="upper left")
save(fig, "fig1_e1_sdc_latency.png")

# ── Fig 2: E2 budget knee at B_int ──────────────────────────────────────────
resc = D["E2"]["rescaled"]
pending = []
if R2 and "e2e_dbscale.csv" in D["common"].get("ram_fallback", []):
    pending.append(resc.pop("E2E"))          # E2e on Ramulator2 still running: do not mix in ram rows
xs = [0, 0.1, 0.25, 0.5, 0.75, 1.0, 2.0, 4.0]
cfg_col = {"E2B": "#2a78d6", "E2C": "#1baf7a", "E2D": "#eb6834", "E2E": "#4a3aa7"}
cfg_mk = {"E2B": "o", "E2C": "s", "E2D": "^", "E2E": "D"}
fig, ax = plt.subplots(figsize=(10, 3.9))
for cid, cfg in resc.items():
    for pol, ls, alpha in [("BY_LEVEL", "-", 1.0), ("LRU", "--", 0.55)]:
        rows = [r for r in cfg["rows"] if r["policy"] == pol and r["budget_bytes"] not in ("inf", "INF")
                and float(r["budget_bytes"]) < 0.9 * cfg["B_full"]]
        rows.sort(key=lambda r: float(r["budget_bytes"]))
        assert len(rows) == len(xs), (cid, pol, len(rows))
        lab = (f"order {cfg['order']}, {int(round(cfg['n_internal'])):,} internal nodes" if pol == "BY_LEVEL" else None)
        ax.plot(range(len(xs)), [r["sdc"] for r in rows], ls=ls, color=cfg_col[cid], marker=cfg_mk[cid], lw=LW,
                ms=MS, mec="white", mew=1.2, alpha=alpha, label=lab)
ax.axvline(xs.index(1.0), color=INK, lw=1, ls=":")
ax.text(xs.index(1.0) + 0.06, 0.03, "budget = B_int\n(all internal nodes fit)", color=INK, fontsize=9, va="bottom",
        transform=ax.get_xaxis_transform())
if pending:
    ax.text(0.99, 0.97, "order 16 (16,076 internal nodes): Ramulator2 run in progress", transform=ax.transAxes,
            ha="right", va="top", fontsize=8.5, color=MUTED)
ax.set_xticks(range(len(xs))); ax.set_xticklabels([f"{x:g}×" for x in xs])
ax.set_yscale("log"); ax.set_xlabel("reliable-memory budget, in multiples of B_int")
ax.set_ylabel("SDC rate"); ax.set_title("Budget knee sits at exactly B_int in every tree  (solid = BY_LEVEL, dashed = LRU)")
ax.legend(loc="lower left", fontsize=9)
save(fig, "fig2_e2_budget_knee.png")

# ── Fig 3: E7 key sparsity ──────────────────────────────────────────────────
e7 = D["E7"]["rows"]
san = sorted([r for r in e7 if r["scheme"] == "SANITY"], key=lambda r: r["stride_log2"])
ks = [r["stride_log2"] for r in san]
e7csv = csvrows("e7_dbscale.csv", "e7_r2.csv")
if not R2:
    e7csv = [r for r in e7csv if r["scheme"] != "CTRL_CRC"] + list(csv.DictReader(open(os.path.join(ROOT, "results/e7_ctrlhdr.csv"))))
fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.8))
a.plot(ks, [(64 - k) / 64 for k in ks], color=MUTED, lw=1.5, ls="--", label="model (64 − k) / 64")
line(a, ks, [r["detection_ratio_vs_ctrl"] for r in san], "SANITY", label="measured SANITY / CTRL_CRC")
a.set_ylim(0.4, 1.02); a.set_xticks(ks); a.set_xticklabels([f"$2^{{{k}}}$" for k in ks])
a.set_xlabel("spacing between adjacent keys"); a.set_ylabel("detection relative to CTRL_CRC")
a.set_title("(a) Free check loses one bit per doubling"); a.legend(loc="lower left")
for s in ["SANITY", "CTRL_CRC"]:
    line(b, ks, [med_sdc([r for r in e7csv if r["scheme"] == s and int(r["key_stride_log2"]) == k]) * 1e4 for k in ks], s)
b.set_xticks(ks); b.set_xticklabels([f"$2^{{{k}}}$" for k in ks]); b.set_ylim(0, 20 if R2 else 12)
b.set_xlabel("spacing between adjacent keys"); b.set_ylabel("SDC rate, median of 5 seeds (×10⁻⁴)")
b.set_title("(b) End-to-end effect"); b.legend(loc="lower right")
save(fig, "fig3_e7_key_sparsity.png")

# ── Fig 4: raising key density — detection vs pages, and wrong answers vs cost ──
ext = D["E7ext"]


def get(arm, scheme):
    return next(r for r in ext if r["arm"].startswith(arm) and r["scheme"] == scheme)


e13 = csvrows("e13_dbscale.csv", "e13_r2.csv")
e22 = csvrows("e22_dbscale.csv", "e22_r2.csv")
e21 = csvrows("e21_dbscale.csv", "e21_r2.csv")
sel = {  # arm label -> SANITY rows of that arm (for medians)
    "stride 2³², plain": [r for r in e13 if r["scheme"] == "SANITY" and r["key_dist"] == "stride" and r["key_stride_log2"] == "32" and r["guard"] == "none" and r["ssd_blocks"] == "512"],
    "grid, 1 dummy": [r for r in e13 if r["scheme"] == "SANITY" and r["key_stride_log2"] == "32" and r["guard"] == "mid"],
    "grid, 3 dummies": [r for r in e22 if r["scheme"] == "SANITY" and r["guard_grid_log2"] == "30"],
    "grid, 7 dummies": [r for r in e22 if r["scheme"] == "SANITY" and r["guard_grid_log2"] == "29"],
    "adjacent, right": [r for r in e13 if r["scheme"] == "SANITY" and r["key_stride_log2"] == "32" and r["guard"] == "right"],
    "shift K>>32": [r for r in e21 if r["key_map"] == "shift"],
    "random64, plain": [r for r in e13 if r["scheme"] == "SANITY" and r["key_dist"] == "random64" and r["guard"] == "none" and r["ssd_blocks"] == "512"],
    "hash map α=0.25": [r for r in e21 if r["key_map"] == "hashdense" and r["key_dist"] == "random64" and r["scheme"] == "SANITY" and float(r["map_load"]) == 0.25],
    "hash map α=0.75": [r for r in e21 if r["key_map"] == "hashdense" and r["key_dist"] == "random64" and r["scheme"] == "SANITY" and float(r["map_load"]) == 0.75],
}
meanrow = {"stride 2³², plain": get("none", "SANITY"), "grid, 1 dummy": get("grid k=31", "SANITY"),
           "grid, 3 dummies": get("grid k=30", "SANITY"), "grid, 7 dummies": get("grid k=29", "SANITY"),
           "adjacent, right": get("adjacent right", "SANITY"), "shift K>>32": get("shift", "SANITY"),
           "random64, plain": get("none (plain random64", "SANITY"), "hash map α=0.25": get("hash α=0.25", "SANITY"),
           "hash map α=0.75": get("hash α=0.75", "SANITY")}
dense_ratio = next(r for r in e7 if r["scheme"] == "SANITY" and r["stride_log2"] == 0)["detection_ratio_vs_ctrl"]

fig, (a, b) = plt.subplots(1, 2, figsize=(10.5, 4.0), gridspec_kw={"width_ratios": [1, 1.35]})
grid = [get("none", "SANITY")] + [get(f"grid k={k}", "SANITY") for k in (31, 30, 29)]
gm = [r["pages"] / grid[0]["pages"] for r in grid]
a.plot(gm, [r["detection_ratio"] for r in grid], color=C["SANITY"], marker="o", lw=LW, ms=MS, mec="white",
       mew=1.2, label="dummies on a 2^k grid inside the gap")
adj = [get("adjacent right", "SANITY"), get("adjacent both", "SANITY")]
a.plot([r["pages"] / grid[0]["pages"] for r in adj], [r["detection_ratio"] for r in adj], ls="none",
       color=C["CTRL_CRC"], marker="^", ms=8, mec="white", mew=1.2, label="dummies adjacent to each key")
for r, t in zip(adj, ["right", "both"]):
    a.annotate(t, (r["pages"] / grid[0]["pages"], r["detection_ratio"]), textcoords="offset points",
               xytext=(0, -14), ha="center", fontsize=8.5, color=INK)
a.plot([1], [dense_ratio], ls="none", marker="D", ms=8, mfc="white", mec=C["FULL_CRC"], mew=1.8,
       label="shift K>>32 (behaves as dense keys)")
a.set_xscale("log", base=2); a.set_xticks([1, 2, 4, 8]); a.set_xticklabels(["1×", "2×", "4×", "8×"])
a.set_ylim(0.4, 1.03); a.set_xlabel("pages relative to the plain tree"); a.set_ylabel("SANITY detection / CTRL_CRC")
a.set_title("(a) Detection vs page cost (keys spaced 2³²)"); a.legend(loc="center right", fontsize=8.5)
names = list(sel)
y = list(range(len(names)))[::-1]
miss = [med(sel[n], "n_sdc_missing") for n in names]; val = [med(sel[n], "n_sdc_value") for n in names]
b.barh(y, miss, height=0.6, color="#d8588c", label="key not found")
b.barh(y, val, left=miss, height=0.6, color="#b3bac5", label="wrong value (no structural check can see it)")
base_lat = {"stride": meanrow["stride 2³², plain"]["lat_us"], "random": meanrow["random64, plain"]["lat_us"]}
for yi, n in zip(y, names):
    r = meanrow[n]
    pm = r["pages"] / 5762.8
    lm = r["lat_us"] / (base_lat["random"] if ("random" in n or "hash" in n) else base_lat["stride"])
    b.text(miss[names.index(n)] + val[names.index(n)] + 0.8, yi, f"{pm:.0f}× pages, {lm:.1f}× latency",
           va="center", fontsize=8.5, color=INK)
b.set_yticks(y); b.set_yticklabels(names); b.set_xlim(0, 75)
b.set_xlabel("undetected wrong answers per run (SANITY, median of 5 seeds)")
b.set_title("(b) What it buys end to end, and what it costs")
b.legend(loc="upper center", bbox_to_anchor=(0.45, -0.16), ncol=2, fontsize=8.5)
b.grid(axis="y", visible=False)
save(fig, "fig4_key_density.png")
print("ok", OUT, sorted(os.listdir(OUT)))
