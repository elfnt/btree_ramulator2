#!/usr/bin/env bash
# run_e6a_db.sh — E6a'：節點密度軸，專為 CTRL_CRC 設計（λ = 3e-3、EVERY_READ、budget=∞）。
#
# 為什麼不是照抄舊 E6b：E1'–E4' 已把 order=253 / 1M keys 當成**預設條件**，
# 再跑一次同樣的 order 掃描只是重覆已知結果。E6a' 換一個只有 CTRL_CRC 才問得出
# 的問題：**control:payload 的位元組比例本身隨 order 改變，CTRL_CRC 的優勢會不會
# 因此只是 DB 規模的特例？**
#
#   leaf ：ctrl_len = 16 + n_keys*8            live_len = ctrl_len + n_keys*8
#   inter：ctrl_len = 16 + n_keys*8 + (n_keys+1)*8 = 24 + 16*n_keys（= live_len）
#   （公式出處：src/shadow_store.cpp 的 ctrl_len_of / live_len_of）
#
# 隨機插入的葉平均填充率 ≈ ln2 ≈ 0.69 × order，故 4096 B 頁的三分割是：
#   order   n_keys  ctrl(B)  values(B)  slack(B)   ctrl/(4096-16)
#   8       ~5.5      60        44       3976        1.5 %
#   32      ~22      192       176       3712        4.7 %
#   128     ~88      720       704       2656       17.6 %
#   253     ~174    1408      1392       1280       34.5 %
# → 小 order 的頁面幾乎全是「永遠不會被讀到的補零」，CTRL_CRC 的偵測面極小；
#   大 order 才逼近 50/50。本掃描用 n_corrupt_reads_* 歸因欄位直接量這個比例。
#
# 固定 200 000 keys（不是舊 E6b 的 50k）：50k 時 order=253 只有 292 頁，
# 「內部節點樂透」會完全支配 NONE 的數字；200k 給 1128 頁，統計穩定得多，
# 而最貴的一格（order 8、FULL_CRC）冒煙測試仍只要 26 s。
#
# ssd_blocks 逐 order 挑成「樹佔實體頁 ~30 %」，與 E1'（5776/16384 = 35 %）同級，
# 讓 GC 壓力在四個 order 之間可比：
#   order 8   42 283 頁 → 4096 blocks（131 072 實體頁，32 %）
#   order 32   9 526 頁 → 1024 blocks（ 32 768 實體頁，29 %）
#   order 128  2 337 頁 →  256 blocks（  8 192 實體頁，29 %）
#   order 253  1 128 頁 →  128 blocks（  4 096 實體頁，28 %）
# ram_rows_per_bank=8192（容量 65 536 頁）對四個 order 都遠大於樹 → 全常駐、
# 無自然清洗混入（與 E1'–E4' 同條件；受限 RAM 的效應由 E5' 單獨處理）。
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/db_common.sh

E6A_KEYS=200000
E6A_RPB=8192

schemes="NONE HDR_CRC CTRL_CRC FULL_CRC"
seeds="1 2 3 4 5"

# order:ssd_blocks
orders="8:4096 32:1024 128:256 253:128"

queue_init
for os in $orders; do
  o="${os%%:*}"; sb="${os##*:}"
  for s in $schemes; do
    for sd in $seeds; do
      queue_run "e6adb_o${o}_${s}_s${sd}" \
        "--scheme=$s --lambda_page=3e-3 --seed=$sd --order=$o \
--prefill_keys=$E6A_KEYS --n_ops=$DB_NOPS --ssd_blocks=$sb --ram_rows_per_bank=$E6A_RPB"
    done
  done
done
queue_exec "$DB_BIN"
merge_parts "e6adb_" results/e6a_dbscale.csv
