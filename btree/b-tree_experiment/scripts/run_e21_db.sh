#!/usr/bin/env bash
# run_e21_db.sh — E21：把稀疏 key 映射到小而稠密的範圍，讓 SANITY 的排序檢查重新有效。
# 參數 = E7′/E8（λ=3e-3、order 253、1M key、30 000 ops、EVERY_READ、budget ∞）。只有 SANITY / NONE。
#
# Phase 0（E21_SKIP_REG=1 可略過）：--key_map=none 的回歸
#   stride-0 {NONE,SANITY} × 5 seeds → regcheck.py（對 e7_dbscale.csv）
#   random64 SANITY seed 1 → 逐欄比對 e8_dbscale.csv
# 矩陣（40 runs）：
#   random64 × hashdense α∈{0.25,0.5,0.75} × {SANITY,NONE} × 5   = 30（2× 幾何）
#   stride 32 × hashdense α=0.5 × SANITY × 5                     =  5（2× 幾何）
#   stride 32 × shift × SANITY × 5                               =  5（1× 幾何；對照 e10 stride-0 SANITY）
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh
source scripts/e8_12_common.sh
DB_JOBS="${DB_JOBS:-14}"          # 與另一個 agent 共用 32 核：上限 14
BASE="--order=$DB_ORDER --prefill_keys=$DB_PREFILL --n_ops=$DB_NOPS --lambda_page=3e-3"
G1="--ssd_blocks=512 --ram_rows_per_bank=2048"
G2="--ssd_blocks=1024 --ram_rows_per_bank=4096"
seeds="1 2 3 4 5"

if [ "${E21_SKIP_REG:-0}" != "1" ]; then
  queue_init
  for s in NONE SANITY; do
    for sd in $seeds; do
      queue_run "e21reg_${s}_s${sd}" "--scheme=$s --seed=$sd --run_id=${s}_l0.003_s${sd}_k0 $BASE $G1"
    done
  done
  queue_run "e21reg_r64_SANITY_s1" "--scheme=SANITY --seed=1 --key_dist=random64 --run_id=SANITY_l0.003_s1_random640 $BASE $G1"
  queue_exec "$DB_BIN"
  check_parts "e21reg_" 11
  merge_parts "e21reg_" results/dbscale/e21_regcheck.csv
  python3 scripts/regcheck.py results/dbscale/e21_regcheck.csv
  python3 - <<'EOF'
import csv, sys
ref = [r for r in csv.DictReader(open('results/e8_dbscale.csv'))
       if r['key_dist'] == 'random64' and r['scheme'] == 'SANITY' and r['seed'] == '1']
new = [r for r in csv.DictReader(open('results/dbscale/e21_regcheck.csv')) if r['key_dist'] == 'random64']
assert len(ref) == 1 and len(new) == 1
diff = [c for c in ref[0] if ref[0][c] != new[0].get(c)]
print(f"random64 SANITY s1 vs e8: {len(ref[0])} cols, {len(diff)} differ {diff[:8]}")
sys.exit(1 if diff else 0)
EOF
fi

queue_init
n=0
add() { queue_run "e21db_$1" "$2"; n=$((n+1)); }
for a in 0.25 0.5 0.75; do
  for s in SANITY NONE; do
    for sd in $seeds; do
      add "r64_hd${a}_${s}_s${sd}" "--scheme=$s --seed=$sd --key_dist=random64 --key_map=hashdense --map_load=$a \
--run_id=${s}_l0.003_s${sd}_random640_hd${a} $BASE $G2"
    done
  done
done
for sd in $seeds; do
  add "k32_hd0.5_SANITY_s${sd}" "--scheme=SANITY --seed=$sd --key_stride_log2=32 --key_map=hashdense --map_load=0.5 \
--run_id=SANITY_l0.003_s${sd}_k32_hd0.5 $BASE $G2"
  add "k32_shift_SANITY_s${sd}" "--scheme=SANITY --seed=$sd --key_stride_log2=32 --key_map=shift \
--run_id=SANITY_l0.003_s${sd}_k32_shift $BASE $G1"
done
echo "queued $n runs"
queue_exec "$DB_BIN"
check_parts "e21db_" 40
merge_parts "e21db_" results/e21_dbscale.csv
