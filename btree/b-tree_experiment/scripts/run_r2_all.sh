#!/usr/bin/env bash
# run_r2_all.sh — 以 Ramulator2（cycle-accurate DDR4-2400，ECC off）後端重跑 E1–E7 全部矩陣。
#
# 與 ram 後端的原始腳本（run_e*_db.sh）使用相同的參數、seeds 與規模，差別只有：
#   - 執行檔 bin/exp_r2.exe，加上 --backend=r2 --r2_config=... --r2_ecc=0
#   - 不跑 HDR_CRC / HDR_MIRROR（論文已排除）
#   - CTRL_CRC 為目前程式碼的版本（涵蓋 SSD header）
#   - 結果寫到 results/r2/e*_r2.csv，不覆蓋 ram 後端的資料
#
# 可中斷續跑：part CSV 已存在且含資料列的 run 會被跳過。
# 用法：bash scripts/run_r2_all.sh            # 全部
#       R2_JOBS=20 bash scripts/run_r2_all.sh  # 調整平行數
#       R2_SKIP='^e2[de]r2_' R2_JOBS=16 bash scripts/run_r2_all.sh   # 輕量實驗
#       R2_ONLY='^e2dr2_'    R2_JOBS=5  bash scripts/run_r2_all.sh   # E2d（每 run ~2.2 GB）
# ⚠️ 記憶體：E2d 每 run 約 2.2 GB、E2e 更大。24 路全開曾把 59 GB 吃滿而 swap 失速。
set -uo pipefail
cd "$(dirname "$0")/.."

R2_CFG="../../r2_btree_config.yaml"
[ -f "$R2_CFG" ] || { echo "ERROR: r2 config not found" >&2; exit 1; }
[ -x bin/exp_r2.exe ] || { echo "ERROR: bin/exp_r2.exe missing (bash scripts/build.sh --r2)" >&2; exit 1; }

R2="--backend=r2 --r2_config=$R2_CFG --r2_ecc=0"
NOPS=30000
DB="--order=253 --prefill_keys=1000000 --n_ops=$NOPS --ssd_blocks=512 --ram_rows_per_bank=2048"
PARTS=results/dbscale/parts_r2
OUT=results/r2
JOBS="${R2_JOBS:-26}"
mkdir -p "$PARTS" "$OUT" logs
export PARTS R2

JOBFILE=$(mktemp)
q() { printf '%s|%s\n' "$1" "$2" >> "$JOBFILE"; }   # q <tag> <args>

# ── 重的先排（5M / 2M keys），避免長尾 ───────────────────────────────────────
# E2b–E2e：B_int 刻度的預算 × 政策（FULL_CRC）
for cfg in e2b:253:5000000:4096:8192:130:29344 e2c:64:2000000:5120:8192:1052:46034 \
           e2d:32:2000000:10240:16384:4159:93713 e2e:16:2000000:21504:32768:16044:193839; do
  IFS=':' read -r tag ord keys sb rpb nint npage <<< "$cfg"
  bfull=$(( npage * 12 )); budgets=""
  for pct in 0 10 25 50 75 100 200 400; do budgets="$budgets $(( ((nint*pct+50)/100) * 12 ))"; done
  for p in BY_LEVEL BY_HOTNESS LRU RANDOM; do for b in $budgets $bfull inf; do for sd in 1 2 3; do
    q "${tag}r2_FULL_CRC_${p}_b${b}_s${sd}" "--scheme=FULL_CRC --lambda_page=3e-3 --policy=$p --budget_bytes=$b --seed=$sd --order=$ord --prefill_keys=$keys --n_ops=$NOPS --ssd_blocks=$sb --ram_rows_per_bank=$rpb"
  done; done; done
done
# E6b：純規模軸
for sc in 5000000:4096:8192 3000000:2048:4096 1000000:512:2048 200000:128:1024; do
  IFS=':' read -r k sb rpb <<< "$sc"
  for s in NONE CTRL_CRC FULL_CRC; do for sd in 1 2 3 4 5; do
    q "e6br2_k${k}_${s}_s${sd}" "--scheme=$s --lambda_page=3e-3 --seed=$sd --order=253 --prefill_keys=$k --n_ops=$NOPS --ssd_blocks=$sb --ram_rows_per_bank=$rpb"
  done; done
done
# E1：scheme × λ
for s in NONE SANITY CTRL_CRC FULL_CRC; do for l in 1e-5 1e-4 3e-4 1e-3 3e-3 1e-2 3e-2; do for sd in 1 2 3 4 5; do
  q "e1r2_${s}_l${l}_s${sd}" "--scheme=$s --lambda_page=$l --seed=$sd $DB"
done; done; done
# E2：1M keys 的預算 × 政策
for sc in FULL_CRC CTRL_CRC; do for p in BY_LEVEL BY_HOTNESS LRU RANDOM; do
  for b in 0 128 256 512 1024 4096 16384 69312 inf; do for sd in 1 2 3; do
    q "e2r2_${sc}_${p}_b${b}_s${sd}" "--scheme=$sc --lambda_page=3e-3 --policy=$p --budget_bytes=$b --seed=$sd $DB"
  done; done
done; done
# E5：DRAM 容量
for s in NONE SANITY CTRL_CRC FULL_CRC; do for rpb in 2048 720 512 256 128 64 32; do for sd in 1 2 3 4 5; do
  q "e5r2_${s}_rpb${rpb}_s${sd}" "--scheme=$s --lambda_page=3e-3 --seed=$sd --order=253 --prefill_keys=1000000 --n_ops=$NOPS --ssd_blocks=512 --ram_rows_per_bank=$rpb"
done; done; done
# E7：key 稀疏度
for k in 0 8 16 24 32; do for s in NONE SANITY CTRL_CRC FULL_CRC; do for sd in 1 2 3 4 5; do
  q "e7r2_k${k}_${s}_s${sd}" "--scheme=$s --lambda_page=3e-3 --seed=$sd --key_stride_log2=$k $DB"
done; done; done
# E3：故障型態
for s in NONE SANITY CTRL_CRC FULL_CRC; do for sd in 1 2 3; do
  q "e3r2_uniform_${s}_s${sd}" "--scheme=$s --lambda_page=3e-3 --seed=$sd $DB --run_id=e3r2_uniform_${s}_s${sd}"
  q "e3r2_hammer_${s}_s${sd}"  "--scheme=$s --lambda_page=0 --hammer_rate_per_s=0.7 --hammer_flip_ratio=1e-4 --seed=$sd $DB --run_id=e3r2_hammer_${s}_s${sd}"
  q "e3r2_colctrl_${s}_s${sd}" "--scheme=$s --lambda_page=0 --colfault_time_s=150 --colfault_byte=128 --seed=$sd $DB --run_id=e3r2_colctrl_${s}_s${sd}"
  q "e3r2_colpay_${s}_s${sd}"  "--scheme=$s --lambda_page=0 --colfault_time_s=150 --colfault_byte=3000 --seed=$sd $DB --run_id=e3r2_colpay_${s}_s${sd}"
done; done
# E4：驗證頻率
for sc in CTRL_CRC FULL_CRC; do for sd in 1 2 3; do
  q "e4r2_${sc}_er_s${sd}" "--scheme=$sc --lambda_page=3e-3 --verify_mode=EVERY_READ --seed=$sd $DB"
  for th in 0.1 0.3 1 3 10 30 100; do
    q "e4r2_${sc}_p${th}_s${sd}" "--scheme=$sc --lambda_page=3e-3 --verify_mode=PERIODIC --theta_s=$th --seed=$sd $DB"
  done
done; done
# E6a：節點密度
for os in 8:4096 32:1024 128:256 253:128; do
  o="${os%%:*}"; sb="${os##*:}"
  for s in NONE CTRL_CRC FULL_CRC; do for sd in 1 2 3 4 5; do
    q "e6ar2_o${o}_${s}_s${sd}" "--scheme=$s --lambda_page=3e-3 --seed=$sd --order=$o --prefill_keys=200000 --n_ops=$NOPS --ssd_blocks=$sb --ram_rows_per_bank=8192"
  done; done
done

# 依 tag 篩選（regex）：R2_ONLY 只跑符合者，R2_SKIP 跳過符合者。
# 用途：E2d/E2e 每個 run 約 2–5 GB，需與其他實驗分開、以較低平行度執行，避免把共用工作站的記憶體吃光。
if [ -n "${R2_ONLY:-}" ] || [ -n "${R2_SKIP:-}" ]; then
  awk -F'|' -v only="${R2_ONLY:-}" -v skip="${R2_SKIP:-}" \
      '(only == "" || $1 ~ only) && (skip == "" || $1 !~ skip)' "$JOBFILE" > "$JOBFILE.f" && mv "$JOBFILE.f" "$JOBFILE"
fi
TOTAL=$(wc -l < "$JOBFILE")
echo "queued $TOTAL runs, $JOBS parallel, started $(date '+%F %T')"

xargs -d '\n' -P "$JOBS" -I{} bash -c '
  entry="{}"; tag="${entry%%|*}"; args="${entry#*|}"
  out="$PARTS/${tag}.csv"
  if [ -s "$out" ] && [ "$(wc -l < "$out")" -ge 2 ]; then exit 0; fi
  rm -f "$out"
  if ./bin/exp_r2.exe $R2 $args --csv="$out" 2> "logs/r2_${tag}.log"; then
    echo "ok $tag"
  else
    rm -f "$out"; echo "FAILED $tag" >&2
  fi
' < "$JOBFILE"
rm -f "$JOBFILE"

# ── 合併 + 列數檢查 ───────────────────────────────────────────────────────
merge() {   # merge <part prefix> <out> <expected rows>
  local prefix="$1" out="$2" want="$3" first=1
  rm -f "$out"
  for f in "$PARTS"/${prefix}*.csv; do
    [ -e "$f" ] || continue
    if [ $first -eq 1 ]; then cat "$f" > "$out"; first=0; else tail -n +2 "$f" >> "$out"; fi
  done
  local got=0; [ -f "$out" ] && got=$(( $(wc -l < "$out") - 1 ))
  printf '%-22s %4d / %4d rows %s\n' "$out" "$got" "$want" "$([ "$got" -eq "$want" ] && echo OK || echo INCOMPLETE)"
}
echo "finished $(date '+%F %T')"
merge e1r2_  "$OUT/e1_r2.csv"  140
merge e2r2_  "$OUT/e2_r2.csv"  216
merge e2br2_ "$OUT/e2b_r2.csv" 120
merge e2cr2_ "$OUT/e2c_r2.csv" 120
merge e2dr2_ "$OUT/e2d_r2.csv" 120
merge e2er2_ "$OUT/e2e_r2.csv" 120
merge e3r2_  "$OUT/e3_r2.csv"  48
merge e4r2_  "$OUT/e4_r2.csv"  48
merge e5r2_  "$OUT/e5_r2.csv"  140
merge e6ar2_ "$OUT/e6a_r2.csv" 60
merge e6br2_ "$OUT/e6b_r2.csv" 60
merge e7r2_  "$OUT/e7_r2.csv"  100
