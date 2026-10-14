#!/usr/bin/env bash
# run_e2large_db.sh — E2b′/E2c′/E2d′：在「內部節點數真的很多」的樹上重測
# 「預算 × 逐出政策」（λ = 3e-3、FULL_CRC、EVERY_READ、3 seeds）。
#
# ── 為什麼要重測 E2′（§6）────────────────────────────────────────────────────
# E2′ 跑在 order=253 / 1M keys。實測（本批的儀器）該樹只有 **33 個內部節點**
# （29 個 level-1 + ... 見 §15.1），佔全樹 0.57 %。於是「512 B 就把 SDC 砍 98.7 %」
# 這個頭條結論，其實是「33 × 12 B = 396 B 就能裝下整個上層」的算術後果，
# 不是大 B+ 樹的性質。order 253 要 253³ ≈ 1.6e7 個 key 才會長到 h=4，
# 所以**單靠加大 N 沒辦法把內部節點變多**；必須降 fanout。
#
# 三個組態（內部節點數 130 → 1 052 → 4 159，實測值）：
#   E2b′  order=253  5M keys   h=3   同 fanout、只放大 N（與 E2′ 直接可比）
#   E2c′  order=64   2M keys   h=4   深樹，~1k 內部節點
#   E2d′  order=32   2M keys   h=5   深樹，~4k 內部節點
#
# ── 關鍵方法修正：預算軸改成「相對刻度」──────────────────────────────────────
# E2′ 用絕對刻度（0/128/…/69312 B），那是為 33 個內部節點量身訂做的。
# 同一組數字放到 4 159 個內部節點的樹上毫無意義（光蓋住內部節點就要 ~50 KB）。
# 因此本批的預算一律定義成 **entry 數的倍數**：
#     B_int  = n_internal_total × 12 B   （恰好裝下全部內部節點）
#     B_full = n_pages_allocated × 12 B  （裝下每一頁）
# 掃描點 = {0, 0.1, 0.25, 0.5, 0.75, 1, 2, 4} × B_int，外加 B_full 與 inf。
# 這樣「膝點在不在 1×B_int」在三個組態裡是同一個問題，可以逐點對照。
#
# B_int / B_full 由 **seed 1 的 NONE 冒煙 run** 實測（見 SUMMARY_dbscale.md §15.0），
# 之後對該組態的所有 cell 固定不變——預算軸必須是跨 cell 的常數，
# 不能每個 seed 各自浮動，否則同一欄的格子不可比。
#
# ── scheme 只跑 FULL_CRC ─────────────────────────────────────────────────────
# 與 E2′ 逐點可比（E2′ 的 CTRL_CRC/FULL_CRC 在 budget < 全額時差 ≤ 3 %，
# 結論由 policy 決定而非 per-page 覆蓋範圍）。省下的一半 runtime 拿去換
# 更細的預算刻度（10 點）與第三個組態。
#
# ── 校準（冒煙測試：seed 1、λ=3e-3、n_ops=30000、6 路同時跑）────────────────
#   組態     pages   h  internal  NONE     FULL_CRC(∞)  峰值 RSS
#   E2b′     29 344  3      130   1:22     4:44         1.12 GB
#   E2c′     46 034  4    1 052   0:40     2:26         1.16 GB
#   E2d′     93 713  5    4 159   1:06     3:14         2.18 GB
#   E2e′    193 839  6   16 044   2:34     6:17         4.40 GB   ← 後補的第四點
# 前三個組態單 run 上界 ≈ 285 s、RSS ≤ 2.2 GB → 20 路平行 ≈ 30 GB，安全。
# E2e′ 的 RSS 4.40 GB 只能 9 路平行（≈ 40 GB），所以另外分批跑：
#   DB_JOBS=9 bash scripts/run_e2large_db.sh e2e
# 合計 480 runs（4 組態 × 10 budget × 4 policy × 3 seeds）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh

policies="BY_LEVEL BY_HOTNESS LRU RANDOM"
seeds="1 2 3"
DB_JOBS="${DB_JOBS:-20}"

# tag:order:prefill:ssd_blocks:rpb:n_internal:n_pages   （後兩者 = seed 1 冒煙實測）
ALL_CONFIGS="e2b:253:5000000:4096:8192:130:29344 \
e2c:64:2000000:5120:8192:1052:46034 \
e2d:32:2000000:10240:16384:4159:93713 \
e2e:16:2000000:21504:32768:16044:193839"

# 不給引數 = 跑全部；給 tag（如 `run_e2large_db.sh e2e`）= 只跑該組態。
# E2e′ 是後補的第四點（16 044 個內部節點），實務上與前三個分批跑：
# 它的峰值 RSS 4.40 GB 撐不住 20 路平行，見 §15.0 的校準表。
if [ $# -gt 0 ]; then
  configs=""
  for want in "$@"; do
    for c in $ALL_CONFIGS; do
      case "$c" in "$want":*) configs="$configs $c";; esac
    done
  done
  [ -n "$configs" ] || { echo "no config matched: $*" >&2; exit 2; }
else
  configs="$ALL_CONFIGS"
fi

ENTRY_BYTES=12          # FULL_CRC 的 shadow entry 大小（scheme_entry_bytes）

queue_init
for cfg in $configs; do
  IFS=':' read -r tag ord keys sb rpb nint npage <<< "$cfg"
  bfull=$(( npage * ENTRY_BYTES ))
  # 以 **entry 數** 取整（而不是 byte 數），讓 budget/12 恰好是想要的 entry 數
  budgets=""
  for pct in 0 10 25 50 75 100 200 400; do
    e=$(( (nint * pct + 50) / 100 ))
    budgets="$budgets $(( e * ENTRY_BYTES ))"
  done
  budgets="$budgets $bfull inf"

  for p in $policies; do
    for b in $budgets; do
      for sd in $seeds; do
        queue_run "${tag}db_FULL_CRC_${p}_b${b}_s${sd}" \
          "--scheme=FULL_CRC --lambda_page=3e-3 --policy=$p --budget_bytes=$b --seed=$sd \
--order=$ord --prefill_keys=$keys --n_ops=$DB_NOPS --ssd_blocks=$sb --ram_rows_per_bank=$rpb"
      done
    done
  done
done
queue_exec "$DB_BIN"

for c in $configs; do
  tag="${c%%:*}"
  merge_parts "${tag}db_" "results/${tag}_dbscale.csv"
done
