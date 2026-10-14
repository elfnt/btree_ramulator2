#pragma once
// exp_config.hpp — 實驗組態（單一 run 的全部旋鈕）
// 本實驗層一律置於 namespace bfx，避免與 v2 全域名稱衝突。
#include <cstdint>
#include <string>

namespace bfx {

// ── 保護方案 ─────────────────────────────────────────────────────────────────
// NONE       : 無保護（基線）
// SANITY     : 只做結構完整性檢查（0 可靠記憶體）
// HDR_CRC    : 可靠記憶體存「NodeHeader 16B 的 CRC32」（entry 12 B）
// HDR_MIRROR : 可靠記憶體存「NodeHeader 16B 的完整鏡像」（entry 24 B），
//              驗證 = 直接位元組比對（無雜湊成本）
// CTRL_CRC   : 「控制平面 CRC」——涵蓋 image[0, 16+ctrl_len)，含 SSD header。可靠記憶體存
//              「image[16 .. 16+ctrl_len) 的 CRC32」（entry 12 B），其中
//                  ctrl_len = 16 (NodeHeader) + n_keys*8 (keys[])
//                           + (internal ? (n_keys+1)*8 (children[]) : 0)
//              internal 節點：涵蓋整個節點內容（internal 無 payload，全是路由資料）。
//              leaf 節點    ：涵蓋 header + keys[]，**刻意排除 values[]**
//              （唯一剩下的「真正 normal data」）。
// HYBRID     : E10 的層級差異化方案：internal（level ≥ 1）走 CTRL_CRC（entry 12 B、
//              凍結 ctrl_len），leaf（level 0）不佔可靠記憶體、改跑免費 SANITY。
//              shadow 用量因此自然 ≈ B_int。
//              動機：HDR_CRC 只看固定 16 B header，看不到決定「路由」（internal
//              children/keys）與「身分」（leaf keys）的位元組——SUMMARY.md 的
//              E1 發現 HDR_CRC 的 SDC 與 NONE 幾乎相同，根因即在此。
//              ⚠️ ctrl_len 必須在 protect() 時由「剛寫入的可信 image」算出並存進
//              ShadowEntry；驗證時一律用存下來的值，**絕不可**從讀回來（可能已毀損）
//              的 image 重算——否則翻掉 n_keys 的 flip 會讓驗證器去檢查錯誤的位元組
//              範圍，反而漏掉它自己造成的毀損。
// FULL_CRC   : 可靠記憶體存「整頁 4096B 的 CRC32」（entry 12 B）
// INPAGE_CTRL: E16。CRC32 存在**頁面本身**最後 4 B（image[page_size-4, page_size)），
//              不佔可靠記憶體。涵蓋 image[0, 16+ctrl_len)（同 CTRL_CRC），但 ctrl_len
//              只能由讀回的 image 重算（沒有可信的凍結值），夾擠在 page_size-4-16 以內。
//              n_keys 被翻 → 涵蓋範圍改變 → 與存下的 CRC 不符（自測驗證）。
// INPAGE_FULL: E16。同上，涵蓋 image[0, page_size-4)（同 FULL_CRC 的涵蓋面）。
enum class Scheme : uint8_t {
    NONE = 0, SANITY, HDR_CRC, HDR_MIRROR, CTRL_CRC, FULL_CRC, HYBRID,
    INPAGE_CTRL, INPAGE_FULL
};
inline bool is_inpage(Scheme s) { return s == Scheme::INPAGE_CTRL || s == Scheme::INPAGE_FULL; }

// E13：guard key（dummy key）模式。每插入一個真 key K，另插入：
//   RIGHT: K+1   LEFT: K-1   BOTH: K-1 與 K+1
//   MID  : K + 2^(k-1)（僅 stride 模式；對照組：同樣多的 entry，但距離 1 內無鄰居）
// dummy 的 value = GUARD_SENTINEL_VALUE；搜尋讀到此 value 視同「找不到」。
// 真 value 恆為 7K+13 (mod 2^64)；7 為奇數 → 此映射為雙射，7K+13 == 6 ⇔ K == 2^64-1，
// 而真 key 永不等於 2^64-1（driver 斷言），故 sentinel 不可能與真 value 相等。
//   GRID : E22。K + j·2^g（j = 1 … 2^(k−g) − 1，g = guard_grid_log2 < k）——把 2^k 的空隙
//          以 2^g 的間距填滿 dummy（僅 stride 模式）。g = k−1 時與 MID 逐一相同。
enum class GuardMode : uint8_t { NONE = 0, RIGHT, LEFT, BOTH, MID, GRID };

// E19：leaf 未使用 slot 的 dummy（只在頁面實體 image 中；讀入後剝除，邏輯樹不變）
//   NONE : 不填（預設，逐位元組同舊行為）
//   RIGHT: 每個真 key K 後放 K+1（slot 不足時均勻挑選）
//   BOTH : K-1 與 K+1（候選依排序順序均勻挑選）
enum class SlackGuard : uint8_t { NONE = 0, RIGHT, BOTH };
static constexpr uint64_t GUARD_SENTINEL_VALUE = 6;

// 預算不足時「保護誰」的策略（RQ2）
// BY_LEVEL   : 樹層級高者優先（root=最高）。滿載時：新頁層級 > 現存最低層級
//              才可擠掉對方（victim = 層級最低、同層取最舊）；否則拒絕收留新頁。
// BY_HOTNESS : 存取次數（LFU）。victim = hotness 最低；新 entry hotness=1。
// LRU        : victim = last_use_tick 最舊。
// RANDOM     : victim 均勻隨機。
enum class Policy : uint8_t { BY_LEVEL = 0, BY_HOTNESS, LRU, RANDOM };

// 驗證時機：每次讀 vs 距上次驗證超過 theta 秒才驗（RQ3/E4）
enum class VerifyMode : uint8_t { EVERY_READ = 0, PERIODIC };

// E8：key 分佈。STRIDE = 舊行為（index << key_stride_log2），逐位元組不變。
//   RANDOM64  : 均勻隨機 uint64（取 [0,2^63) 以保留 append 的空間），去重。
//   GEOMGAP   : key_i = Σ g_j，g_j ~ Geometric(mean 2^key_stride_log2)，g ≥ 1。
//   CLUSTERED : 每 1000 個連續 key（gap 1）一簇，簇起點 = cluster_id << 32。
enum class KeyDist : uint8_t { STRIDE = 0, RANDOM64, GEOMGAP, CLUSTERED };

// E11：只對某一層的頁注入（λ 仍是 per page）。
enum class InjectLevel : uint8_t { ALL = 0, INTERNAL, LEAF };

// E21：應用 key → 樹 key 的映射（邏輯在 keymap.hpp/.cpp）。NONE = 舊行為（逐位元組不變）。
//   SHIFT     : 樹 key = K >> key_stride_log2（僅 stride 分佈）
//   HASHDENSE : 開放定址雜湊表鋪在樹的 key 空間；(2s → K)、(2s+1 → value)
enum class KeyMap : uint8_t { NONE = 0, SHIFT, HASHDENSE };
const char* key_map_name(KeyMap m);

// scheme 的 shadow entry 大小（bytes/頁）；NONE/SANITY = 0
uint32_t scheme_entry_bytes(Scheme s);

const char* scheme_name(Scheme s);
const char* policy_name(Policy p);
const char* verify_mode_name(VerifyMode m);
const char* key_dist_name(KeyDist d);
const char* inject_level_name(InjectLevel l);
const char* guard_mode_name(GuardMode g);
const char* slack_guard_name(SlackGuard g);

// ── 一個 run 的完整組態 ──────────────────────────────────────────────────────
struct ExpConfig {
    // 模擬體規模（沿 test_btree.cpp 慣例：page 4096、7% OP、RAM 容量全載）。
    // ssd_blocks 預設 4096 僅為了 E1–E5 數字可重現（當時 GC 從未啟動）。
    // 昔日「GC 回收後頁面雙倍長度」的 v2 bug（block::erase 不清 page_data_、
    // page::program 用 append）已修：page::program 現在會先 clear。小容量
    // SSD（GC 活躍）如今是安全的，E6 之類的 GC 工作負載可放心調小此值。
    uint32_t ssd_blocks       = 4096;
    uint32_t pages_per_block  = 32;      // 實體 131072 頁、邏輯 ~121896 頁
    uint32_t page_size        = 4096;    // 必須 == DRAM_PAGE_SIZE
    uint32_t ram_rows_per_bank = 0;      // 0 = 自動（實體頁數/8，全部放得下）

    // 保護層
    Scheme     scheme        = Scheme::NONE;
    bool       sanity_always = false;    // 任何 scheme 疊加免費結構檢查
    Policy     policy        = Policy::BY_LEVEL;
    uint64_t   budget_bytes  = UINT64_MAX;   // 可靠記憶體容量；UINT64_MAX = 無上限
    VerifyMode verify_mode   = VerifyMode::EVERY_READ;
    double     theta_s       = 10.0;     // PERIODIC 驗證間隔（模擬秒；須遠小於
                                         // n_ops*dt_op 的 horizon，否則整場零驗證）

    // 故障模型（實驗自行注入；v2 的統計 lambda_eff 一律設 0）
    double lambda_page       = 0.0;      // 均勻 BER：flips / page / s（每在-RAM 頁）
    double hammer_rate_per_s = 0.0;      // row hammer 事件率（次/s）
    double hammer_flip_ratio = 0.01;     // 每事件對 2 rows 內每 bit 的翻轉機率
    double colfault_time_s   = -1.0;     // <0 = 停用；>=0 = 該模擬時刻觸發一次
    uint32_t colfault_bank   = 0;
    uint32_t colfault_byte   = 128;      // 頁內 byte 位置
    uint8_t  colfault_bit    = 3;
    uint32_t colfault_rows   = 512;

    // 工作負載
    uint32_t order        = 8;           // 節點最大 key 數
    uint32_t prefill_keys = 2000;        // 先建樹（亂序插入 0..prefill-1）
    // key 稀疏度（E7′）：實際 key = index << key_stride_log2，
    // 亦即相鄰 key 的間距 = 2^key_stride_log2。
    //   0（預設）= 完全等同舊行為（dense consecutive keys），逐欄可重現。
    //   >0        = 稀疏 key：低於第 key_stride_log2 位的 bit flip 不會破壞
    //               「keys 嚴格遞增」這個 SANITY 不變量 → 用來分離
    //               「結構不變量」與「真實檢查碼」的偵測面。
    // 上限 32（見 main_experiment.cpp 的溢位檢查）：miss key 的基底最大
    // 1 999 999 999 < 2^31，左移 32 位後 < 2^63，仍在 uint64_t 內。
    uint32_t key_stride_log2 = 0;
    KeyDist  key_dist     = KeyDist::STRIDE;      // E8（--key_dist=stride|random64|geomgap|clustered）
    InjectLevel inject_level = InjectLevel::ALL;  // E11（--inject_level=all|internal|leaf）
    KeyMap      key_map      = KeyMap::NONE;      // E21（--key_map=none|shift|hashdense）
    double      map_load     = 0.5;               // E21（--map_load=α；M = ceil(N_total/α)）
    GuardMode   guard        = GuardMode::NONE;   // E13（--guard=none|right|left|both|mid|grid）
    uint32_t    guard_grid_log2 = 0;              // E22：--guard=grid 的 dummy 間距 log2（0 = 未設定）
    // E17：parent–child 範圍檢查（下降時以父節點分隔鍵界定子節點的 [lo,hi)）
    bool        sanity_range = false;
    // E18：key 對齊檢查（key 的低 k 位必為 0；0 = 停用）
    uint32_t    sanity_align_log2 = 0;
    // E19：leaf 空 slot 的 dummy（--slack_guard=none|right|both）
    SlackGuard  slack_guard  = SlackGuard::NONE;
    uint32_t n_ops        = 30000;       // 主迴圈操作數
    double   read_ratio   = 0.9;         // 其餘為 insert（新 key 遞增）
    double   miss_ratio   = 0.05;        // search 中查「不存在 key」的比例
    double   dt_op_s      = 0.01;        // 每 op 推進的模擬時間

    // 延遲模型（模擬秒；t_mem/t_ssd 沿 RAMConfig 預設）
    double t_mem_s          = 100e-9;
    double t_ssd_s          = 100e-6;
    double t_reliable_s     = 20e-9;     // 可靠記憶體單次存取
    double t_crc_per_byte_s = 0.5e-9;    // CRC 計算：每 byte
    double t_sanity_s       = 50e-9;     // 一次結構檢查

    uint32_t seed = 1;

    // 後端選擇
    std::string backend        = "ram";  // "ram" = 純 C++ 模擬；"r2" = Ramulator2
    std::string r2_config_path = "";     // r2 後端的 YAML 組態路徑（--r2_config=...）
    bool        r2_ecc         = true;   // r2 後端是否啟用 ECC（0 = 關閉，flip 直接穿透）

    // TTL 冒煙測試旗標（ttl_theta_experiment Batch 1）：
    //   > 0 時，prefill 結束後對「所有已配置頁」設定此 TTL（秒），主迴圈期間生效。
    //   0（預設）= 停用，行為與原本完全相同。
    //   正式實驗的冷熱分類 TTL 由 ttl_theta_experiment 的 driver 負責，不走這裡。
    double      r2_ttl_s       = 0.0;

    // 輸出
    std::string run_id;                  // 空 = 自動組合
    std::string csv_path = "results/out.csv";

    // argv 解析：--key=value（鍵名同欄位；scheme/policy/verify 用字串）。
    // 未知鍵 → stderr 警告 + return false。
    bool parse_args(int argc, char** argv);
};

} // namespace bfx
