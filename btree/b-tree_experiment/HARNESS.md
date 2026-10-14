# b-tree_experiment — B+ 樹對 DRAM bit-flip 的偵測與防護研究

> **2026-10-13 清理註記**：舊版小規模實驗（order 8 / 2,000 keys）的結果與腳本已從工作目錄移除，包括 `results/SUMMARY.md`、`results/e1.csv`…`e6b.csv`、`results/*_r2*.csv`、`results/plots/`、`scripts/run_e1.sh`…`run_e4.sh`、`scripts/run_e*_r2*.sh`、`scripts/analyze.py`。下文提到它們的段落僅供參考；需要時可從原 repo（smile-a-lot/bit_flip_sim，commit 429c562 的 `v2/b-tree_experiment/`）取回。目前使用的是 DB 規模的 `scripts/run_e*_db.sh`，見 [README.md](README.md)。

本資料夾是 v2 內的獨立實驗層：**只把上層的 v2 程式碼（`../`）當作 API 使用，
絕不修改其任何檔案**。所有實驗程式碼、腳本、結果都收在這裡。

---

## 1. 研究問題

DRAM 發生 bit flip 時，B+ 樹的 page image 會被靜默破壞。本研究問：

- **RQ1（偵測能力）**：把關鍵中繼資料（全頁 CRC32、NodeHeader 的導航資訊）放在
  「可靠記憶體」（模擬 ECC SRAM / 暫存器檔），能把毀損偵測做到多好？
  各方案的 F1 score 隨錯誤率如何變化？
- **RQ2（可靠記憶體不足）**：可靠記憶體容量不夠保護全部節點時，
  哪種「該保護誰」的策略最好？（依樹層級優先 / 依熱度 / LRU / 隨機）
  F1–budget 曲線長怎樣？
- **RQ3（成本）**：偵測與復原對讀取延遲的影響（驗證計算成本、SSD 重載成本、
  驗證頻率 every-read vs periodic-θ 的取捨）。
- **RQ4（錯誤空間結構）**：均勻位元錯誤 vs 空間相關錯誤（row hammer、位元線
  column 故障）下，資料擺放（節點分佈於 bank/row）如何影響損害集中度與偵測。
- **RQ5（免費的防線）**：不花可靠記憶體的「結構完整性檢查」（sanity check：
  node_type/pad/n_keys 邊界、keys 排序、指標範圍）能接住多少毀損？
  和 CRC 方案的差距多大？

### 有趣的衍生現象（一併量測）

- **寫回污染（poisoned write）**：讀到未偵測的毀損節點 → 修改 → 寫回，
  毀損經 write-through 永久化到 SSD。保護層在寫入前驗證可以擋下多少？
- **自然清洗（natural scrubbing）**：LRU/TTL 逐出會丟棄 DRAM 中的毀損副本，
  下次從 SSD 重載即恢復乾淨——逐出策略本身就是一種被動防護。

## 2. 對 v2 的依賴方式（全部唯讀）

| v2 API | 用途 |
|---|---|
| `SSD`（read/write/trim/GC） | 持久層；**write-through 保證 SSD 上永遠是最後寫入的乾淨副本 → 復原來源**（ram 後端） |
| `IRAM`（new_RAM_core） | 抽象記憶體介面；`GuardedRAM` 與 `FaultInjector` 以此為底層依賴，與具體實作解耦 |
| `RAM : IRAM`（new_RAM_core） | 純 C++ DRAM 模擬（ram 後端）：read/write/allocate、LRU/TTL、延遲模型 |
| `RAM::inject_*`（透過 IRAM 虛擬方法） | 真實毀損來源（v2 的 Poisson 只計數、不改資料，故實驗自行驅動注入） |
| `BTreeNode` serialize/deserialize | 節點序列化格式（image[16..31]=NodeHeader、[32..]=keys/values/children） |
| `pageCRC32`（tools/checksums） | 校驗值計算 |

可選依賴（僅 r2 後端需要）：

| Ramulator2 API | 用途 |
|---|---|
| `RamulatorRAM : IRAM`（ramulator2/） | Cycle-accurate DDR4 後端；讀寫延遲來自真實 DDR4 時序 |
| DataLayer / BitFlip / ECC plugin | 儲存 page 資料、週期性注入 bit flip、透明 SECDED 修正 |

**為何 `ExpBTree` 不用 v2 的 `BTree` 類別**：實驗需要把 `GuardedRAM`（含
保護層判斷、oracle 評分）插進每一次讀寫路徑；`BTree` 是為 RAM/IRAM 直接存取
設計的，沒有這層 hook。因此 `ExpBTree` 以相同節點格式、相同分裂邏輯重寫
（~200 行），所有 I/O 改走 `GuardedRAM`。v2 原始碼零改動。
（注：v2 `BTree` 本身現已透過 `IRAM*` 支援 `RamulatorRAM`，見 `r2_test_btree`。）

## 3. 架構

```
ExpBTree（B+ 樹，鏡射 v2 BTree 邏輯，回報節點層級）
    │  read / write / allocate（帶 level hint）
GuardedRAM（保護層：驗證、分類 TP/FP/FN/TN、復原、oracle 地面真相）
    │                                  │
   IRAM*                              ShadowStore（可靠記憶體模型：
    ├─ [ram]  RAM（v2 純 C++ 模擬）    容量預算 + 保護對象選擇策略）
    │          │
    │         SSD（write-through 的乾淨副本；crash_rescue 來源）
    │
    └─ [r2]   RamulatorRAM（Ramulator2 DDR4，cycle-accurate 延遲）
               ├─ DataLayer plugin（儲存 page 資料）
               ├─ BitFlip  plugin（自動注入 bit flip）
               └─ ECC      plugin（SECDED 透明修正）

FaultInjector（Poisson 均勻 BER + row hammer / column fault，呼叫 IRAM::inject_*）
```

`--backend=ram`（預設）使用上路徑，行為與原版完全相同；
`--backend=r2` 使用下路徑，延遲來自真實 DDR4 時序，無 SSD 後端。

### 保護方案（Scheme）

| 方案 | 可靠記憶體成本/頁 | 覆蓋範圍 | 驗證成本 |
|---|---|---|---|
| `NONE` | 0 B | 無 | 0 |
| `SANITY` | 0 B | 結構不變量可及處 | 解析檢查 |
| `HDR_CRC` | 12 B | NodeHeader 16 B | CRC over 16 B |
| `HDR_MIRROR` | 24 B | NodeHeader 16 B | 16 B 直接比對（免雜湊） |
| `CTRL_CRC` | 12 B | **控制平面** `16 + ctrl_len` B | CRC over `ctrl_len` B |
| `FULL_CRC` | 12 B | 整頁 4096 B | CRC over 4096 B |

任一方案可加開 `sanity_always`（結構檢查免費疊加）。
偵測後的復原一律 = 從 SSD 重載乾淨副本（成本 `t_ssd`）。

#### `CTRL_CRC`（控制平面 CRC）

```
ctrl_len = 16 (NodeHeader) + n_keys*8 (keys[])
         + (node_type == internal ? (n_keys+1)*8 (children[]) : 0)
```

覆蓋 `image[16 .. 16+ctrl_len)`：

- **internal 節點**：等於整個節點內容（internal 沒有 payload，keys/children 全是路由資料）
- **leaf 節點**：header + keys[]，**刻意排除 values[]**——那是唯一真正的
  「normal data」

動機：`HDR_CRC` 只看固定 16 B 的 NodeHeader，看不見決定**路由**（internal 的
keys/children）與**身分**（leaf 的 keys）的位元組。舊 `SUMMARY.md` 的 E1 因此
發現「HDR_CRC 把 would_crash 砍半，但 SDC 與 NONE 幾乎一模一樣」。
`CTRL_CRC` 就是把保護面推到 control/payload 的交界，用遠低於 `FULL_CRC` 的
驗證成本換回幾乎全部的 SDC 防護（DB 規模的量化結果見
`results/SUMMARY_dbscale.md`）。

**正確性不變量（實作重點）**：`ctrl_len` 必須在 `protect()` 時由「剛寫入的可信
image」算出並凍結進 `ShadowEntry`；驗證時一律用存下來的值，**絕不可**從讀回來
（可能已毀損）的 image 重算——否則 `n_keys` 被翻掉時，驗證器會去檢查錯誤的
位元組範圍。`ShadowStore::crc_of()` 的 `ctrl_len` 參數因此刻意不給預設值，
強迫每個呼叫點明寫。driver 啟動時的 `ctrl_crc_self_test()` 會驗證三件事：
(a) 乾淨往返不誤報、(b) 涵蓋區內任一位元組翻轉必被抓到、
(c) LEAF 涵蓋區外的翻轉恆不被抓到（證明邊界確實落在預期位置）。

### 保護對象選擇策略（Policy，RQ2）

預算不足時決定誰有 shadow entry：`BY_LEVEL`（internal/root 優先——一個壞指標
毒害整棵子樹，一個壞 value 只毒害一筆查詢）、`BY_HOTNESS`（存取計數）、
`LRU`、`RANDOM`。

### 指標

- **頁級偵測分類**（每次 guarded read 一筆）：
  truth = 「讀到的 image ≠ oracle（該頁應有內容）」；predicted = 「保護層報警」。
  → TP/FP/FN/TN → precision / recall / **F1**。
- **端到端**：search 結果對照 `std::map` 參考模型 → 未偵測錯誤結果數（SDC）；
  結束後全 key 完整性掃描。
- **延遲**：模擬延遲總和 / 平均 / 最大（含驗證與復原成本），對照 NONE 基線。
- **其他**：recoveries、would_crash（結構毀損嚴重到真實系統會當機，實驗以
  「fail-stop + 重載」續跑並計數）、poisoned writes、注入事件數 vs 實際讀到
  毀損數（差值 = 自然清洗）。

## 4. 實驗矩陣

| 實驗 | 掃描維度 | 固定 | 回答 |
|---|---|---|---|
| E1 | λ ∈ {1e-5…3e-2} × Scheme | budget=∞ | RQ1, RQ3, RQ5 |
| E2 | budget ∈ {0…全額} × Policy | λ 固定, FULL_CRC | RQ2 |
| E3 | 錯誤模式 {uniform, row hammer, column} × Scheme | λ 等效 | RQ4 |
| E4 | 驗證頻率 {every-read, θ ∈ …} | λ 固定 | RQ3 |

每組 ≥3 seeds。λ 單位 = flips/page/s；op 間隔 `dt_op` 秒推進模擬時鐘，
注入數 ~ Poisson(λ × 在 RAM 頁數 × dt)。

### 4b. DB 規模矩陣（E1′–E4′）

上表的 E1–E5 用的是玩具規模（order 8、2000 keys）。**真實 DB 的節點密度是
order ≈ 253**（4096 B 頁 + 8 B key/value），樹淺得多、單頁覆蓋的 key 多得多，
結論會變。E1′–E4′ 把 DB 規模當成主要條件重跑一次：

| 實驗 | 內容 | 腳本 | 輸出 |
|---|---|---|---|
| E1′ | 6 scheme × 7 λ × 5 seeds（含 `CTRL_CRC`）+ 毀損歸因 | `run_e1_db.sh` | `results/e1_dbscale.csv` |
| E2′ | 2 scheme × 4 policy × 9 budget × 3 seeds | `run_e2_db.sh` | `results/e2_dbscale.csv` |
| E3′ | 4 種錯誤空間結構 × 6 scheme × 3 seeds | `run_e3_db.sh` | `results/e3_dbscale.csv` |
| E4′ | 2 scheme × {every-read, 7 個 θ} × 3 seeds | `run_e4_db.sh` | `results/e4_dbscale.csv` |
| E1′-r2 | E1′ 的 Ramulator2 DDR4 複本（ECC off，3 seeds） | `run_e1_db_r2.sh` | `results/e1_dbscale_r2_noecc.csv` |

共用規模參數與其校準理由集中在 `scripts/db_common.sh`；彙總與資料品質檢查用
`scripts/analyze_db.py`（`--qc`）。結果與觀察見 `results/SUMMARY_dbscale.md`。
舊的玩具規模結果 `results/SUMMARY.md` 與 `e1.csv…e6b.csv` 保留為歷史基線，
未被覆寫。

⚠️ **`--ram_rows_per_bank` 在 DB 規模必須顯式給定**：不給時 ram 與 r2 兩後端的
DRAM 容量差 8 倍（ram 是 `rows_per_bank × 8`、r2 是 `ssd_blocks*ppb/8` 總頁數），
會讓 r2 提早發生 LRU 逐出而混入「自然清洗」效應。詳見 `db_common.sh` 註解。

## 5. 建置與執行

### ram 後端（原版，純 C++ 模擬）

```bash
cd b-tree_experiment
bash scripts/build.sh                 # 產出 bin/exp.exe + bin/exp_fast.exe
./bin/exp.exe --scheme=FULL_CRC --lambda=1e-3 --seed=1 \
              --csv=results/e1.csv 2> logs/run.log
bash scripts/run_e1.sh                # E1 掃描
bash scripts/run_e2.sh                # E2 掃描
bash scripts/run_e3.sh                # E3 掃描
bash scripts/run_e4.sh                # E4 掃描
python scripts/analyze.py results/   # 匯總表
```

### r2 後端（Ramulator2 DDR4，cycle-accurate 延遲）

需先在 `ramulator2/` 完成 cmake build，產出 `libramulator.so`。

```bash
cd b-tree_experiment
bash scripts/build.sh --r2            # 產出 bin/exp_r2.exe（-std=c++20 -DHAVE_RAMULATOR2）

./bin/exp_r2.exe \
    --backend=r2 \
    --r2_config=../../r2_btree_config.yaml \
    --scheme=FULL_CRC --lambda_page=1e-3 --seed=1 \
    --csv=results/e1_r2.csv 2> logs/run_r2.log
```

`--r2_config` 接受任何 Ramulator2 YAML（需含 DataLayer plugin；`--r2_ecc=1` 時
還需 ECC plugin）。

**`--r2_ecc`（預設 1）**：控制是否透過 ECC plugin 讀寫。

| `--r2_ecc` | 行為 | 適用場景 |
|---|---|---|
| `1`（預設） | SECDED 透明修正所有 1-bit flip；GuardedRAM 幾乎永遠看到乾淨資料 | 量測「硬體 ECC 保護下」的殘餘風險 |
| `0` | raw DataLayer 讀寫；flip 直接穿透到 GuardedRAM | E1–E4 vulnerability 量測，可與 ram 後端直接比較 |

掃描腳本對應關係：

```
run_e1.sh / run_e2.sh / run_e3.sh / run_e4.sh        → ram 後端（基準）
run_e1_r2.sh / …                                      → r2 後端，ECC on
run_e1_r2_noecc.sh / …                               → r2 後端，ECC off（可與 ram 比較）
```

`run_e3_r2*.sh` 同樣支援 uniform / hammer / colfault 三模式（`inject_row_error` /
`inject_column_error` 已在 `RamulatorRAM` 中以 `page_id = bank × rows_per_bank + row`
映射實作）。與 ram 後端的差異僅在延遲來源（DDR4 timing）而非故障注入語意。

注意：v2 的 SSD 會對 stdout 大量列印除錯訊息——driver 啟動時把 stdout
重導向 NUL；stderr 由執行腳本導入 logs/。實驗結果只寫 CSV。

## 6. 資料夾結構

```
include/   介面契約（行為規格以標頭註解為準）
src/       實作
scripts/   build / sweep / 分析
results/   CSV 輸出（追蹤）
logs/      執行紀錄（不追蹤）
bin/       執行檔（不追蹤）
```
