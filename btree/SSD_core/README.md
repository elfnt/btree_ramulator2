# SSD 模擬器（非常簡易版）

log-structured FTL。**「某個實體頁是否有效」的唯一判準是 mapping table（L2P）**，page 與 block 都不回答這個問題 —— 這是理解底下所有東西的前提。

## 如何 compile
參見 `compile.txt`。

自動化測試：
```bash
g++ -std=c++17 -w test_ssd.cpp SSD_core/ssd.cpp SSD_core/block.cpp SSD_core/page.cpp utility.cpp tools/func.cpp -o ssd_unit_test
./ssd_unit_test > /dev/null      # SSD 的除錯訊息走 stdout，檢查結果走 stderr
```
**不要加 `-DNDEBUG`** —— `check_invariants()` 是靠 `assert` 生效的。

## 如何使用
在工作資料夾
```powershell
./ssd_test.exe
```
或者利用 flag
`--max_block_count`
`--page_size_bytes`
`--pages_per_block`
`--logical_page_count`
例如：
```powershell
./ssd_test.exe --max_block_count 30 --page_size_bytes 17 --pages_per_block 40 --logical_page_count 1000
```

注意事項：
- **`page_size_bytes` 必須 > `sizeof(header)`（16）**，payload 目前固定 1 byte，所以實務上用 17。
- **`max_block_count` 至少要 4**（2 個寫入前緣 + 1 個 victim 候選 + 1 個 OP 保留區），不足會在建構子 throw。預設是 8。
- **LA 必須 < `logical_page_count`**，超界會被擋掉回 `invalid_logical_page_id`。預設 10000。

### instructions
```powershell
write 1 227   #對 LA=1 寫入 payload = 227
read 1        #讀 LA=1
trim 1        #trim 掉 LA=1
SBS 0         #show block state，block id = 0
SBS-A         #show block state --all
SMT           #show mapping table，LA -> {block id, offset}
```
每一條指令執行完，main 都會呼叫一次 `ssd.GC()`。

## demo
### 基本讀寫
```powershell
./ssd_test.exe
SSD config:
8 blocks
4 pages per block
17 bytes per page
```
```powershell
SBS 0      #全新的 block：4 頁都是 free
Block 0 stats:
        4 free pages
        0 invalid pages
        0 valid pages
------------------------------------------------
page_id 0       1       2       3
content _       _       _       _
states  F       F       F       F
LA      _       _       _       _

read 1     #還沒寫過，讀不到
LA = 1
SSD::read LA = 1
SSD::read(logical addr = 1) failed: invalid_logical_page_id

write 1 227
SSD::write LA = 1

read 1
LA = 1
SSD::read LA = 1
SSD::read(logical addr = 1) success

SBS 0
Block 0 stats:
        3 free pages
        0 invalid pages
        1 valid pages
------------------------------------------------
page_id 0       1       2       3
content 227     _       _       _
states  V       F       F       F
LA      1       _       _       _

SMT
Mapping table:
1 -> {0, 0}
```

### 顯示格式
| 列 | 意義 |
|---|---|
| `content` | payload 尾碼；`_` = 該頁是 free |
| `states` | `F` = 未寫入、`V` = 寫入且 mapping 仍指著它、`I` = 寫入但已過期 |
| `LA` | 這頁宣稱自己屬於哪個 LA（`meta_data.pageId`）；`_` = free |

`V` 與 `I` 的差別**完全來自 `is_valid()`**，也就是「去問 mapping table，這個 LA 現在是不是還指回這一頁」，不是 page 自己的狀態。

`LA` 那一列拿去對照 `SMT` 就是最好用的除錯手段：某頁寫著 `LA=15`，而 SMT 說 `15 -> {3, 0}`（別的位置），那它就必然是 `I`。

### GC
連續寫入 8 個 LA 再全部覆寫一輪，把實體空間逼到需要回收：
```powershell
write 11 110 ... write 18 180      #第一輪，填滿 block 0、1
write 11 111 ... write 18 181      #第二輪覆寫，填滿 block 2、3
write 99 200                       #host 前緣移到 block 4，free block 掉到門檻

SSD::GC victim = block 0 (4 stale / 4 programmed)

SMT
Mapping table:
11 -> {2, 0}   12 -> {2, 1}   13 -> {2, 2}   14 -> {2, 3}
15 -> {3, 0}   16 -> {3, 1}   17 -> {3, 2}   18 -> {3, 3}   99 -> {4, 0}

SBS 0      #victim 被搬空後 erase，整塊回到 free
Block 0 stats:
        4 free pages
        0 invalid pages
        0 valid pages
------------------------------------------------
page_id 0       1       2       3
content _       _       _       _
states  F       F       F       F
LA      _       _       _       _

SBS 1      #第一輪寫的 15~18 仍在，但 SMT 已指向 block 3，所以全是 I
Block 1 stats:
        0 free pages
        4 invalid pages
        0 valid pages
------------------------------------------------
page_id 0       1       2       3
content 150     160     170     180
states  I       I       I       I
LA      15      16      17      18

SBS 2      #第二輪的 11~14，SMT 指著它們，所以是 V
Block 2 stats:
        0 free pages
        0 invalid pages
        4 valid pages
------------------------------------------------
page_id 0       1       2       3
content 111     121     131     141
states  V       V       V       V
LA      11      12      13      14
```
注意 block 0 的 4 頁全是 stale，所以 GC 搬移了 0 頁就直接 erase —— 這是最理想的 victim。

## page
`v2/SSD_core/page.hpp`
`v2/SSD_core/page.cpp`

page 是**純物理層**：它只知道自己被抹除或被寫入，以及被寫入時屬於哪個 LA。有效性一律不由 page 回答。

### read
```cpp
bool read(std::vector<uint8_t>& output);
```
讀取 page header + payload，即整個 disk page 的 data，以 `output` 作為 output parameter，return 是否 read 成功。

### program
```cpp
bool program(const uint32_t logical_page_id, const std::vector<uint8_t>& data);
```
對一個 `logical_page_id` 寫入 `data`（格式同樣是 header + payload），return 是否 program 成功。只有 `state == free` 的頁能被 program。

### page state
只有兩個 state：
1. `free`
2. `programmed`

轉換：
- `free`       -> `programmed`   (program)
- `programmed` -> `free`         (erase / setFree)
- `free`       -> `free`         (erase)

read 不影響 page state。

**沒有 `invalid` 這個 state**。一頁「寫過但已過期」不是它自己的狀態，而是 mapping table 不再指向它的結果 —— 作廢是隱含的，不需要任何人跑去標記。

### meta_data.pageId
記錄這頁 program 當下屬於哪個 LA。這是 `is_valid()` 反查的依據，**絕對不能砍**。`setFree()` 會把它重設回 `UINT32_MAX`。

## block
`v2/SSD_core/block.hpp`
`v2/SSD_core/block.cpp`

block 也是純物理層，只管 `slots_` / `next_offset_` / `capacity_` / `erase`：
```cpp
std::vector<std::unique_ptr<page>> slots_;
```
提供 `read`、`program`、`erase`，以及 O(1) 的 `programmedPageCount()` / `isFull()` / `isEmpty()`。

`next_offset_` 是單調遞增的寫入指標，只有 `erase()` 會把它歸零，所以它同時就等於「這塊已被寫入的頁數」。

block **不提供** `validPageCount()` / `invalidPageCount()` —— valid/invalid 屬於 FTL 層，由 SSD 回答。

## SSD
`v2/SSD_core/ssd.hpp`
`v2/SSD_core/ssd.cpp`

### public member function
```cpp
//write content to a LA
ssd_status write(uint32_t LA, const std::vector<uint8_t>& content);
//read content of a LA to output
ssd_status read(uint32_t LA, std::vector<uint8_t>& output);
//dead a LA
ssd_status trim(uint32_t LA);
//garbage collection algorithm
ssd_status GC();
//host 尚未占用的邏輯頁數
uint32_t available_logical_pages() const;
//debug: assert 所有衍生索引都還跟 L2P 一致（NDEBUG 下是 no-op）
void check_invariants() const;
```
（考慮未來將 `GC()` 放到 private）

### 唯一真相來源
```cpp
std::vector<physical_address> l2p_;     //LA -> pa，未映射時是 INVALID_PA
```
覆寫、trim、GC 搬移，全都只改**這一個 entry**。改完的瞬間舊那頁自動變 stale。

```cpp
bool SSD::is_valid(physical_address pa) const;
```
全系統唯一的有效性判準：那頁記得自己屬於哪個 LA，去問 mapping table，LA 現在是不是還指回這一頁。GC、顯示、統計一律只透過它。

### 兩個寫入前緣
`host_front_` 與 `gc_front_` 永遠指向兩個不同的 open block：
- 防止 GC 把剛搬出來的資料寫回正要被 erase 的 victim（這會靜默遺失資料）
- host 資料較熱、GC 搬移的資料較冷，分流可降低寫入放大（WAF）

`RESERVED_BLOCKS = 1` 是 OP 保留區，host 拿不到，確保 GC 永遠有地方可搬 —— 沒有它會出現「必須先 GC 才有空間，但 GC 也沒空間可搬」的死鎖。

### 容量會計
```
available_logical_pages() = logical_page_count_ - mapped_count_
```
只有兩件事會改變它：新 LA 首次寫入（+1 占用）、trim（−1）。**GC / relocate / erase 完全不碰它。**

實體空間壓力是另一回事，由 `free_block_count()` 表達，也是 GC 的觸發依據。邏輯容量與實體壓力從此是兩個獨立的量。

### 衍生索引
```cpp
std::vector<uint32_t> block_valid_page_count_;
uint32_t stale_count(bid) = programmedPageCount(bid) - block_valid_page_count_[bid];
```
只用來 O(blocks) 排序候選 victim，**不用來決定要不要搬某一頁**（那是 `is_valid()` 的工作）。出錯的後果只是選到較差的 victim，不會遺失資料。`check_invariants()` 的 (b) 會直接對照逐頁掃描結果抓它有沒有脫節。
