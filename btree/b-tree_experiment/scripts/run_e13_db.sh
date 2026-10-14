#!/usr/bin/env bash
# run_e13_db.sh — E13：guard key（dummy key）在資料層的上限測試。
# 參數 = E7′（λ=3e-3、order 253、1M 真 key、30 000 ops、EVERY_READ、budget ∞）。
#
# 幾何：dummy 讓樹變成 2×（right/left/mid）或 3×（both）個 entry。ssd_blocks 與
# ram_rows_per_bank 依 entry 倍數等比放大，使樹佔實體頁比例維持 ~35 %（同 E1′/E6b′
# 的作法）且 RAM 容量 > 樹頁數（全常駐、無 LRU 逐出）：
#   1×  ssd_blocks  512, rpb 2048  （16 384 實體頁；樹 ~5.8k 頁）
#   2×  ssd_blocks 1024, rpb 4096  （32 768；樹 ~11.6k 頁）
#   3×  ssd_blocks 1536, rpb 6144  （49 152；樹 ~17.4k 頁）
# 幾何敏感度：SANITY × guard=none 也在 2×/3× 跑一次（stride 32 與 random64）。
#
# Phase 0（E13_SKIP_REG=1 可略過）：新旗標皆為預設值時 stride-0 回歸檢查
#   {NONE,SANITY,FULL_CRC,CTRL_CRC} × 5 seeds → regcheck.py（不符即中止）。
#
# 矩陣（270 runs）：
#   stride k∈{8,16,32} × guard{none,right,left,both,mid} × {SANITY,CTRL_CRC} × 5 = 150
#   random64 × guard{none,right,left,both} × {SANITY,CTRL_CRC} × 5                 =  40
#   HYBRID × guard{none,right,both} × {stride 8/16/32, random64} × 5                =  60
#   SANITY × guard=none × geom{2x,3x} × {stride 32, random64} × 5                    =  20
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh
source scripts/e8_12_common.sh
DB_JOBS="${DB_JOBS:-20}"
BASE="--order=$DB_ORDER --prefill_keys=$DB_PREFILL --n_ops=$DB_NOPS --lambda_page=3e-3"
geom() {   # geom <1x|2x|3x>
  case "$1" in
    1x) echo "--ssd_blocks=512 --ram_rows_per_bank=2048" ;;
    2x) echo "--ssd_blocks=1024 --ram_rows_per_bank=4096" ;;
    3x) echo "--ssd_blocks=1536 --ram_rows_per_bank=6144" ;;
  esac
}
geom_of_guard() { case "$1" in none) echo 1x ;; both) echo 3x ;; *) echo 2x ;; esac; }
seeds="1 2 3 4 5"

if [ "${E13_SKIP_REG:-0}" != "1" ]; then
  queue_init
  for s in NONE SANITY FULL_CRC CTRL_CRC; do
    for sd in $seeds; do
      queue_run "e13reg_${s}_s${sd}" "--scheme=$s --seed=$sd --run_id=${s}_l0.003_s${sd}_k0 $BASE $(geom 1x)"
    done
  done
  queue_exec "$DB_BIN"
  check_parts "e13reg_" 20
  merge_parts "e13reg_" results/dbscale/e13_regcheck.csv
  python3 scripts/regcheck.py results/dbscale/e13_regcheck.csv
fi

queue_init
n=0
add() {  # add <tag> <args>
  queue_run "e13db_$1" "$2"; n=$((n+1))
}
for k in 8 16 32; do
  for g in none right left both mid; do
    for s in SANITY CTRL_CRC; do
      for sd in $seeds; do
        add "k${k}_${g}_${s}_s${sd}" "--scheme=$s --seed=$sd --key_stride_log2=$k --guard=$g \
--run_id=${s}_l0.003_s${sd}_k${k}_g${g} $BASE $(geom $(geom_of_guard $g))"
      done
    done
  done
done
for g in none right left both; do
  for s in SANITY CTRL_CRC; do
    for sd in $seeds; do
      add "r64_${g}_${s}_s${sd}" "--scheme=$s --seed=$sd --key_dist=random64 --guard=$g \
--run_id=${s}_l0.003_s${sd}_random640_g${g} $BASE $(geom $(geom_of_guard $g))"
    done
  done
done
for g in none right both; do
  for d in k8 k16 k32 r64; do
    case $d in r64) kd="--key_dist=random64"; rid=random640 ;; *) kd="--key_stride_log2=${d#k}"; rid=$d ;; esac
    for sd in $seeds; do
      add "${d}_${g}_HYBRID_s${sd}" "--scheme=HYBRID --seed=$sd $kd --guard=$g \
--run_id=HYBRID_l0.003_s${sd}_${rid}_g${g} $BASE $(geom $(geom_of_guard $g))"
    done
  done
done
for gm in 2x 3x; do
  for d in k32 r64; do
    case $d in r64) kd="--key_dist=random64"; rid=random640 ;; *) kd="--key_stride_log2=32"; rid=k32 ;; esac
    for sd in $seeds; do
      add "geo${gm}_${d}_none_SANITY_s${sd}" "--scheme=SANITY --seed=$sd $kd --guard=none \
--run_id=SANITY_l0.003_s${sd}_${rid}_gnone_geo${gm} $BASE $(geom $gm)"
    done
  done
done
echo "queued $n runs"
queue_exec "$DB_BIN"
check_parts "e13db_" 270
merge_parts "e13db_" results/e13_dbscale.csv
