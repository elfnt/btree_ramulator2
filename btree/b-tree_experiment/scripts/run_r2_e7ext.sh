#!/usr/bin/env bash
# run_r2_e7ext.sh — §4.8（提高 key 密度）中能在主程式碼跑的那幾組，改用 Ramulator2 重跑。
#   E13：stride 2^32 × guard{none,mid,right,both} × {SANITY,CTRL_CRC} × 5，加 random64 guard=none × 2 × 5
#   E22：stride 2^32 × grid k{30,29} × {NONE,SANITY,CTRL_CRC} × 5
# 參數、幾何、seeds 同 run_e13_db.sh / run_e22_db.sh。hash 映射（E21）的程式碼未合併進主程式，不在此重跑。
set -uo pipefail
cd "$(dirname "$0")/.."
R2_CFG="../../r2_btree_config.yaml"
R2="--backend=r2 --r2_config=$R2_CFG --r2_ecc=0"
BASE="--lambda_page=3e-3 --order=253 --prefill_keys=1000000 --n_ops=30000"
PARTS=results/dbscale/parts_r2; OUT=results/r2; JOBS="${R2_JOBS:-6}"
mkdir -p "$PARTS" "$OUT" logs; export PARTS R2
geom() { case "$1" in 1x) echo "--ssd_blocks=512 --ram_rows_per_bank=2048";; 2x) echo "--ssd_blocks=1024 --ram_rows_per_bank=4096";;
  3x) echo "--ssd_blocks=1536 --ram_rows_per_bank=6144";; 4x) echo "--ssd_blocks=2048 --ram_rows_per_bank=8192";;
  8x) echo "--ssd_blocks=4096 --ram_rows_per_bank=16384";; esac; }
J=$(mktemp); q() { printf '%s|%s\n' "$1" "$2" >> "$J"; }
for k in 29 30; do g=$([ $k = 29 ] && echo 8x || echo 4x)
  for s in CTRL_CRC SANITY NONE; do for sd in 1 2 3 4 5; do
    q "e22r2_k${k}_${s}_s${sd}" "--scheme=$s --seed=$sd --key_stride_log2=32 --guard=grid --guard_grid_log2=$k $BASE $(geom $g)"
  done; done; done
for gd in both mid right none; do g=$(case $gd in none) echo 1x;; both) echo 3x;; *) echo 2x;; esac)
  for s in SANITY CTRL_CRC; do for sd in 1 2 3 4 5; do
    q "e13r2_k32_${gd}_${s}_s${sd}" "--scheme=$s --seed=$sd --key_stride_log2=32 --guard=$gd --run_id=${s}_l0.003_s${sd}_k32_g${gd} $BASE $(geom $g)"
  done; done; done
for s in SANITY CTRL_CRC; do for sd in 1 2 3 4 5; do
  q "e13r2_r64_none_${s}_s${sd}" "--scheme=$s --seed=$sd --key_dist=random64 --guard=none --run_id=${s}_l0.003_s${sd}_r64_gnone $BASE $(geom 1x)"
done; done
echo "queued $(wc -l < "$J") runs, $JOBS parallel, started $(date '+%F %T')"
xargs -d '\n' -P "$JOBS" -I{} bash -c '
  entry="{}"; tag="${entry%%|*}"; args="${entry#*|}"; out="$PARTS/${tag}.csv"
  if [ -s "$out" ] && [ "$(wc -l < "$out")" -ge 2 ]; then exit 0; fi
  rm -f "$out"
  if ./bin/exp_r2.exe $R2 $args --csv="$out" 2> "logs/r2_${tag}.log"; then echo "ok $tag"; else rm -f "$out"; echo "FAILED $tag" >&2; fi
' < "$J"; rm -f "$J"
merge() { local prefix="$1" out="$2" want="$3" first=1; rm -f "$out"
  for f in "$PARTS"/${prefix}*.csv; do [ -e "$f" ] || continue
    if [ $first -eq 1 ]; then cat "$f" > "$out"; first=0; else tail -n +2 "$f" >> "$out"; fi; done
  local got=0; [ -f "$out" ] && got=$(( $(wc -l < "$out") - 1 ))
  printf '%-22s %4d / %4d rows %s\n' "$out" "$got" "$want" "$([ "$got" -eq "$want" ] && echo OK || echo INCOMPLETE)"; }
echo "finished $(date '+%F %T')"
merge e13r2_ "$OUT/e13_r2.csv" 50
merge e22r2_ "$OUT/e22_r2.csv" 30
