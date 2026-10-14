#!/usr/bin/env bash
# e8_12_common.sh — E8–E12 共用：part 數量檢查（防止 part 靜默缺漏後才合併）
check_parts() {   # check_parts <prefix> <expected>
  local n
  n=$(ls "$PARTS_DIR"/${1}*.csv 2>/dev/null | wc -l)
  if [ "$n" -ne "$2" ]; then
    echo "ERROR: $1 parts = $n, expected $2" >&2; exit 1
  fi
  echo "parts ok: $1 = $n"
}
