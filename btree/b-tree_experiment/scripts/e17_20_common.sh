#!/usr/bin/env bash
# e17_20_common.sh — E17–E20 共用：key 集合 → 旗標、平行度上限 16（機器與另一組 sweep 共用）。
# 只用 SANITY 與其免費延伸；不跑任何 CRC scheme。
source scripts/db_common.sh
source scripts/e8_12_common.sh
export DB_JOBS="${DB_JOBS:-16}"
[ "$DB_JOBS" -le 16 ] || { echo "DB_JOBS capped at 16" >&2; DB_JOBS=16; }
STD="--order=$DB_ORDER --prefill_keys=$DB_PREFILL --n_ops=$DB_NOPS --ssd_blocks=$DB_SSD_BLOCKS --ram_rows_per_bank=$DB_RPB"
SEEDS="1 2 3 4 5"
keyargs() {   # keyargs <k0|k8|k16|k32|r64>
  case "$1" in
    r64) echo "--key_dist=random64" ;;
    k*)  echo "--key_stride_log2=${1#k}" ;;
  esac
}
