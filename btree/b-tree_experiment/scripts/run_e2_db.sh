#!/usr/bin/env bash
# run_e2_db.sh — E2'：DB 規模的 Policy × budget 掃描（λ = 3e-3）。
#
# 相對舊 E2 的關鍵差異——**預算刻度整體左移兩個數量級**：
#   舊世界 order=8、~1339 頁，全額保護 = 12 B × 1339 ≈ 16.1 KB，
#   有意義的預算落在 256 B – 16 KB。
#   DB 世界 order=253、~5776 頁，全額 = 12 B × 5776 ≈ 69.3 KB，但**內部節點
#   只有 ~23 頁**（h=3：root 1 + level-1 ~22 + leaf ~5753）——整個控制平面
#   上層只要 ~276 B 就能全包。因此本掃描特意把刻度往下鋪到 128 B，
#   才看得到 BY_LEVEL 的飽和點；只從 4 KB 起跳會完全錯過這個現象。
#
# 兩個 scheme 都跑：FULL_CRC（與舊 E2 逐點可比）與 CTRL_CRC（新方案）。
# 兩者 entry 皆 12 B/頁，故 budget 軸的刻度意義完全相同。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh

schemes="FULL_CRC CTRL_CRC"
policies="BY_LEVEL BY_HOTNESS LRU RANDOM"
budgets="0 128 256 512 1024 4096 16384 69312 inf"
seeds="1 2 3"

queue_init
for sc in $schemes; do
  for p in $policies; do
    for b in $budgets; do
      for sd in $seeds; do
        queue_run "e2db_${sc}_${p}_b${b}_s${sd}" \
          "--scheme=$sc --lambda_page=3e-3 --policy=$p --budget_bytes=$b --seed=$sd $DB_COMMON"
      done
    done
  done
done
queue_exec "$DB_BIN"
merge_parts "e2db_" results/e2_dbscale.csv
