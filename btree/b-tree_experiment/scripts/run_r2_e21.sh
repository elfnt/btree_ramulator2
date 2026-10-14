#!/usr/bin/env bash
# run_r2_e21.sh — E21（key 映射）以 Ramulator2 重跑，矩陣同 run_e21_db.sh：
#   random64 × hashdense α{0.25,0.5,0.75} × {SANITY,NONE} × 5 = 30
#   stride 2^32 × hashdense α=0.5 × SANITY × 5 = 5 ； stride 2^32 × shift × SANITY × 5 = 5
# 使用 bin/exp_r2.exe（已含 E21 的 key 映射）。
set -uo pipefail
cd "$(dirname "$0")/.."
R2_CFG="../../r2_btree_config.yaml"
BIN="${R2_BIN:-./bin/exp_r2.exe}"; R2="--backend=r2 --r2_config=$R2_CFG --r2_ecc=0"
BASE="--lambda_page=3e-3 --order=253 --prefill_keys=1000000 --n_ops=30000"
G1="--ssd_blocks=512 --ram_rows_per_bank=2048"; G2="--ssd_blocks=1024 --ram_rows_per_bank=4096"
PARTS=results/dbscale/parts_r2; OUT=results/r2; JOBS="${R2_JOBS:-2}"
mkdir -p "$PARTS" "$OUT" logs; export PARTS R2 BIN
J=$(mktemp); q() { printf '%s|%s\n' "$1" "$2" >> "$J"; }
for a in 0.25 0.5 0.75; do for s in SANITY NONE; do for sd in 1 2 3 4 5; do
  q "e21r2_r64_hd${a}_${s}_s${sd}" "--scheme=$s --seed=$sd --key_dist=random64 --key_map=hashdense --map_load=$a --run_id=${s}_l0.003_s${sd}_random640_hd${a} $BASE $G2"
done; done; done
for sd in 1 2 3 4 5; do
  q "e21r2_k32_hd0.5_SANITY_s${sd}" "--scheme=SANITY --seed=$sd --key_stride_log2=32 --key_map=hashdense --map_load=0.5 --run_id=SANITY_l0.003_s${sd}_k32_hd0.5 $BASE $G2"
  q "e21r2_k32_shift_SANITY_s${sd}" "--scheme=SANITY --seed=$sd --key_stride_log2=32 --key_map=shift --run_id=SANITY_l0.003_s${sd}_k32_shift $BASE $G1"
done
echo "queued $(wc -l < "$J") runs, $JOBS parallel, started $(date '+%F %T')"
xargs -d '\n' -P "$JOBS" -I{} bash -c '
  entry="{}"; tag="${entry%%|*}"; args="${entry#*|}"; out="$PARTS/${tag}.csv"
  if [ -s "$out" ] && [ "$(wc -l < "$out")" -ge 2 ]; then exit 0; fi
  rm -f "$out"
  if $BIN $R2 $args --csv="$out" 2> "logs/r2_${tag}.log"; then echo "ok $tag"; else rm -f "$out"; echo "FAILED $tag" >&2; fi
' < "$J"; rm -f "$J"
first=1; out="$OUT/e21_r2.csv"; rm -f "$out"
for f in "$PARTS"/e21r2_*.csv; do [ -e "$f" ] || continue
  if [ $first -eq 1 ]; then cat "$f" > "$out"; first=0; else tail -n +2 "$f" >> "$out"; fi; done
echo "finished $(date '+%F %T')"; echo "$out $(( $(wc -l < "$out") - 1 )) / 40 rows"
