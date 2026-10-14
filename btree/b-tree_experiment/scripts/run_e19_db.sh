#!/usr/bin/env bash
# run_e19_db.sh — E19：leaf 空 slot 的 dummy（--slack_guard）。SANITY × {right,both} × {k8,k16,k32,r64} × 5 = 40
# 幾何同 1×（頁數不變，不需放大）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/e17_20_common.sh
queue_init
for g in right both; do for d in k8 k16 k32 r64; do for sd in $SEEDS; do
  queue_run "e19db_${g}_${d}_s${sd}" "--scheme=SANITY --slack_guard=$g $(keyargs $d) --seed=$sd \
--lambda_page=3e-3 --run_id=SANITY_slack${g}_l0.003_s${sd}_${d} $STD"
done; done; done
queue_exec "$DB_BIN"
check_parts "e19db_" 40
merge_parts "e19db_" results/e19_dbscale.csv
