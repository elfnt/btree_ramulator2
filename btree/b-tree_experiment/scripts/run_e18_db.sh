#!/usr/bin/env bash
# run_e18_db.sh — E18：對齊檢查（--sanity_align_log2 = stride）。SANITY+align × stride {8,16,32} × 5 = 15
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/e17_20_common.sh
queue_init
for k in 8 16 32; do for sd in $SEEDS; do
  queue_run "e18db_k${k}_s${sd}" "--scheme=SANITY --sanity_align_log2=$k --key_stride_log2=$k --seed=$sd \
--lambda_page=3e-3 --run_id=SANITY_a${k}_l0.003_s${sd}_k${k} $STD"
done; done
queue_exec "$DB_BIN"
check_parts "e18db_" 15
merge_parts "e18db_" results/e18_dbscale.csv
