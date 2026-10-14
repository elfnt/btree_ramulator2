#!/usr/bin/env bash
set -e; cd "$(dirname "$0")/.."
P=results/dbscale/parts; export P; mkdir -p "$P" logs
R(){ local tag=$1; shift
     ./bin/exp_fast.exe --scheme=CTRL_CRC "$@" --csv="$P/v2_${tag}.csv" 2>/dev/null; }
export -f R
{
for l in 1e-5 1e-4 3e-4 1e-3 3e-3 1e-2 3e-2; do for s in 1 2 3 4 5; do
  echo "e1_l${l}_s$s --lambda_page=$l --seed=$s --order=253 --prefill_keys=1000000 --n_ops=30000 --ssd_blocks=512 --ram_rows_per_bank=2048"; done; done
for r in 2048 720 512 256 128 64 32; do for s in 1 2 3 4 5; do
  echo "e5_r${r}_s$s --lambda_page=3e-3 --seed=$s --order=253 --prefill_keys=1000000 --n_ops=30000 --ssd_blocks=512 --ram_rows_per_bank=$r"; done; done
for ob in 8:4096 32:1024 128:256 253:128; do IFS=: read o b <<< "$ob"; for s in 1 2 3 4 5; do
  echo "e6a_o${o}_s$s --lambda_page=3e-3 --seed=$s --order=$o --prefill_keys=200000 --n_ops=30000 --ssd_blocks=$b --ram_rows_per_bank=8192"; done; done
for k in 200000:128:1024 1000000:512:2048 3000000:2048:4096 5000000:4096:8192; do IFS=: read n b r <<< "$k"; for s in 1 2 3 4 5; do
  echo "e6b_k${n}_s$s --lambda_page=3e-3 --seed=$s --order=253 --prefill_keys=$n --n_ops=30000 --ssd_blocks=$b --ram_rows_per_bank=$r"; done; done
for k in 0 8 16 24 32; do for s in 1 2 3 4 5; do
  echo "e7_k${k}_s$s --lambda_page=3e-3 --seed=$s --order=253 --prefill_keys=1000000 --n_ops=30000 --ssd_blocks=512 --ram_rows_per_bank=2048 --key_stride_log2=$k"; done; done
} | xargs -P 20 -I{} bash -c 'R {}'
echo "rerun done: $(ls $P/v2_*.csv | wc -l)"
