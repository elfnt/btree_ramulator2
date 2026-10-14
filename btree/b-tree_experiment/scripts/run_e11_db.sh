#!/usr/bin/env bash
# run_e11_db.sh — E11：只對單一層注入，分離兩個盲區。
# {NONE,SANITY,CTRL_CRC} × stride {0,16,32} × inject_level {internal,leaf} × 3 seeds = 54 runs。
# λ 校準（per page，Poisson 均值 = λ × |filtered resident| × dt）：
#   internal：33 個 internal 頁 × 3e-3 × 300 s ≈ 38 flips/run（太少）→ λ = 0.15（×50）
#             實測 seed 1：1 479 flips/run
#   leaf    ：λ = 3e-3（標準值），實測 ~5 130 flips/run
# 其他參數 = E7′（order 253、1M keys、EVERY_READ、budget ∞）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh
source scripts/e8_12_common.sh
queue_init
for il in internal:0.15 leaf:3e-3; do
  lv="${il%%:*}"; lam="${il##*:}"
  for k in 0 16 32; do
    for s in NONE SANITY CTRL_CRC; do
      for sd in 1 2 3; do
        queue_run "e11db_${lv}_k${k}_${s}_s${sd}" \
          "--scheme=$s --lambda_page=$lam --seed=$sd --key_stride_log2=$k --inject_level=$lv \
--run_id=${s}_${lv}_l${lam}_s${sd}_k${k} $DB_COMMON"
      done
    done
  done
done
queue_exec "$DB_BIN"
check_parts "e11db_" 54
merge_parts "e11db_" results/e11_dbscale.csv
