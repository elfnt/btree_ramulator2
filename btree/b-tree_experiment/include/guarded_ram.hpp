#pragma once
// guarded_ram.hpp — 保護層核心：驗證讀取、分類 TP/FP/FN/TN、SSD 重載復原
//
// 包裝 v2 的 RAM 與 SSD（純 API 呼叫，零修改）。同時維護 oracle
// （每頁「應有內容」= 最後一次成功寫入的 image）作為地面真相，
// oracle 只用於評分，絕不影響保護層的決策路徑。
//
// 關鍵性質：RAM 是 write-through，SSD 上永遠是最後寫入的內容；
// 注入只改 DRAM。因此「從 SSD 重載」= 乾淨復原——除非毀損曾以
// 寫回的方式污染 SSD（poisoned write，本層在寫入路徑計量它）。
#include <cstdint>
#include <unordered_map>
#include <vector>
#include "../../new_RAM_core/new_ram.hpp"
#include "exp_config.hpp"
#include "shadow_store.hpp"
#include "metrics.hpp"

namespace bfx {

struct ChildBounds;   // exp_btree.hpp（E17）

struct GuardedReadResult {
    std::vector<uint8_t> data;   // 交給上層的 image（偵測到毀損時已是復原後內容）
    double latency_s = 0.0;
    bool truth_corrupt = false;  // 評分用（oracle 比對）
    bool detected      = false;  // 保護層是否報警
    bool recovered     = false;
    bool range_alarm   = false;  // E17：報警來自 parent–child 範圍檢查
    bool returned_corrupt = false; // 交回的 data ≠ oracle（評分用：未偵測的毀損）
};

// ── 讀取政策擴充點（供 ttl_theta_experiment 使用）─────────────────────────────
//
// 預設為 nullptr，此時 GuardedRAM 的行為與原本完全相同（E1–E6 不受影響）。
//
// 存在的理由：TTL 實驗需要兩件 GuardedRAM 內部才知道的事——
//   1. 依頁面的冷熱分類決定「這次讀取要不要驗證」（arm A1/A3 的 cold 免驗證）
//   2. 依冷熱分別累計混淆矩陣（P_s_hot / P_s_cold，RQ1 的主指標）
// 兩者都無法從外層觀察：驗證發生在 read() 內部，而 metrics 的記帳看不到 page_id。
//
// 用回呼而非「把 read() 虛擬化再繼承」，是為了避免在子類裡複製整段驗證流程
// ——那會隨時間與本檔分歧。
struct ReadPolicy {
    virtual ~ReadPolicy() = default;

    // 回傳 true → 本次讀取跳過可靠記憶體驗證（延遲也不計）
    virtual bool skip_verify(uint64_t /*page_id*/) const { return false; }

    // 每次 guarded read 記帳後回呼。
    //   verified = 本次是否真的執行了驗證（cadence 允許且未被 skip_verify 擋下）
    virtual void on_read(uint64_t /*page_id*/, bool /*truth_corrupt*/,
                         bool /*predicted*/, bool /*verified*/, double /*t*/) {}
};

// E13：leaf image（可信來源，如 oracle）的第 slot 個 key 是否為 dummy
// （其 value == GUARD_SENTINEL_VALUE）。越界 → false。
bool leaf_slot_is_dummy(const std::vector<uint8_t>& leaf_image, int slot);

class GuardedRAM {
public:
    // ssd 可為 nullptr（r2 後端無 SSD；crash_rescue 改用 ram->read 回退）
    GuardedRAM(IRAM* ram, SSD* ssd, ShadowStore* shadow,
               Metrics* metrics, const ExpConfig* cfg);

    // 配新頁（轉呼 ram->allocate；oracle 記為「全零 + 合法 SSD header」的
    // 初始 image，與 RAM::allocate 寫入 SSD 的內容一致）。
    // 回傳 page_id；latency_out += t_ssd + t_mem。
    uint64_t allocate(double t, double& latency_out);

    // 受保護讀取。流程（順序固定）：
    //  1. r = ram->read(page,t)；lat = r.latency
    //  2. truth = (r.data != oracle[page])（評分，零成本）
    //  2b. truth 為真時，以 oracle 的 ctrl_len 為界做位元組級歸因，累計
    //      metrics->n_corrupt_reads_{ctrl_only,payload_only,mixed,ssd_header}
    //      （四類互斥窮盡，總和 == tp + fn；純評分，不影響偵測決策）
    //  3. 偵測（predicted 初值 false）：
    //     a. scheme 為 CRC/MIRROR 類且 shadow 有 entry 且 cadence 允許
    //        （EVERY_READ 恆允許；PERIODIC 需 t - last_verified_s > theta_s，
    //          驗後更新 last_verified_s）：
    //          HDR_CRC   → lat += t_reliable + 16*t_crc_per_byte；比對 crc_of
    //          CTRL_CRC  → lat += t_reliable + entry.ctrl_len*t_crc_per_byte；
    //                      比對 crc_of(…, entry.ctrl_len)——**用 entry 凍結的
    //                      ctrl_len**，不從讀回的 image 重算（見 exp_config.hpp）
    //          FULL_CRC  → lat += t_reliable + 4096*t_crc_per_byte；比對 crc_of
    //          HDR_MIRROR→ lat += t_reliable；memcmp(image[16..31], entry.hdr)
    //        不符 → predicted = true
    //     b. scheme==SANITY 或 sanity_always：lat += t_sanity；
    //        結構檢查失敗（見 exp_btree.hpp safe_parse）→ predicted = true
    //  4. metrics->page_read.add(truth, predicted)；n_guarded_reads++；
    //     shadow 有 entry → n_protected_reads++
    //  5. predicted → 復原：ssd->read(LA) 取乾淨副本（lat += t_ssd），
    //     ram->write(page, clean, t) 修復 DRAM（lat += t_mem；此呼叫附帶的
    //     write-through 是無害的同內容重寫，不另計延遲），
    //     shadow->protect(...) 以乾淨 image 刷新 entry，n_recoveries++，
    //     回傳 clean。
    //  6. 未報警 → 原樣回傳 r.data（可能是 FN，交由上層與端到端指標承接）。
    //  E17：bounds != nullptr 且 cfg.sanity_range 且結構檢查通過時，另做 range_check；
    //  違反 → predicted = true（同 SANITY 報警，走步驟 5 的復原），range_alarm = true。
    GuardedReadResult read(uint64_t page_id, double t, uint8_t level,
                           const ChildBounds* bounds = nullptr);

    // E17：範圍報警時重載祖先節點（同步驟 5 的復原：t_ssd + t_mem，n_recoveries++）
    void recover_from_ssd(uint64_t page_id, double t, uint8_t level, double& latency_out);
    void note_range_parent(bool parent_bad) { if (parent_bad) metrics_->n_range_parent_bad++; }
    void note_range_restart() { metrics_->n_range_restarts++; }
    void note_range_giveup()  { metrics_->n_range_giveups++; }

    // 受保護寫入（上層節點序列化後呼叫）：
    //  oracle[page] = image；shadow->protect(page, image, level, tick)；
    //  ram->write(page, image, t)；回傳延遲 = t_mem + t_ssd（write-through）
    //  + t_reliable + scheme 的校驗計算成本（protect 時需算 CRC）。
    //  derived_from_fn = 本 op 稍早曾發生 FN 讀 → metrics->n_poisoned_writes++
    //  （毀損可能已混入 image 並將永久化——這正是要量測的污染事件）。
    double write(uint64_t page_id, const std::vector<uint8_t>& image,
                 double t, uint8_t level, bool derived_from_fn);

    // 未偵測且結構毀損到無法安全解析時，上層呼叫此函數模擬
    // fail-stop + 重啟：強制從 SSD 重載（同步驟 5——含無條件 protect()，
    // 但計 n_would_crash 而非混淆矩陣——分類已在 read() 記過 FN）。
    // 回傳復原後 image；latency 累加。
    std::vector<uint8_t> crash_rescue(uint64_t page_id, double t, uint8_t level,
                                      double& latency_out);

    // E21：上層（key 映射一致性檢查）報警後的 SSD 重載。同 read() 步驟 5，
    // 計 n_recoveries（不是 n_would_crash）。不碰混淆矩陣。
    std::vector<uint8_t> reload_clean(uint64_t page_id, double t, uint8_t level,
                                      double& latency_out);

    // 給 FaultInjector：目前「已配置且在 RAM 內」的頁清單
    std::vector<uint64_t> resident_pages() const;
    // E11：依層級過濾（ALL == resident_pages()）
    std::vector<uint64_t> resident_pages_filtered(InjectLevel f) const;

    const std::vector<uint8_t>& oracle(uint64_t page_id) const;
    uint64_t pages_allocated() const { return next_hint_; }
    const ExpConfig& config() const { return *cfg_; }   // E16：ExpBTree 需知 scheme 以 stamp 頁內 CRC
    void     note_op_boundary();      // op 序號 +1（LRU tick / poisoned 判定範圍）
    uint64_t tick() const { return tick_; }

    // 設定讀取政策（nullptr = 預設行為）。見上方 ReadPolicy 說明。
    void set_read_policy(ReadPolicy* p) { policy_ = p; }

private:
    IRAM* ram_; SSD* ssd_; ShadowStore* shadow_; Metrics* metrics_;
    const ExpConfig* cfg_;
    ReadPolicy* policy_ = nullptr;
    std::unordered_map<uint64_t, std::vector<uint8_t>> oracle_;
    std::vector<int8_t> level_of_;   // E11：page_id → level（-1 = 未寫入）
    uint64_t next_hint_ = 0;   // 已配置頁數（= 歷來 allocate 次數）
    uint64_t tick_ = 0;
};

} // namespace bfx
