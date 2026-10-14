#!/usr/bin/env bash
# run_e7_db.sh — E7′：key 稀疏度軸（λ = 3e-3、order 253、1M keys、EVERY_READ、
#                budget = ∞、全常駐）。除了 `--key_stride_log2` 之外，每一個參數
#                都與 E1′ 的 λ=3e-3 那一格完全相同 → **stride = 0 那一欄就是該格**
#                （已逐欄驗證：30 run × 60 欄零差異，見 SUMMARY_dbscale.md §14.1）。
#
# ── 這條軸在問什麼 ───────────────────────────────────────────────────────────
# E1′ 的結果裡，免費的 `SANITY`（結構不變量、零可靠記憶體）幾乎抓到與
# `CTRL_CRC`（真正的 CRC）相同的東西：λ=3e-3 時 tp 1711.6 vs 1728.6（差 1.0 %），
# 但 `CTRL_CRC` 多付 24 個百分點的延遲（+67.9 % vs +44.1 %）。
#
# 假說：這是**工作負載**造成的假象，不是方案的性質。舊工作負載的 key 是
# **稠密連續整數**（prefill = iota(0..N-1)、主迴圈 append N+i），所以一個葉節點
# 裡相鄰 key 的間距恆為 1。`sanity_check()` 的「keys 嚴格遞增」在間距 1 之下
# 等於一個近乎完美的 key 陣列檢查碼：任何一個位元翻轉都讓 key 至少位移 1，
# 必然破壞嚴格遞增。
#
# 把 key 換成 `index << k`（間距 2^k）之後，翻到第 b < k 位的 flip 讓 key 位移
# 2^b < 2^k，排序**不會**被破壞 → `SANITY` 應該對它全盲，而 `CTRL_CRC` 照抓。
# 解析預測：`SANITY` 在 keys[] 上的偵測率應隨 k 大致以 (64−k)/64 下降，
# `CTRL_CRC` 則完全不動（keys[] 整段都在它的涵蓋範圍內）。
#
# ── 為什麼仍是 1M keys ───────────────────────────────────────────────────────
# 冒煙測試（seed 1、λ=3e-3、stride 16、FULL_CRC）量的是本實驗的統計量
# 「keys[] 內單一位元翻轉的事件數」：
#     200k keys → 310 事件/run（5 seeds = 1 550 → 64 個 bit bucket 各 ~24）
#     1M   keys → 1 318 事件/run（5 seeds = 6 590 → 各 ~103）
# 64 分辨率的直方圖在 200k 太薄；且 1M 讓 stride=0 那一欄直接等於 E1′ 的格子，
# 不必另做橋接。單 run wall：NONE 7.65 s、SANITY 7.95 s、CTRL_CRC 23.6 s、
# FULL_CRC 48.0 s（與 stride 無關——樹形與 flip 流逐格相同，只有 key 的位元組值變）。
#
# ── stride 的上限 ────────────────────────────────────────────────────────────
# 32。實際 key = index << stride，而 miss key 的 index 基底最大 1 999 999 999
# （< 2^31），左移 32 位後 < 2^63 仍在 uint64_t 內；stride 33 起會溢位，
# driver 會直接以錯誤碼拒絕（`main_experiment.cpp` 的護欄）。
# 工作負載本身的 index 上限（1 030 000）其實可以到 stride 43，
# 綁死在 32 的是 miss key——而 miss key 必須用同一個 stride 才能保證「不存在」。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh

schemes="NONE SANITY HDR_CRC CTRL_CRC FULL_CRC"
strides="0 8 16 24 32"
seeds="1 2 3 4 5"

queue_init
for k in $strides; do
  for s in $schemes; do
    for sd in $seeds; do
      # run_id 顯式給定：自動組合的 id 不含 stride，5 個 stride 會撞名
      queue_run "e7db_k${k}_${s}_s${sd}" \
        "--scheme=$s --lambda_page=3e-3 --seed=$sd --key_stride_log2=$k \
--run_id=${s}_BY_LEVEL_l0.003_binf_s${sd}_er_k${k} $DB_COMMON"
    done
  done
done
queue_exec "$DB_BIN"
merge_parts "e7db_" results/e7_dbscale.csv
