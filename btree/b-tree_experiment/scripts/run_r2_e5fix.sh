#!/usr/bin/env bash
# run_r2_e5fix.sh — E5（DRAM 容量）以 Ramulator2 重跑，使用 bin/exp_r2.exe（GuardedRAM 已含 r2 miss 時補 t_ssd 的修正）。
# 原因：RamulatorRAM::read 在 DRAM miss 時從 SSD 重載，但回傳延遲只含 DDR4 讀取；ram 後端會另加 t_ssd。
#       修正位於 GuardedRAM::read（只在 backend=r2 且 miss 時加 t_ssd），只影響延遲欄位。
# 舊的（未計 miss 延遲）結果保存在 results/dbscale/parts_r2_e5_nomisslat/。
set -uo pipefail
cd "$(dirname "$0")/.."
R2_CFG="../../r2_btree_config.yaml"
BIN="${R2_BIN:-./bin/exp_r2.exe}"; R2="--backend=r2 --r2_config=$R2_CFG --r2_ecc=0"
PARTS=results/dbscale/parts_r2; OUT=results/r2; JOBS="${R2_JOBS:-10}"
mkdir -p "$PARTS" "$OUT" logs; export PARTS R2 BIN
J=$(mktemp)
for s in NONE SANITY CTRL_CRC FULL_CRC; do for rpb in 2048 720 512 256 128 64 32; do for sd in 1 2 3 4 5; do
  printf '%s|%s\n' "e5r2_${s}_rpb${rpb}_s${sd}" "--scheme=$s --lambda_page=3e-3 --seed=$sd --order=253 --prefill_keys=1000000 --n_ops=30000 --ssd_blocks=512 --ram_rows_per_bank=$rpb" >> "$J"
done; done; done
echo "queued $(wc -l < "$J") runs, $JOBS parallel, started $(date '+%F %T')"
xargs -d '\n' -P "$JOBS" -I{} bash -c '
  entry="{}"; tag="${entry%%|*}"; args="${entry#*|}"; out="$PARTS/${tag}.csv"
  if [ -s "$out" ] && [ "$(wc -l < "$out")" -ge 2 ]; then exit 0; fi
  rm -f "$out"
  if $BIN $R2 $args --csv="$out" 2> "logs/r2_${tag}.log"; then echo "ok $tag"; else rm -f "$out"; echo "FAILED $tag" >&2; fi
' < "$J"; rm -f "$J"
first=1; out="$OUT/e5_r2.csv"; rm -f "$out"
for f in "$PARTS"/e5r2_*.csv; do [ -e "$f" ] || continue
  if [ $first -eq 1 ]; then cat "$f" > "$out"; first=0; else tail -n +2 "$f" >> "$out"; fi; done
echo "finished $(date '+%F %T')"; echo "$out $(( $(wc -l < "$out") - 1 )) / 140 rows"
