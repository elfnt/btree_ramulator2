#!/usr/bin/env bash
# run_e3_db.sh — E3'：DB 規模的錯誤空間結構 × Scheme。
#
# 四種注入模式（舊 E3 只有前三種）：
#   uniform   λ=3e-3 均勻散佈（Poisson）
#   hammer    0.7 事件/s，每事件對 2 相鄰列的 1e-4 位元翻轉
#   colctrl   t=150 s 一次性欄故障，byte=128
#   colpay    t=150 s 一次性欄故障，byte=3000
#
# ── 為什麼欄故障要拆成兩個 byte 位置（舊 E3 沒有的維度）────────────────────
# 舊 E3 固定 colfault_byte=128 並下結論「欄故障固定落在 payload 區而非結構
# 欄位，所以不會 crash、只靜默毒化」。那個結論**綁死在 order=8**：
#   order=8   leaf：keys[] = byte 32..96、values[] = byte 96..160
#             → byte 128 落在 values[]（payload）
#   order=253 leaf：keys[] = byte 32..2056、values[] = byte 2056..4080
#             → byte 128 落在 keys[]（控制平面！）
# 同一個 --colfault_byte=128 在兩種密度下打的是完全不同性質的欄位，直接
# 沿用會把「密度效應」和「打到哪一區」混在一起。因此這裡明確分成
#   colctrl(byte=128)  = 控制平面欄故障 → CTRL_CRC 應該要接得住
#   colpay (byte=3000) = payload 欄故障 → CTRL_CRC 原理上看不見
# 兩者的 512 rows × 1 bit = 512 flips 完全相同，可直接對比。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh

schemes="NONE SANITY HDR_CRC HDR_MIRROR CTRL_CRC FULL_CRC"
seeds="1 2 3"

queue_init
for s in $schemes; do
  for sd in $seeds; do
    queue_run "e3db_uniform_${s}_s${sd}" \
      "--scheme=$s --lambda_page=3e-3 --seed=$sd $DB_COMMON --run_id=e3db_uniform_${s}_s${sd}"
    queue_run "e3db_hammer_${s}_s${sd}" \
      "--scheme=$s --lambda_page=0 --hammer_rate_per_s=0.7 --hammer_flip_ratio=1e-4 \
       --seed=$sd $DB_COMMON --run_id=e3db_hammer_${s}_s${sd}"
    queue_run "e3db_colctrl_${s}_s${sd}" \
      "--scheme=$s --lambda_page=0 --colfault_time_s=150 --colfault_byte=128 \
       --seed=$sd $DB_COMMON --run_id=e3db_colctrl_${s}_s${sd}"
    queue_run "e3db_colpay_${s}_s${sd}" \
      "--scheme=$s --lambda_page=0 --colfault_time_s=150 --colfault_byte=3000 \
       --seed=$sd $DB_COMMON --run_id=e3db_colpay_${s}_s${sd}"
  done
done
queue_exec "$DB_BIN"
merge_parts "e3db_" results/e3_dbscale.csv
