#!/usr/bin/env bash
# run_e12_db.sh — E12：NONE 的 SDC 為何隨 key 稀疏度下降？
# 錯誤搜尋三分類 n_wrong_{missing,value,phantom}（+ 無報警子集 n_sdc_*）。
# 參數 = E7′ 完全相同（λ=3e-3、order 253、1M keys、EVERY_READ、budget ∞）。
# {NONE,SANITY} × stride {0,8,16,24,32} × 5 seeds = 50 runs。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh
source scripts/e8_12_common.sh
queue_init
for k in 0 8 16 24 32; do
  for s in NONE SANITY; do
    for sd in 1 2 3 4 5; do
      queue_run "e12db_k${k}_${s}_s${sd}" \
        "--scheme=$s --lambda_page=3e-3 --seed=$sd --key_stride_log2=$k \
--run_id=${s}_l0.003_s${sd}_k${k} $DB_COMMON"
    done
  done
done
queue_exec "$DB_BIN"
check_parts "e12db_" 50
merge_parts "e12db_" results/e12_dbscale.csv
python3 scripts/regcheck.py results/e12_dbscale.csv
