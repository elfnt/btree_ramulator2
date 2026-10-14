#pragma once
#include <cstdint>
#include <vector>
#include <limits>

// ── 常數 ────────────────────────────────────────────────────────────────────
static constexpr uint32_t DRAM_PAGE_SIZE = 4096;   // Row size = OS page size = 4 KB
static constexpr uint32_t DRAM_NUM_BANKS = 8;

// ECC_RAM 的 SECDED 保護單位：64-bit（8-byte）word + 8-bit parity
// 注入函式的粒度必須與此一致，否則「N 個翻轉落在同一個 ECC word」的語意會失效。
static constexpr uint32_t ECC_WORD_BYTES     = 8;
static constexpr uint32_t ECC_WORDS_PER_PAGE = DRAM_PAGE_SIZE / ECC_WORD_BYTES;  // 512

// ── 物理位址 ─────────────────────────────────────────────────────────────────
struct DRAMAddress {
    uint32_t bank;
    uint32_t row;
};

// ── 初始化設定 ────────────────────────────────────────────────────────────────
struct RAMConfig {
    uint32_t rows_per_bank;                              // 總容量 = 8 × rows_per_bank pages
    double   lambda_eff  = 0.0;                          // bit flip 速率（flips/page/second）
    double   t_mem       = 100e-9;                       // DRAM 存取延遲（s）
    double   t_ssd       = 100e-6;                       // SSD 存取延遲（s）
    uint32_t seed        = 42;

    // ── 全局開關 ──────────────────────────────────────────────────
    // TTL 逐出：enable_ttl=true 時，allocate() 自動對每頁設定 ttl_seconds
    bool     enable_ttl    = false;
    double   ttl_seconds   = 3600.0;

    // TTL 到期判定基準（ttl_theta_experiment 需要 residency 語意）
    //   false（預設，沿用舊行為）: idle-based —— 逐出條件 t − last_access > ttl
    //                              頻繁被讀的頁永遠不會過期
    //   true : residency-based —— 逐出條件 t − load_time > ttl
    //          不論讀取頻率，頁面駐留超過 ttl 即逐出。
    //          這才是 P_s 模型中「曝露窗 = t_evict」的正確語意，
    //          也才能量到「hot page 被誤判為 cold」的真實代價。
    bool     ttl_residency = false;

    // Theta-verify：enable_verify=true 時，read() 每隔 theta 秒對頁面做一次驗證
    // 驗證可捕捉硬體未糾正的 silent flip（軟體 checksum 補位）
    bool     enable_verify = false;
    double   theta         = 600.0;
};

// ── 單一 DRAM Row 的狀態 ──────────────────────────────────────────────────────
// Slot (bank, row) 的 page_id = bank * rows_per_bank + row
// 固定映射：一個 slot 只會存放唯一對應的 page_id
struct RAMSlot {
    std::vector<uint8_t> data;                           // 頁面內容（有效時為 DRAM_PAGE_SIZE bytes）
    uint64_t owner_page_id = UINT64_MAX;                 // 目前存放的 page_id（UINT64_MAX = 空格）
    bool     valid       = false;                        // 是否有資料在 RAM 內
    bool     is_cold     = false;                        // 是否啟用 TTL 逐出
    double   last_access   = 0.0;                        // 最後存取時間（LRU / TTL idle 計算用）
    double   last_check    = 0.0;                        // 上次計算 bit flip 的時間點
    double   last_verified = 0.0;                        // 上次 theta-verify 的時間點
    double   load_time     = 0.0;                        // 本頁載入本格的時間（TTL residency / T_reload 曝露窗計算用）
    double   ttl           = std::numeric_limits<double>::infinity();  // TTL 秒數
};

// ── 統計資料 ──────────────────────────────────────────────────────────────────
struct RAMStats {
    uint64_t n_reads         = 0;
    uint64_t n_writes        = 0;
    uint64_t n_hits          = 0;
    uint64_t n_misses        = 0;   // cache miss → 觸發 SSD 讀取
    uint64_t n_lru_evictions = 0;
    uint64_t n_ttl_evictions = 0;

    // ── ECC / 錯誤統計 ────────────────────────────────────────────
    // n_hw_corrected：ECC 成功修正的 word 數（1-bit error per word）
    // n_hw_silent   ：ECC miscorrection 數（3+ bit，syndrome 指向錯誤位置，靜默寫回錯誤值）
    // n_ecc_ue      ：ECC 偵測到但無法修正的 word 數（2/4/6+ bit，UncorrectableError）
    uint64_t n_hw_corrected      = 0;
    uint64_t n_hw_silent         = 0;
    uint64_t n_ecc_ue            = 0;

    uint64_t n_allocations       = 0;
    uint64_t n_verifications     = 0;   // 觸發 theta-verify 的次數
    uint64_t n_verify_detections = 0;   // verify 捕捉到的錯誤數
};

// ── Read 回傳值 ───────────────────────────────────────────────────────────────
struct RAMReadResult {
    std::vector<uint8_t> data;
    bool        hit;
    double      latency;
    int         n_corrected;   // ECC 修正的 word 數
    int         n_ecc_ue;      // ECC 偵測到但無法修正的 word 數（UE）
    int         n_silent;      // ECC miscorrection 數（靜默損壞）
    DRAMAddress phys;          // 物理位址（bank, row），方便 error injection 查詢
};
