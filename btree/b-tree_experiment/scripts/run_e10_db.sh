#!/usr/bin/env bash
# run_e10_db.sh — E10：層級差異化 HYBRID（internal = CTRL_CRC、leaf = 免費 SANITY）。
# {SANITY,CTRL_CRC,FULL_CRC,HYBRID} × stride {0,8,16,24,32} × 5 seeds = 100 runs。
# 參數 = E7′（λ=3e-3、order 253、1M keys、EVERY_READ、budget ∞）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh
source scripts/e8_12_common.sh
queue_init
for k in 0 8 16 24 32; do
  for s in SANITY CTRL_CRC FULL_CRC HYBRID; do
    for sd in 1 2 3 4 5; do
      queue_run "e10db_k${k}_${s}_s${sd}" \
        "--scheme=$s --lambda_page=3e-3 --seed=$sd --key_stride_log2=$k \
--run_id=${s}_l0.003_s${sd}_k${k} $DB_COMMON"
    done
  done
done
queue_exec "$DB_BIN"
check_parts "e10db_" 100
merge_parts "e10db_" results/e10_dbscale.csv
python3 scripts/regcheck.py results/e10_dbscale.csv
