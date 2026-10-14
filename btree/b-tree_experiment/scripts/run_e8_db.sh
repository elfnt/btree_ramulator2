#!/usr/bin/env bash
# run_e8_db.sh — E8：(64−k)/64 公式在真實 key 分佈下是否成立？
# {NONE,SANITY,CTRL_CRC,FULL_CRC} × {random64, geomgap@8/16/24, clustered} × 5 seeds = 100 runs。
# 參數 = E7′（λ=3e-3、order 253、1M keys、EVERY_READ、budget ∞）。
#   random64 : 均勻 [0,2^63) 去重；append = max + Geom(mean 2^63/N)
#   geomgap@k: key_i = Σ Geom(mean 2^k)（g ≥ 1）；append 同分佈
#   clustered: key(idx) = (idx/1000)<<32 | idx%1000；append 接續 idx
#   miss key : [0,max_key] 均勻 draw-and-reject against ref（拒絕率 ≤ 2^-8）
# 每列附 pred_sanity_rel（規格公式）與 pred_sanity_exact（方向敏感版）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh
source scripts/e8_12_common.sh
queue_init
for dk in random64:0 geomgap:8 geomgap:16 geomgap:24 clustered:0; do
  d="${dk%%:*}"; k="${dk##*:}"
  for s in NONE SANITY CTRL_CRC FULL_CRC; do
    for sd in 1 2 3 4 5; do
      queue_run "e8db_${d}${k}_${s}_s${sd}" \
        "--scheme=$s --lambda_page=3e-3 --seed=$sd --key_dist=$d --key_stride_log2=$k \
--run_id=${s}_l0.003_s${sd}_${d}${k} $DB_COMMON"
    done
  done
done
queue_exec "$DB_BIN"
check_parts "e8db_" 100
merge_parts "e8db_" results/e8_dbscale.csv
