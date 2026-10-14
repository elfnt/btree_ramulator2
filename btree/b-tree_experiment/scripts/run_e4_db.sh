#!/usr/bin/env bash
# run_e4_db.sh — E4'：DB 規模的驗證頻率（EVERY_READ vs PERIODIC θ）。
#
# 舊 E4 只跑 FULL_CRC。這裡加入 CTRL_CRC，因為兩者的**每次驗證成本結構不同**：
#   FULL_CRC 每次驗證固定 4096 B 的 CRC
#   CTRL_CRC 每次驗證 ctrl_len B——leaf ≈ 16+253*8 = 2040 B、
#            internal ≈ 4088 B，平均約半頁
# 問題：既然 CTRL_CRC 每次驗證便宜約一半，放寬 θ 換到的延遲紅利是否也減半、
# 膝點會不會往左移（更早就不值得放寬）？
#
# horizon = n_ops × dt_op = 30000 × 0.01 = 300 模擬秒；θ 全部遠小於此，
# 否則 PERIODIC 整場零驗證（見 exp_config.hpp theta_s 註記）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh

schemes="CTRL_CRC FULL_CRC"
thetas="0.1 0.3 1 3 10 30 100"
seeds="1 2 3"

queue_init
for sc in $schemes; do
  for sd in $seeds; do
    queue_run "e4db_${sc}_er_s${sd}" \
      "--scheme=$sc --lambda_page=3e-3 --verify_mode=EVERY_READ --seed=$sd $DB_COMMON"
    for th in $thetas; do
      queue_run "e4db_${sc}_p${th}_s${sd}" \
        "--scheme=$sc --lambda_page=3e-3 --verify_mode=PERIODIC --theta_s=$th --seed=$sd $DB_COMMON"
    done
  done
done
queue_exec "$DB_BIN"
merge_parts "e4db_" results/e4_dbscale.csv
