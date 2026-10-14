#!/usr/bin/env bash
# run_e6b_db.sh — E6b'：純規模軸（order 253 固定，λ = 3e-3、EVERY_READ、budget=∞）。
#
# 目的很窄：**E1' 的頭條結論（CTRL_CRC 以 ~4 成的 FULL_CRC 成本買到 ~99 % 的 SDC
# 防護）在 1M keys 以外還成不成立？** 因此只留三個 scheme（NONE 基線、
# CTRL_CRC 主角、FULL_CRC 上界），不重跑 SANITY/HDR_*。
#
# 規模刻度與其上限的校準（冒煙測試，單 run wall / 峰值 RSS，見 SUMMARY_dbscale.md §11）：
#   keys   頁數    NONE    CTRL_CRC  FULL_CRC   RSS
#   200k    1 128   1.6 s     4.7 s     10.1 s   ~100 MB
#   1M      5 776   7.6 s    24.4 s     48.8 s   ~197 MB
#   3M     17 160  30.4 s    87.1 s    153.8 s   ~515 MB
#   5M     29 344  62.1 s   165.9 s    264.4 s   ~910 MB
#   10M    ~58 000 222.8 s      —      > 600 s  ~1.80 GB   ← 超出預算，故 5M 為上限
# 樹高在 200k–5M 全程 = 3（order 253 的 h=3 可容 253^3 ≈ 1.6e7 個 key），
# 所以這條軸是「同一形狀的樹變大」，不混入樹高變化。
#
# ssd_blocks 逐規模挑成「樹佔實體頁 ~22–35 %」（與 E1' 的 35 % 同級）；
# ram_rows_per_bank 一律讓容量 > 樹頁數 → 全常駐、無自然清洗（同 E1'–E4'）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh

schemes="NONE CTRL_CRC FULL_CRC"
seeds="1 2 3 4 5"

# keys:ssd_blocks:ram_rows_per_bank
scales="200000:128:1024 1000000:512:2048 3000000:2048:4096 5000000:4096:8192"

queue_init
for sc in $scales; do
  k="${sc%%:*}"; rest="${sc#*:}"; sb="${rest%%:*}"; rpb="${rest##*:}"
  for s in $schemes; do
    for sd in $seeds; do
      queue_run "e6bdb_k${k}_${s}_s${sd}" \
        "--scheme=$s --lambda_page=3e-3 --seed=$sd --order=$DB_ORDER \
--prefill_keys=$k --n_ops=$DB_NOPS --ssd_blocks=$sb --ram_rows_per_bank=$rpb"
    done
  done
done
queue_exec "$DB_BIN"
merge_parts "e6bdb_" results/e6b_dbscale.csv
