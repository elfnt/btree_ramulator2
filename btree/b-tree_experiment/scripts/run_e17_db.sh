#!/usr/bin/env bash
# run_e17_db.sh — E17：parent–child 範圍檢查（--sanity_range=1）。
# Phase 0（E17_SKIP_REG=1 可略過）：新旗標皆預設、stride 0，NONE/SANITY × 5 seeds → regcheck.py。
# 主矩陣：{SANITY, SANITY+range} × keys {k0,k16,k32,r64} × inject {all λ3e-3, internal λ0.15, leaf λ3e-3} × 5 = 120
# 小節點：order 16、200k keys（E9 幾何：ssd_blocks 2048、rpb 8192）× {SANITY, +range} × {k0,k16} × 3 = 12
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/e17_20_common.sh

if [ "${E17_SKIP_REG:-0}" != "1" ]; then
  queue_init
  for s in NONE SANITY; do for sd in $SEEDS; do
    queue_run "e17reg_${s}_s${sd}" "--scheme=$s --seed=$sd --run_id=${s}_l0.003_s${sd}_k0 $STD --lambda_page=3e-3"
  done; done
  queue_exec "$DB_BIN"
  check_parts "e17reg_" 10
  merge_parts "e17reg_" results/dbscale/e17_regcheck.csv
  python3 scripts/regcheck.py results/dbscale/e17_regcheck.csv
fi

queue_init
for il in all:3e-3 internal:0.15 leaf:3e-3; do
  lv="${il%%:*}"; lam="${il##*:}"
  for d in k0 k16 k32 r64; do
    for rg in 0 1; do
      for sd in $SEEDS; do
        queue_run "e17db_${lv}_${d}_r${rg}_s${sd}" "--scheme=SANITY --sanity_range=$rg --seed=$sd $(keyargs $d) \
--inject_level=$lv --lambda_page=$lam --run_id=SANITY_r${rg}_${lv}_l${lam}_s${sd}_${d} $STD"
      done
    done
  done
done
for d in k0 k16; do
  for rg in 0 1; do
    for sd in 1 2 3; do
      queue_run "e17db_o16_${d}_r${rg}_s${sd}" "--scheme=SANITY --sanity_range=$rg --seed=$sd $(keyargs $d) \
--order=16 --prefill_keys=200000 --n_ops=$DB_NOPS --ssd_blocks=2048 --ram_rows_per_bank=8192 --lambda_page=3e-3 \
--run_id=SANITY_r${rg}_o16_l0.003_s${sd}_${d}"
    done
  done
done
queue_exec "$DB_BIN"
check_parts "e17db_" 132
merge_parts "e17db_" results/e17_dbscale.csv
