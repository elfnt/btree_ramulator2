#!/usr/bin/env bash
# run_e1_db.sh — E1'：DB 規模（order 253 / 1M keys）的 Scheme × λ 掃描，budget=∞。
#
# 相對舊 E1（order 8 / 2k keys）的差異：
#   1. 規模改為真實 DB 節點密度（見 db_common.sh 的校準說明）
#   2. 新增 CTRL_CRC——本表的主角，位在 HDR_CRC 與 FULL_CRC 之間的比較點
#   3. 5 seeds（舊實驗為 3）。舊 SUMMARY.md 最大的資料品質警告就是
#      「NONE 的 wrong_undetected 逐 seed 極度離散（637/12/1）」——
#      傷害由『flip 有沒有打中熱門內部節點』的樂透決定，故多加 2 個 seed。
#   4. 每列都帶 control-vs-payload 歸因欄位（n_corrupt_reads_*）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh

schemes="NONE SANITY HDR_CRC HDR_MIRROR CTRL_CRC FULL_CRC"
lambdas="1e-5 1e-4 3e-4 1e-3 3e-3 1e-2 3e-2"
seeds="1 2 3 4 5"

queue_init
for s in $schemes; do
  for l in $lambdas; do
    for sd in $seeds; do
      queue_run "e1db_${s}_l${l}_s${sd}" \
        "--scheme=$s --lambda_page=$l --seed=$sd $DB_COMMON"
    done
  done
done
queue_exec "$DB_BIN"
merge_parts "e1db_" results/e1_dbscale.csv
