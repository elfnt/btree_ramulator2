#!/usr/bin/env bash
# run_e16_db.sh — E16：頁內 CRC（CRC32 存在頁面最後 4 B，零可靠記憶體）。
# {INPAGE_CTRL, INPAGE_FULL} × {stride 0, stride 32, random64} × 5 seeds = 30 runs。
# 參數 = E7′（λ=3e-3、order 253、1M keys、30 000 ops、EVERY_READ、budget ∞、1× 幾何）。
# 對照列（SANITY/HYBRID/CTRL_CRC/FULL_CRC）沿用 e10_dbscale.csv（stride）與 e8_dbscale.csv（random64）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh
source scripts/e8_12_common.sh
queue_init
for s in INPAGE_CTRL INPAGE_FULL; do
  for d in k0 k32 r64; do
    case $d in r64) kd="--key_dist=random64"; rid=random640 ;; *) kd="--key_stride_log2=${d#k}"; rid=$d ;; esac
    for sd in 1 2 3 4 5; do
      queue_run "e16db_${d}_${s}_s${sd}" "--scheme=$s --lambda_page=3e-3 --seed=$sd $kd \
--run_id=${s}_l0.003_s${sd}_${rid} $DB_COMMON"
    done
  done
done
queue_exec "$DB_BIN"
check_parts "e16db_" 30
merge_parts "e16db_" results/e16_dbscale.csv
