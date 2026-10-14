#!/usr/bin/env bash
# run_e20_db.sh — E20：免費套件。
#   SANITY + range + slack(right) × {k0,k16,k32,r64} × 5 = 20
#   SANITY + range + slack(right) + align(k) × {k16,k32} × 5 = 10
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/e17_20_common.sh
queue_init
for d in k0 k16 k32 r64; do for sd in $SEEDS; do
  queue_run "e20db_rs_${d}_s${sd}" "--scheme=SANITY --sanity_range=1 --slack_guard=right $(keyargs $d) --seed=$sd \
--lambda_page=3e-3 --run_id=SANITY_rs_l0.003_s${sd}_${d} $STD"
done; done
for k in 16 32; do for sd in $SEEDS; do
  queue_run "e20db_rsa_k${k}_s${sd}" "--scheme=SANITY --sanity_range=1 --slack_guard=right --sanity_align_log2=$k \
--key_stride_log2=$k --seed=$sd --lambda_page=3e-3 --run_id=SANITY_rsa_l0.003_s${sd}_k${k} $STD"
done; done
queue_exec "$DB_BIN"
check_parts "e20db_" 30
merge_parts "e20db_" results/e20_dbscale.csv
