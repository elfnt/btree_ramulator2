#!/usr/bin/env bash
set -e; cd "$(dirname "$0")/.."
P=results/dbscale/parts;
export P; mkdir -p "$P" logs
run(){ ./bin/exp_fast.exe --scheme=$1 --sanity_always=$2 --lambda_page=$3 --seed=$4 \
  --order=253 --prefill_keys=1000000 --n_ops=30000 --ssd_blocks=512 --ram_rows_per_bank=2048 \
  --csv="$P/cb_$1_sa$2_l$3_s$4.csv" 2> "logs/cb_$1_$2_$3_$4.log"; }
export -f run
for lam in 1e-3 3e-3 1e-2 3e-2; do for sd in 1 2 3; do
  echo "CTRL_CRC 1 $lam $sd"; echo "SANITY 0 $lam $sd"; echo "CTRL_CRC 0 $lam $sd"
done; done | xargs -P 12 -n 4 bash -c 'run "$0" "$1" "$2" "$3"'
O=results/e_combo.csv; head -1 "$P"/cb_CTRL_CRC_sa1_l1e-3_s1.csv > "$O"
for f in "$P"/cb_*.csv; do tail -n +2 "$f" >> "$O"; done
echo "combo done: $(wc -l < $O)"
