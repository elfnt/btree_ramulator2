#pragma once
#include "ram_types.hpp"
#include "../SSD_core/ssd.hpp"
#include <vector>
#include <random>
#include <unordered_map>
#include <queue>

// ── IRAM — 抽象 RAM 介面（供 BTree 使用）────────────────────────────────────
//
// RAM（純 C++ 模擬）和 RamulatorRAM（Ramulator2 cycle-accurate 後端）
// 都繼承自這個介面，讓 BTree 與具體實作解耦。
class IRAM {
public:
    virtual ~IRAM() = default;

    virtual RAMReadResult read(uint64_t page_id, double current_time) = 0;

    virtual void write(uint64_t page_id,
                       const std::vector<uint8_t>& data,
                       double current_time) = 0;

    virtual uint64_t allocate(double current_time) = 0;

    virtual void free_page(uint64_t page_id) = 0;

    // 推進模擬時間（RamulatorRAM 不需要，預設空實作）
    virtual void advance_time(double /*dt*/) {}

    // ── 查詢（供 GuardedRAM）────────────────────────────────────────
    // 頁是否目前在 DRAM 內（RamulatorRAM 預設 true＝DataLayer 全在 DRAM）
    virtual bool is_in_ram(uint64_t /*page_id*/) const { return true; }

    // ── TTL（供 ttl_theta_experiment 的冷熱分類器）────────────────────
    // 設定某頁的 TTL；ttl_seconds = +inf 代表取消 TTL（視為 hot page）。
    //
    // 重要語意（兩個後端一致）：
    //   TTL 政策是「持久」的 —— 綁定 page_id 而非綁定當前的物理格。
    //   頁面被逐出後再從 SSD 載入，TTL 政策必須自動重新套用，
    //   否則 TTL 只會觸發一次（這正是 v2 原實作的缺陷）。
    virtual void set_ttl(uint64_t /*page_id*/, double /*ttl_seconds*/) {}

    // 該頁自上次從 SSD 載入至今的駐留時間（= P_s 模型中的曝露窗 T_reload）。
    // 頁面不在 RAM 內時回傳 0。
    virtual double residency(uint64_t /*page_id*/, double /*now*/) const { return 0.0; }

    // 主動逐出一頁（不經讀取）。回傳是否確實逐出（頁不在 RAM 時回傳 false）。
    //
    // 用途：積極（eager）TTL —— 背景掃描到期頁面並立即逐出，
    //   不必等下一次讀取。懶惰 TTL 只能保護「被讀過的頁」，
    //   而 cold page 大多整場都不會被讀到（實測約 1750/2152）。
    //
    // SSD 上有 write-through 的乾淨副本，因此逐出等同放棄 DRAM 中已累積錯誤的副本。
    virtual bool evict(uint64_t /*page_id*/) { return false; }

    // ── 統計 ───────────────────────────────────────────────────────
    virtual RAMStats get_stats() const { return RAMStats{}; }

    // ── 故障注入（供 FaultInjector）──────────────────────────────────
    // 預設空實作；RamulatorRAM 透過 DataLayer API 實作
    virtual void inject_random_flip(uint64_t /*page_id*/) {}

    // ── 指定位置的注入（供 ttl_theta_experiment 的 FaultModel）──────
    //
    // flip_bit ：XOR 翻轉 —— **transient** 故障。資料被覆寫或重載後即消失。
    // force_bit：釘死為指定值 —— **permanent**（stuck-at）故障。
    //            必須用「設值」而非 XOR：真實的 stuck-at cell 只有在
    //            「應寫入的值 ≠ 卡住的值」時才表現為錯誤（約半數情況）。
    //            用 XOR 會讓每次都出錯，把永久故障的影響高估一倍。
    //
    // 兩者皆回傳「資料是否真的改變」，讓上層能正確判定該頁是否進入損毀狀態。
    virtual bool flip_bit(uint64_t /*page_id*/, uint32_t /*byte*/, uint8_t /*bit*/) {
        return false;
    }
    virtual bool force_bit(uint64_t /*page_id*/, uint32_t /*byte*/, uint8_t /*bit*/,
                           bool /*value*/) {
        return false;
    }
    virtual void inject_row_error(uint32_t /*bank*/, uint32_t /*start_row*/,
                                   double   /*flip_ratio*/ = 0.5) {}
    virtual void inject_column_error(uint32_t /*bank*/, uint32_t /*start_row*/,
                                      uint32_t /*col_byte*/, uint8_t  /*bit*/,
                                      uint32_t /*num_rows*/ = 512) {}
};

// ── NewRAM ───────────────────────────────────────────────────────────────────
//
// 物理 layout：
//   page_id → bank = page_id / rows_per_bank
//           → row  = page_id % rows_per_bank
//
// 每個 (bank, row) slot 固定對應唯一一個 page_id，不會移動。
// slot 可以是 valid（page 在 RAM 內）或 invalid（page 被逐出到 SSD）。
//
// B-Tree 只透過此類存取資料，不直接碰 SSD。
//
class RAM : public IRAM {
public:
    RAM(RAMConfig config, SSD* ssd);
    virtual ~RAM() = default;

    // ── B-Tree / 上層介面 ────────────────────────────────────────
    // 讀一頁（cache miss 時自動從 SSD 載入）
    virtual RAMReadResult read(uint64_t page_id, double current_time);

    // 寫一頁（write-through：RAM 更新後立即寫回 SSD）
    virtual void write(uint64_t page_id,
                       const std::vector<uint8_t>& data,
                       double current_time);

    // 配置新頁：分配 page_id、寫 SSD、載入 RAM
    virtual uint64_t allocate(double current_time);

    // 釋放頁：清除 RAM slot + SSD trim
    virtual void free_page(uint64_t page_id);

    // 設定 TTL（冷頁逐出）——政策持久化，逐出重載後自動套用
    void set_ttl(uint64_t page_id, double ttl_seconds) override;

    // 自上次載入至今的駐留時間（曝露窗 T_reload）
    double residency(uint64_t page_id, double now) const override;

    // 主動逐出（積極 TTL 用）；計入 n_ttl_evictions
    bool evict(uint64_t page_id) override;

    // 指定位置的注入（FaultModel 用）
    bool flip_bit (uint64_t page_id, uint32_t byte, uint8_t bit) override;
    bool force_bit(uint64_t page_id, uint32_t byte, uint8_t bit, bool value) override;

    // 推進模擬時間（供 B-Tree::advance_time 呼叫）
    void advance_time(double dt) { current_time_ += dt; }

    // ── Error Injection ──────────────────────────────────────────
    // 1. 隨機翻 1 bit（任意 byte、任意 bit）
    void inject_random_flip(uint64_t page_id);

    // 2. 指定 bank 內連續 2 個 row 翻 flip_ratio 比例的 bit（模擬 row hammer）
    void inject_row_error(uint32_t bank,
                          uint32_t start_row,
                          double   flip_ratio = 0.5);

    // 3. 同一 bank 內連續 num_rows 個 row，各翻 (col_byte, bit) 這一個 bit
    //    模擬 bit line（column）永久故障
    void inject_column_error(uint32_t bank,
                             uint32_t start_row,
                             uint32_t col_byte,
                             uint8_t  bit,
                             uint32_t num_rows = 512);

    // 4. 單一 SECDED ECC word（ECC_WORD_BYTES = 8 bytes）內留下 num_flips 個翻轉
    //    ecc_word_offset：page 內第幾個 8-byte ECC word（0-based，0..511）
    //    num_flips=1 → 修正；=2 → UE；=3 → 誤修正（不會是 UE）
    //    粒度與 ECC_RAM 的 SECDED word 一致，翻轉保證落在同一個 word 內。
    void inject_ecc_word_error(uint64_t page_id,
                               uint32_t ecc_word_offset,
                               int      num_flips = 3);

    // ── 查詢 ────────────────────────────────────────────────────
    RAMStats    get_stats()                    const override { return stats_; }
    bool        is_in_ram(uint64_t page_id)    const;
    DRAMAddress get_phys_addr(uint64_t page_id) const { return to_phys(page_id); }
    uint32_t    capacity()  const { return DRAM_NUM_BANKS * config_.rows_per_bank; }
    uint32_t    occupied()  const;
    double      current_time() const { return current_time_; }

protected:
    std::mt19937 rng_;
    RAMConfig    config_;   // ECC_RAM 需要讀取 enable_verify 等欄位
    RAMStats     stats_;    // ECC_RAM 需要寫入 n_hw_corrected 等欄位

private:
    SSD*      ssd_;
    uint64_t  next_page_id_ = 0;
    double    current_time_ = 0.0;

    // 物理儲存：banks_[bank][row]
    std::vector<std::vector<RAMSlot>> banks_;

    // 動態映射：page_id → 目前所在的物理格（只含 in-RAM 的 page）
    std::unordered_map<uint64_t, DRAMAddress> page_to_slot_;

    // 持久化 TTL 政策：page_id → ttl_seconds
    // 與 page_to_slot_ 無關 —— 頁面被逐出後政策仍保留，重新載入時由
    // apply_ttl_policy() 套回 slot。只存有限 TTL 的頁（inf 代表移除條目）。
    std::unordered_map<uint64_t, double> ttl_policy_;

    // 載入／配置後把持久化的 TTL 政策套回 slot
    void apply_ttl_policy(uint64_t page_id);

    // 空閒物理格 pool
    std::queue<DRAMAddress> free_slots_;

    // ── 內部輔助 ────────────────────────────────────────────────
    DRAMAddress    to_phys(uint64_t page_id)     const;  // 查 page_to_slot_，page 不在 RAM 時丟例外
    uint64_t       to_page_id(DRAMAddress addr)  const;  // 查 owner_page_id
    RAMSlot&       slot(uint64_t page_id);
    const RAMSlot& slot(uint64_t page_id)        const;
    void           validate_page_id(uint64_t page_id) const;  // 檢查是否已分配（< next_page_id_）

    // TTL 懶惰檢查：若已過期則逐出並回傳 true
    bool check_ttl(uint64_t page_id, double t);

    // LRU：掃描所有 valid slot，逐出 last_access 最舊的
    void do_evict_lru(double t);

    // 從 SSD 讀入並填入 slot
    void do_load(uint64_t page_id, double t);

    // Poisson 取樣 bit flip 數（只計數，不修改 data）
    int  sample_flips(uint64_t page_id, double t);

    // 填入合法 SSD header（CRC32=0, page_size, version=0, byte_order=0）
    void fill_ssd_header(std::vector<uint8_t>& image) const;
};

// ── ECC_RAM ──────────────────────────────────────────────────────────────────
// SECDED（Single Error Correction, Double Error Detection）
// 每 64-bit word 儲存 8-bit Hamming parity，讀取時進行真實錯誤檢測與修正：
//   0-bit error  → OK
//   1-bit error  → 修正（CORRECTED）
//   2-bit error  → 偵測到，不修正（UNCORRECTABLE，回報 UE）
//   3-bit error  → syndrome 指向錯誤位置，誤修正（MISCORRECTED，靜默損壞）
//   偶數-bit     → 偵測為 UE（4-bit, 6-bit...）
// parity_ 不佔 RAMSlot 空間，獨立存放，模擬 ECC DIMM 的第 9 顆晶片
class ECC_RAM : public RAM {
public:
    using RAM::RAM;

    RAMReadResult read(uint64_t page_id, double current_time) override;
    void          write(uint64_t page_id,
                        const std::vector<uint8_t>& data,
                        double current_time) override;
    void          free_page(uint64_t page_id) override;

private:
    // page_id → parity bytes（每 8-byte word 對應 1 byte parity，共 PAGE_SIZE/8 bytes）
    std::unordered_map<uint64_t, std::vector<uint8_t>> parity_;
};
