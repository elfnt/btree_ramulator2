#pragma once
// shadow_store.hpp — 「可靠記憶體」模型：有限容量的 shadow metadata 存放區
//
// 模擬一小塊不受 bit flip 影響的記憶體（ECC SRAM / 暫存器檔）。
// 每個受保護的 page 佔一個 entry；entry 大小由 Scheme 決定
// （見 exp_config.hpp scheme_entry_bytes）。容量不足時由 Policy 決定去留。
#include <cstdint>
#include <unordered_map>
#include <vector>
#include <random>
#include "exp_config.hpp"

namespace bfx {
struct Metrics;

// ── 控制平面長度（CTRL_CRC 的涵蓋範圍、Task 2 的歸因分界）─────────────────────
//
//   ctrl_len = 16 (NodeHeader) + n_keys*8 (keys[])
//            + (node_type == internal ? (n_keys+1)*8 (children[]) : 0)
//
// 涵蓋範圍即 image[16 .. 16+ctrl_len)。internal 節點沒有 payload，故此範圍
// 等於整個節點內容；leaf 節點則排除 values[]（唯一的「normal data」）。
//
// ⚠️ 呼叫者的義務：`trusted_image` 必須是可信來源——
//    protect() 用「剛寫入的 image」、毀損歸因用 oracle。
//    絕不可傳入剛從 DRAM 讀回、可能已被 flip 汙染的 image：若 n_keys 本身被翻，
//    重算出的 ctrl_len 會指向錯誤範圍，驗證器就會漏掉它自己造成的毀損。
//
// 防禦性夾擠：node_type/n_keys 若離譜（可信來源理應不會），結果夾在
// [16, page_size-16]，確保永不越界。
uint32_t ctrl_len_of(const std::vector<uint8_t>& trusted_image, uint32_t page_size);

// 「活內容」長度：節點真正被讀到的位元組數（header + keys + values/children）
//
//   live_len = ctrl_len + (leaf ? n_keys*8 (values[]) : 0)
//
// image[16 .. 16+live_len) 之後到頁尾全是**未使用的補零 slack**：節點只填到
// n_keys 個 slot，order 上限與實際 fill 之間的差額永遠是零。
//
// 為什麼要分出來：DB 規模下 slack 佔了頁面很大一塊（order=253 但平均每葉
// 只裝 ~174 個 key），落在 slack 的 flip 與 oracle 相異、會被算成「毀損」，
// 但 B+ 樹永遠不會讀到那些位元組——**語意上完全無害**。若不把它從
// payload_only 裡拆出來，就會嚴重高估「不保護 values[] 所付出的代價」。
// 呼叫者的可信度義務同 ctrl_len_of。
uint32_t live_len_of(const std::vector<uint8_t>& trusted_image, uint32_t page_size);

// ── E16：頁內 CRC（INPAGE_CTRL / INPAGE_FULL）───────────────────────────────
// CRC32 存在 image[page_size-4, page_size)（little-endian），不佔可靠記憶體。
// 涵蓋 image[0, end)：
//   INPAGE_CTRL → end = min(16 + ctrl_len_of(image), page_size-4)
//                 （ctrl_len 由「手上這份 image」算：寫入時是可信 image，讀取時是
//                  讀回的 image——沒有凍結值可用，這正是與 CTRL_CRC 的差別）
//   INPAGE_FULL → end = page_size-4
// 夾擠保證涵蓋範圍永不觸及 CRC 欄位本身。
uint32_t inpage_cover_end(Scheme s, const std::vector<uint8_t>& image, uint32_t page_size);
uint32_t inpage_crc(Scheme s, const std::vector<uint8_t>& image, uint32_t page_size);
uint32_t inpage_stored_crc(const std::vector<uint8_t>& image, uint32_t page_size);
void     inpage_stamp(Scheme s, std::vector<uint8_t>& image, uint32_t page_size);
// true = 頁內 CRC 不符（偵測到毀損）
bool     inpage_mismatch(Scheme s, const std::vector<uint8_t>& image, uint32_t page_size);

struct ShadowEntry {
    uint32_t crc = 0;             // HDR_CRC: CRC over image[16..31]；FULL_CRC: CRC over 整頁；
                                  // CTRL_CRC: CRC over image[16 .. 16+ctrl_len)
    uint16_t ctrl_len = 0;        // CTRL_CRC 專用：protect() 時由可信 image 算出並凍結。
                                  // 驗證一律用這個值，不從讀回的 image 重算（見上方警告）。
    uint8_t  hdr[16] = {0};       // HDR_MIRROR: NodeHeader 完整鏡像
    uint8_t  level = 0;           // 節點層級（leaf=0，root 最高）
    uint64_t hotness = 0;         // 存取次數（BY_HOTNESS 用）
    uint64_t last_use_tick = 0;   // LRU 用（op 序號）
    double   last_verified_s = 0; // PERIODIC 驗證用
};

class ShadowStore {
public:
    // metrics 可為 nullptr（單元測試）；rng_seed 供 RANDOM policy。
    ShadowStore(const ExpConfig& cfg, Metrics* metrics, uint32_t rng_seed);

    // 寫入/更新保護資訊（於每次節點寫入、或成功復原後呼叫）。
    // image = 完整 4096B page image。回傳是否實際受保護。
    // 行為：
    //  - scheme NONE/SANITY：恆 false，不佔容量。
    //  - 已有 entry → 就地更新（不觸發逐出）。
    //  - 新 entry 且容量夠 → 收留。
    //  - 新 entry 且容量滿 → 依 Policy 決定：
    //      BY_LEVEL 新頁層級 > 現存最低層級才擠掉（victim=最低層級、同層最舊 tick），
    //               否則拒收；其他 policy 一律收留並逐出各自的 victim。
    //    被拒或逐出時 metrics->n_shadow_rejected++（每次一計）。
    bool protect(uint64_t page_id, const std::vector<uint8_t>& image,
                 uint8_t level, uint64_t tick);

    // 查詢；找到時 bump hotness 與 last_use_tick。無 → nullptr。
    ShadowEntry* lookup(uint64_t page_id, uint64_t tick);

    void erase(uint64_t page_id);

    uint64_t bytes_used() const;      // entries * entry_bytes
    uint32_t entry_bytes() const;
    bool     is_protected(uint64_t page_id) const;
    size_t   size() const;

    // 依 image 計算本 scheme 的校驗內容（protect / verify 共用同一實作）
    //   HDR_CRC  → fast_crc32(image[16..31])
    //   CTRL_CRC → fast_crc32(image[16 .. 16+ctrl_len))
    //   FULL_CRC → fast_crc32(整份 image)
    //   其他     → 0（HDR_MIRROR 直接比對；NONE/SANITY 無校驗）
    // bfx::fast_crc32 與 v2 pageCRC32 位元相同（driver 啟動自測保證）。
    //
    // ctrl_len 參數**刻意無預設值**：CTRL_CRC 的正確性完全繫於「用哪個長度」，
    // 給預設值會讓漏傳的呼叫點靜默地算出空範圍的 CRC（永不報警）。強制每個
    // 呼叫點明寫，編譯器就會抓出遺漏。非 CTRL_CRC 的 scheme 忽略此參數。
    // CTRL_CRC 且 ctrl_len < 16（= 連 NodeHeader 都蓋不到）視為呼叫端 bug → abort。
    static uint32_t crc_of(Scheme s, const std::vector<uint8_t>& image,
                           uint32_t ctrl_len);

private:
    const ExpConfig& cfg_;
    Metrics* metrics_;
    std::unordered_map<uint64_t, ShadowEntry> map_;
    std::mt19937 rng_;
    uint64_t capacity_entries_;   // budget_bytes / entry_bytes（entry 0 → 無限）
    bool evict_one(uint8_t incoming_level);   // 回傳是否騰出了位置
};

} // namespace bfx
