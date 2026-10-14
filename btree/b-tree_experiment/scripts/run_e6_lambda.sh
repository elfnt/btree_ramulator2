#!/usr/bin/env bash
# run_e6_lambda.sh <lambda> — E6: 1M keys, order=253, one lambda, 3 schemes x 3 seeds.
# Appends to results/e6_parts/e6_l<lambda>.csv using exp_fast.exe (build.sh: E6-class sweeps).
set -e
cd "$(dirname "$0")/.."
lam="$1"
mkdir -p results/e6_parts
out="results/e6_parts/e6_l${lam}.csv"
for scheme in NONE SANITY FULL_CRC; do
  for sd in 1 2 3; do
    echo "E6 lambda=$lam scheme=$scheme seed=$sd start $(date +%H:%M:%S)"
    ./bin/exp_fast.exe --scheme=$scheme --lambda_page=$lam --order=253 \
        --prefill_keys=1000000 --n_ops=30000 --ssd_blocks=512 \
        --seed=$sd --csv="$out" 2>/dev/null
    echo "E6 lambda=$lam scheme=$scheme seed=$sd done rc=$? $(date +%H:%M:%S)"
  done
done
echo "E6 lambda=$lam ALL DONE"
