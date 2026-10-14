#!/usr/bin/env bash
# run_e9_db.sh — E9：SANITY 盲區邊緣是否追蹤 log2(stride × fanout)？
# order {16,64,253} × stride {0,8,16,24} × {NONE,SANITY,CTRL_CRC,FULL_CRC} × 3 seeds = 144 runs。
# 200k keys（order 16 在 1M 下 ~180k 頁太重）；ssd_blocks 依 order 挑成樹佔實體頁 ~30 %
# （同 run_e6a_db.sh 的做法），ram_rows_per_bank=8192（65 536 頁）→ 全常駐。
#   order 16  ~20k 頁 → 2048 blocks（65 536 實體頁）
#   order 64  ~4.6k 頁 →  512 blocks（16 384）
#   order 253 ~1.1k 頁 →  128 blocks（ 4 096，同 E6a′）
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh
source scripts/e8_12_common.sh
E9_KEYS=200000
E9_RPB=8192
queue_init
for os in 16:2048 64:512 253:128; do
  o="${os%%:*}"; sb="${os##*:}"
  for k in 0 8 16 24; do
    for s in NONE SANITY CTRL_CRC FULL_CRC; do
      for sd in 1 2 3; do
        queue_run "e9db_o${o}_k${k}_${s}_s${sd}" \
          "--scheme=$s --lambda_page=3e-3 --seed=$sd --order=$o --key_stride_log2=$k \
--prefill_keys=$E9_KEYS --n_ops=$DB_NOPS --ssd_blocks=$sb --ram_rows_per_bank=$E9_RPB \
--run_id=${s}_o${o}_l0.003_s${sd}_k${k}"
      done
    done
  done
done
queue_exec "$DB_BIN"
check_parts "e9db_" 144
merge_parts "e9db_" results/e9_dbscale.csv
