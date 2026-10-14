#!/usr/bin/env bash
# run_e22_db.sh — E22：stride-2^32 key 的空隙以固定 2^k 網格填滿 dummy（--guard=grid）。
# 參數 = E7′/E13（λ=3e-3、order 253、1M 真 key、30 000 ops、EVERY_READ、budget ∞）。
# 每個真 key K 插入 dummy K + j·2^k（j = 1 … 2^(32−k) − 1），路徑/sentinel/主迴圈同 --guard=mid。
#   k = 31 → 1 dummy（= E13 mid；Phase 0b 逐欄回歸），k = 30 → 3，k = 29 → 7。
# 幾何依 entry 倍數（dummies+1）等比放大，樹佔 SSD ~35 % 且全常駐：
#   1× 512/2048   2× 1024/4096   4× 2048/8192   8× 4096/16384  （ssd_blocks / ram_rows_per_bank）
#
# Phase 0a（E22_SKIP_REG=1 略過）：新旗標皆預設時 stride-0 回歸（regcheck.py vs e7）。
# Phase 0b：grid k=31 × {SANITY,CTRL_CRC} × 5 seeds（2×）vs e13 guard=mid（e22_regcheck.py）。
# 矩陣（40 runs → results/e22_dbscale.csv）：
#   stride 32 × k∈{30,29} × {NONE,SANITY,CTRL_CRC} × 5 seeds = 30
#   SANITY × guard=none × geom{4x,8x} × 5 seeds              = 10（幾何敏感度對照）
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh
source scripts/e8_12_common.sh
export DB_JOBS="${DB_JOBS:-16}"
[ "$DB_JOBS" -gt 16 ] && DB_JOBS=16
export PARTS_DIR DB_BIN
BASE="--order=$DB_ORDER --prefill_keys=$DB_PREFILL --n_ops=$DB_NOPS --lambda_page=3e-3"
export BASE
geom() {   # geom <1x|2x|4x|8x>
  case "$1" in
    1x) echo "--ssd_blocks=512 --ram_rows_per_bank=2048" ;;
    2x) echo "--ssd_blocks=1024 --ram_rows_per_bank=4096" ;;
    4x) echo "--ssd_blocks=2048 --ram_rows_per_bank=8192" ;;
    8x) echo "--ssd_blocks=4096 --ram_rows_per_bank=16384" ;;
  esac
}
geom_of_k() { case "$1" in 31) echo 2x ;; 30) echo 4x ;; 29) echo 8x ;; esac; }
seeds="${E22_SEEDS:-1 2 3 4 5}"
seeds29="${E22_SEEDS29:-$seeds}"

if [ "${E22_SKIP_REG:-0}" != "1" ]; then
  rm -f "$PARTS_DIR"/e22reg_*.csv "$PARTS_DIR"/e22mid_*.csv
  queue_init
  for s in NONE SANITY FULL_CRC CTRL_CRC; do
    for sd in 1 2 3 4 5; do
      queue_run "e22reg_${s}_s${sd}" "--scheme=$s --seed=$sd --run_id=${s}_l0.003_s${sd}_k0 $BASE $(geom 1x)"
    done
  done
  for s in SANITY CTRL_CRC; do
    for sd in 1 2 3 4 5; do
      queue_run "e22mid_${s}_s${sd}" "--scheme=$s --seed=$sd --key_stride_log2=32 --guard=grid --guard_grid_log2=31 \
--run_id=${s}_l0.003_s${sd}_k32_ggrid31 $BASE $(geom 2x)"
    done
  done
  queue_exec "$DB_BIN"
  check_parts "e22reg_" 20
  check_parts "e22mid_" 10
  merge_parts "e22reg_" results/dbscale/e22_regcheck.csv
  merge_parts "e22mid_" results/dbscale/e22_regcheck_mid.csv
  python3 scripts/regcheck.py results/dbscale/e22_regcheck.csv
  python3 scripts/e22_regcheck.py results/dbscale/e22_regcheck_mid.csv
fi

rm -f "$PARTS_DIR"/e22db_*.csv
queue_init
n=0
add() { queue_run "e22db_$1" "$2"; n=$((n+1)); }
# 最貴的 8× 先排，縮短尾端
for k in 29 30; do
  ss=$seeds; [ "$k" = 29 ] && ss=$seeds29
  for s in CTRL_CRC SANITY NONE; do
    for sd in $ss; do
      add "k${k}_${s}_s${sd}" "--scheme=$s --seed=$sd --key_stride_log2=32 --guard=grid --guard_grid_log2=$k \
--run_id=${s}_l0.003_s${sd}_k32_ggrid${k} $BASE $(geom $(geom_of_k $k))"
    done
  done
done
for gm in 8x 4x; do
  for sd in $seeds; do
    add "geo${gm}_none_SANITY_s${sd}" "--scheme=SANITY --seed=$sd --key_stride_log2=32 --guard=none \
--run_id=SANITY_l0.003_s${sd}_k32_gnone_geo${gm} $BASE $(geom $gm)"
  done
done
echo "queued $n runs"
queue_exec "$DB_BIN"
check_parts "e22db_" "$n"
merge_parts "e22db_" results/e22_dbscale.csv
python3 scripts/e22_regcheck.py results/dbscale/e22_regcheck_mid.csv \
  <(python3 -c "import csv,sys;r=list(csv.DictReader(open('results/e22_dbscale.csv')));w=csv.DictWriter(sys.stdout,r[0].keys());w.writeheader();[w.writerow(x) for x in r if x['guard']=='none']") || true
