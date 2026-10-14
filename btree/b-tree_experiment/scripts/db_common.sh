#!/usr/bin/env bash
# db_common.sh — DB-realistic-scale (E1'–E4') 掃描的共用設定與平行執行器。
# 由 run_e{1,2,3,4}_db.sh source 進來；本身不獨立執行。
#
# ── 為什麼是這組規模參數（校準依據見 results/SUMMARY_dbscale.md「校準」節）──
#   order=253          4096 B 頁 + 8 B key/value 下接近塞得滿的最大 order
#                      （internal: 32 + 253*8 + 254*8 = 4088 B ≤ 4096），
#                      沿用舊 E6 的真實 DB 節點密度錨點。
#   prefill_keys=1e6   舊 E6 已驗證可行；樹 ≈ 5776 頁、h=3。
#   n_ops=30000        與 E1–E6 全部歷史實驗相同，橫向可比；
#                      dt_op=0.01 s → horizon 300 模擬秒（E4' 的 θ 需遠小於此）。
#   ssd_blocks=512     16384 實體頁，樹佔 ~35 % → GC 全程活躍（舊 E6 同組態）。
#   ram_rows_per_bank=2048
#                      ⚠️ 必須顯式給定。不給時兩後端的 DRAM 容量差 8 倍：
#                        ram 後端 rows_per_bank = ssd_blocks*ppb/8 = 2048，
#                                  容量 = DRAM_NUM_BANKS(8) × 2048 = 16384 頁
#                        r2  後端 cap_pages     = ssd_blocks*ppb/8 = 2048 頁
#                      顯式給定後兩者皆為 8 × 2048 = 16384 頁，樹（5776 頁）
#                      全常駐、無 LRU 逐出、無「自然清洗」混入——與舊 E6 一致。
#
# ── 平行化 ────────────────────────────────────────────────────────────────────
# 每個 run 寫進自己的 part CSV（driver 以 append 寫檔，並行 append 會交錯），
# 全部跑完後由 merge_parts 併成單一檔並去掉重複 header。

set -euo pipefail

DB_ORDER=253
DB_PREFILL=1000000
DB_NOPS=30000
DB_SSD_BLOCKS=512
DB_RPB=2048

DB_COMMON="--order=$DB_ORDER --prefill_keys=$DB_PREFILL --n_ops=$DB_NOPS \
--ssd_blocks=$DB_SSD_BLOCKS --ram_rows_per_bank=$DB_RPB"

# exp_fast.exe：-DNDEBUG，與 exp.exe 對同組態產出逐欄相同的 CSV 列
# （SUMMARY_dbscale.md「資料品質檢查」有 1M 規模的實測驗證）。
DB_BIN=./bin/exp_fast.exe
DB_JOBS="${DB_JOBS:-24}"

PARTS_DIR=results/dbscale/parts

# queue_run <part_tag> <args...> — 把一條指令排進待執行清單
JOBFILE=""
queue_init() { JOBFILE=$(mktemp); }
queue_run() {
  local tag="$1"; shift
  printf '%s\0' "$tag|$*" >> "$JOBFILE"
}

# queue_exec <bin> — 以 DB_JOBS 路平行跑完佇列
queue_exec() {
  local bin="$1"
  mkdir -p "$PARTS_DIR" logs
  tr '\0' '\n' < "$JOBFILE" | xargs -d '\n' -P "$DB_JOBS" -I{} bash -c '
    entry="{}"
    tag="${entry%%|*}"
    args="${entry#*|}"
    out="'"$PARTS_DIR"'/${tag}.csv"
    rm -f "$out"
    if ! '"$bin"' $args --csv="$out" 2> "logs/db_${tag}.log"; then
      echo "FAILED: $tag" >&2
      exit 1
    fi
    echo "ok $tag"
  '
  rm -f "$JOBFILE"
}

# merge_parts <glob_prefix> <out_csv> — 併 part CSV（保留單一 header）
merge_parts() {
  local prefix="$1" out="$2"
  local first=1
  rm -f "$out"
  for f in "$PARTS_DIR"/${prefix}*.csv; do
    [ -e "$f" ] || continue
    if [ $first -eq 1 ]; then cat "$f" > "$out"; first=0
    else tail -n +2 "$f" >> "$out"; fi
  done
  echo "merged -> $out ($(( $(wc -l < "$out") - 1 )) rows)"
}
