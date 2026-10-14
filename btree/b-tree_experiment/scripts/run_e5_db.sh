#!/usr/bin/env bash
# run_e5_db.sh — E5'：DB 規模的「受限 RAM / 自然清洗」掃描（λ = 3e-3、EVERY_READ）。
#
# 舊 E5（SUMMARY.md）用 rpb ∈ {512,128,64,32,16}，那是為 order=8 的 ~1339 頁小樹
# 挑的刻度（容量 = 8 × rpb = 4096…128 頁 → 樹的 3.06× … 0.096×）。
# DB 樹是 ~5776 頁，直接沿用會全部落在「完全常駐」那一側，什麼都看不到。
# 本掃描把**容量/樹大小的比值**對齊舊 E5，重新挑刻度（校準見 SUMMARY_dbscale.md §10）：
#
#   rpb   容量(頁)  容量/樹(5776)   角色
#   2048  16384     2.84×           全常駐（= E1' 的組態，跨表錨點）
#    720   5760      0.997×         逐出剛好開始的臨界點
#    512   4096      0.709×
#    256   2048      0.355×
#    128   1024      0.177×
#     64    512      0.0887×
#     32     256     0.0443×        重度逐出（舊 E5 最極端點的對應）
#
# scheme 只跑 4 個：E1' 已證明 HDR_CRC / HDR_MIRROR 的 SDC 與 NONE 逐位元相同
# （降幅 ≤ 2.6 %），沒有必要在每個後續實驗裡重證一次。
# 5 seeds（同 E1'）：本實驗的 NONE 更容易被「內部節點樂透」支配（見 §10 警告）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh

E5_COMMON="--order=$DB_ORDER --prefill_keys=$DB_PREFILL --n_ops=$DB_NOPS \
--ssd_blocks=$DB_SSD_BLOCKS"

schemes="NONE SANITY CTRL_CRC FULL_CRC"
rpbs="2048 720 512 256 128 64 32"
seeds="1 2 3 4 5"

queue_init
for s in $schemes; do
  for rpb in $rpbs; do
    for sd in $seeds; do
      queue_run "e5db_${s}_rpb${rpb}_s${sd}" \
        "--scheme=$s --lambda_page=3e-3 --seed=$sd --ram_rows_per_bank=$rpb $E5_COMMON"
    done
  done
done
queue_exec "$DB_BIN"
merge_parts "e5db_" results/e5_dbscale.csv
