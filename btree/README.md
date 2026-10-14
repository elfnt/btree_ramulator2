# B+ tree bit-flip 實驗（Ramulator2 版）

本目錄是在 Ramulator2 之上的 B+ tree DRAM bit-flip 實驗。研究內容、主要成果與圖表見
[b-tree_experiment/README.md](b-tree_experiment/README.md)。

## 目錄結構

| 位置 | 內容 | 來源 |
|---|---|---|
| repo 根目錄的 `r2_btree_ram.*`、`r2_btree_config.*`、`r2_*` 測試 | Ramulator2 與 B+ tree 的對接（`RamulatorRAM`） | Appledog3572/ramulator2 的 16 個 commit，原作者保留 |
| `src/ramulator/controller/plugin/impl/` 的 `data_layer`、`bit_flip`、`ecc_plugin` | 儲存資料、注入 bit flip、ECC 的 Ramulator2 外掛 | 同上 |
| `btree/SSD_core/`、`new_RAM_core/`、`BTree_core/`、`tools/`、`utility.*` | SSD、DRAM 快取、B+ tree 節點的模擬核心 | smile-a-lot/bit_flip_sim 的 `v2/`（只取實驗用到的檔案） |
| `btree/b-tree_experiment/` | 保護方案、故障注入、實驗腳本、結果與圖表 | 同上的 `v2/b-tree_experiment/` |

## 建置

```bash
./build.sh                                   # 在 repo 根目錄編譯 Ramulator2，產生 libramulator.so
cd btree/b-tree_experiment
bash scripts/build.sh                        # bin/exp.exe、bin/exp_fast.exe（C++ DRAM 模型）
bash scripts/build.sh --r2                   # bin/exp_r2.exe（Ramulator2 後端）
```

單次執行範例（Ramulator2，ECC 關閉）：

```bash
./bin/exp_r2.exe --backend=r2 --r2_config=../../r2_btree_config.yaml --r2_ecc=0 \
  --scheme=CTRL_CRC --lambda_page=3e-3 --seed=1 \
  --order=253 --prefill_keys=1000000 --n_ops=30000 --ssd_blocks=512 --ram_rows_per_bank=2048 \
  --csv=out.csv
```

全部實驗的掃描腳本與注意事項（記憶體用量、平行數）見 `b-tree_experiment/scripts/run_r2_all.sh` 開頭的註解。
