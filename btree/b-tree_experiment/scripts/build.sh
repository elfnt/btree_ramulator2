#!/usr/bin/env bash
# build.sh — 產出二進位：
#   bin/exp.exe      — 標準建置（無 -DNDEBUG）：v2 SSD 的 check_invariants 全開。
#                      E1–E5 的正式數字以此為準。
#   bin/exp_fast.exe — -O2 -DNDEBUG：v2 的 assert/invariant 掃描變 no-op，供
#                      E6 這類 GC 活躍、invariant 掃描佔大半 wall-time 的 sweep
#                      使用。實驗層自身的防護（shadow 驗證等）不靠 assert，
#                      不受影響。兩者對同一組態必須產出相同的 CSV 列
#                      （invariant 檢查只讀不寫，不影響模擬行為）。
#   bin/exp_r2.exe   — Ramulator2 後端（需加 --r2 flag）。
#                      用法：./build.sh --r2
#                      執行：./bin/exp_r2.exe --backend=r2 \
#                              --r2_config=../../r2_btree_config.yaml \
#                              --scheme=NONE --lambda_page=0.01 ...
#
# v2 的 .cpp 逐一明列（不可 glob）：v2/test_*.cpp / ssd_demo.cpp 各含 main。
set -e
cd "$(dirname "$0")/.."
mkdir -p bin logs results

V2_DIR="$(pwd)/.."
R2_DIR="$(pwd)/../.."   # 本 repo 的根目錄就是 Ramulator2

# 相對路徑（對空格路徑友好；不含 btree.cpp — ExpBTree 不依賴它）
V2_SRCS="../SSD_core/ssd.cpp \
    ../SSD_core/block.cpp \
    ../SSD_core/page.cpp \
    ../new_RAM_core/new_ram.cpp \
    ../BTree_core/btree_node.cpp \
    ../utility.cpp \
    ../tools/func.cpp"

# ── 引數解析 ─────────────────────────────────────────────────────────────────
BUILD_R2=0
for arg in "$@"; do
  [[ "$arg" == "--r2" ]] && BUILD_R2=1
done

# ── 標準建置（ram 後端） ──────────────────────────────────────────────────────
if [[ $BUILD_R2 -eq 0 ]]; then
  g++ -std=c++17 -O2 -w -I include -I "$V2_DIR" \
      src/*.cpp \
      $V2_SRCS \
      -o bin/exp.exe

  g++ -std=c++17 -O2 -DNDEBUG -w -I include -I "$V2_DIR" \
      src/*.cpp \
      $V2_SRCS \
      -o bin/exp_fast.exe

  echo "built: bin/exp.exe  bin/exp_fast.exe"
fi

# ── r2 建置（Ramulator2 後端） ────────────────────────────────────────────────
if [[ $BUILD_R2 -eq 1 ]]; then
  if [[ ! -f "$R2_DIR/libramulator.so" ]]; then
    echo "ERROR: $R2_DIR/libramulator.so not found"
    echo "       請先在 ramulator2/ 執行 cmake build"
    exit 1
  fi

  # r2 build 的 V2_SRCS 同樣用相對路徑（cwd = b-tree_experiment/）
  # btree.cpp 由 r2_btree_ram.cpp 間接依賴，但 ExpBTree 不用，故仍不含
  g++ -std=c++20 -O2 -DNDEBUG -DHAVE_RAMULATOR2 -w \
      -I include \
      -I "$V2_DIR" \
      -I "$R2_DIR/src" \
      -I "$R2_DIR/ext/yaml-cpp/include" \
      -I "$R2_DIR/ext/spdlog/include" \
      -I "$R2_DIR" \
      src/*.cpp \
      "$R2_DIR/r2_btree_ram.cpp" \
      $V2_SRCS \
      -L "$R2_DIR" -lramulator "-Wl,-rpath,$R2_DIR" \
      -o bin/exp_r2.exe

  echo "built: bin/exp_r2.exe"
fi
