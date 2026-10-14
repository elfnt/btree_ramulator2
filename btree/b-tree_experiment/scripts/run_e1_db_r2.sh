#!/usr/bin/env bash
# run_e1_db_r2.sh — E1' 的 Ramulator2（cycle-accurate DDR4）後端複本。
#
# --r2_ecc=0：SECDED 關閉，flip 直接穿透到 GuardedRAM，vulnerability 指標
# （tp/SDC/F1）才與 ram 後端可比（ECC 開啟時所有 1-bit flip 在 ecc_read()
# 就被透明修正，SDC 恆為 0——見舊 SUMMARY.md「r2 後端結果說明」）。
#
# ⚠️ 與 ram 後端的配對程度：
#   - n_flip_events **逐列相同**（注入排程由 FaultInjector 的 rng 決定，兩後端共用）
#   - 但「翻哪一個 byte/bit」由各後端內部的 rng 決定（RamulatorRAM 用
#     seed ^ 0x7a11，RAM 用 seed），**位置不配對**。
#   因此 r2 是同一實驗設計下的**獨立重複**，不是逐 flip 的配對複本；
#   兩者結論一致才算互相佐證，數字不該逐位元相同。
#
# 3 seeds（ram 後端用 5）——與舊 E1–E6 的 r2/ram 非對稱慣例相同。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh

R2_CFG="../../r2_btree_config.yaml"
if [ ! -f "$R2_CFG" ]; then
  echo "ERROR: $R2_CFG 不存在。先在 ramulator2/ 執行："
  echo "  PYTHONPATH=\$PWD/python python3 -m ramulator export r2_btree_config.py -o r2_btree_config.yaml"
  exit 1
fi

schemes="NONE SANITY HDR_CRC HDR_MIRROR CTRL_CRC FULL_CRC"
lambdas="1e-5 1e-4 3e-4 1e-3 3e-3 1e-2 3e-2"
seeds="1 2 3"

queue_init
for s in $schemes; do
  for l in $lambdas; do
    for sd in $seeds; do
      queue_run "e1r2db_${s}_l${l}_s${sd}" \
        "--backend=r2 --r2_config=$R2_CFG --r2_ecc=0 --scheme=$s --lambda_page=$l --seed=$sd $DB_COMMON"
    done
  done
done
queue_exec ./bin/exp_r2.exe
merge_parts "e1r2db_" results/e1_dbscale_r2_noecc.csv
