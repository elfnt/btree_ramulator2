#pragma once
// exp_btree.hpp — 實驗用 B+ 樹：鏡射 v2 BTree_core 的邏輯與節點格式，
// 但所有 I/O 走 GuardedRAM，並以 safe_parse 防止毀損 image 造成當機。
//
// 與 v2 BTree 的一致性要求：
//  - 節點格式 = BTreeNode::serialize / deserialize（image[16..31] NodeHeader）
//  - 分裂邏輯相同：leaf 對半、右半首 key 上推；internal 對半、中位 key 上推；
//    root 分裂長高。order_ = 節點最大 key 數，超過才分裂 → 落盤節點恆 ≤ order。
//  - 差異（刻意）：internal 節點的 next_leaf 一律明確寫 INVALID_PAGE
//    （v2 寫入未初始化值），使 sanity 檢查可用此不變量。
#include <cstdint>
#include <vector>
#include "../../BTree_core/btree_node.hpp"
#include "guarded_ram.hpp"

namespace bfx {

// 結構完整性檢查（SANITY 偵測器；也用於 would-crash 判定）。
// 回傳 true = 通過。檢查項目（全部不需可靠記憶體）：
//  1. node_type ∈ {0,1}
//  2. pad[3] 全零
//  3. n_keys ≤ order 且 32 + n_keys*8 + (leaf? n_keys : n_keys+1)*8 ≤ page_size
//  4. keys 嚴格遞增（工作負載只插入唯一 key）
//  5. internal：children 皆 < pages_allocated 且 ≠ 自身 page_id；
//     next_leaf == INVALID_PAGE
//  6. leaf：next_leaf < pages_allocated 或 == INVALID_PAGE
// fatal_out = true 表示連解析都不安全（違反第 1 或 3 項）。
// E18/E19 延伸（nullptr 或全預設 = 舊行為，逐位元組相同）：
//   align_log2 > 0：每個 key 的低 align_log2 位必為 0（leaf 與 internal）。
//     slack = true 時，leaf 中 value == GUARD_SENTINEL_VALUE 的 entry 是 slack dummy
//     （K±1，K 已對齊）→ 其低位必為 1 或全 1（mask）。
struct SanityExt {
    uint32_t align_log2 = 0;
    bool     slack      = false;
};
bool sanity_check(const std::vector<uint8_t>& image, uint64_t self_page_id,
                  uint32_t order, uint32_t page_size, uint64_t pages_allocated,
                  bool& fatal_out, const SanityExt* ext = nullptr);

// ── E17：parent–child 範圍檢查 ──────────────────────────────────────────────
// 下降時由「剛讀到的父節點」的分隔鍵界定子節點的合法範圍 [lo, hi)（未界定的一側
// 沿用父節點自己的界限，root 兩側皆無界）。不變量（本樹無刪除）：
//   leaf     ：若 lo 有界，第一個真 key == lo（leaf 分裂把右葉首 key 複製上推，
//              之後小於 lo 的 key 不會被路由進來）；最後一個真 key < hi。
//   internal ：第一個 key > lo（internal 分裂把中位 key 上推，右半的 keys 皆大於它）；
//              最後一個 key < hi。
//   node_type 必須符合預期層級（level 0 = leaf）。
// 每個界限記住提供它的頁（src），報警時連同直接父節點一起從 SSD 重載。
struct RangeSrc {
    uint64_t pid   = UINT64_MAX;    // UINT64_MAX = 無
    uint8_t  level = 0;
    bool     bad   = false;         // 該節點被 tree 持有的內容 ≠ oracle（評分用）
};
struct ChildBounds {
    bool     has_lo = false, has_hi = false;
    uint64_t lo = 0, hi = 0;
    RangeSrc lo_src, hi_src, parent;
    bool     expect_leaf = false;
};
// image 必須已通過 sanity_check（佈局可安全讀取）。slack = leaf 中 value == sentinel 者
// 為 dummy、不參與範圍判斷。回傳 true = 通過。
bool range_check(const std::vector<uint8_t>& image, const ChildBounds& b, bool slack);
// 父節點 parent（已剝除 dummy 的邏輯節點）第 i 個 child 的界限
ChildBounds child_bounds(const BTreeNode& parent, size_t i, const ChildBounds& pb,
                         const RangeSrc& parent_src, uint8_t child_level);

// ── E19：leaf slack dummy 編碼/解碼 ─────────────────────────────────────────
// 邏輯 leaf（只含真 entry）→ 實體 leaf：空 slot（order − n）填 K+1（right）或
// K−1/K+1（both），value = GUARD_SENTINEL_VALUE；與鄰居相撞者略過；候選多於空 slot
// 時以 floor(j·m/free) 均勻挑選。滿的 node 不加 dummy。
BTreeNode add_slack_dummies(const BTreeNode& logical, uint32_t order, SlackGuard g);
// 剝除 value == GUARD_SENTINEL_VALUE 的 entry（leaf 才做）
void strip_slack_dummies(BTreeNode& node);

class ExpBTree {
public:
    ExpBTree(GuardedRAM* gram, uint32_t order, uint32_t page_size);

    // op_latency_out：本次操作的模擬延遲總和（read+write+驗證+復原）。
    // search 內部流程：沿途每個節點經 gram_->read()；
    //  - 讀取結果若 sanity fatal 且未被偵測 → gram_->crash_rescue() 後重試該節點
    //    （最多 2 次，仍壞則放棄本 op，回傳 false）
    //  - 追蹤本 op 是否出現過 FN 讀（fn_seen()，供 poisoned write 判定）
    //    與任何報警（alarm_seen()，供 driver 判定 SDC）
    bool search(uint64_t key, uint64_t& value_out, double& op_latency_out);
    void insert(uint64_t key, uint64_t value, double& op_latency_out);
    // E21：同 search，另回傳命中的 leaf page，以及同一 leaf 內緊鄰的下一個 entry
    // 是否為 key+1（是 → next_value_out 為其 value；一次走訪取兩個 entry）。
    bool search_pair(uint64_t key, uint64_t& value_out, double& op_latency_out,
                     uint64_t& leaf_page_out, bool& next_adjacent_out,
                     uint64_t& next_value_out);
    // E21：上層報警 → 從 SSD 重載該頁（計 n_recoveries）並標記本 op 已報警
    void reload_page(uint64_t page_id, uint8_t level, double& op_latency_out);

    void   advance_time(double dt);
    double now() const { return current_time_; }
    uint32_t height() const { return height_; }   // leaf-only 樹 = 1

    // ── 每層節點數（E2b′–E2e′ 的儀器）───────────────────────────────────────
    //
    // 為什麼可以用「配置時的層級」當作永久標籤：B+ 樹中一個節點「離葉子有多高」
    // 是不變量——分裂只會產生同層的兄弟，長高只會在頂端加一層新的 root，
    // 既有節點與葉子的距離不變。level 慣例（leaf = 0）正是這個高度，
    // 因此 allocate 當下記一筆、之後永不更新，即等於期末的每層節點數。
    // 本實驗無刪除，故「配置次數」== 「存活節點數」，
    // Σ level_count(l) 必然 == GuardedRAM::pages_allocated()（driver 每個 run 檢查
    // 並印 LEVELCHK 一行；不成立時印 FAIL，掃描腳本可 grep）。
    static constexpr int MAX_LEVELS = 8;
    uint64_t level_count(int l) const {
        return (l >= 0 && l < MAX_LEVELS) ? level_counts_[l] : 0;
    }
    // 配置時層級 ≥ MAX_LEVELS 的節點數（正常組態恆為 0；非零代表 CSV 的
    // 逐層欄位不完整，driver 會據此警告）。
    uint64_t level_overflow() const { return level_overflow_; }

    // 獨立的結構驗算：以 GuardedRAM 的 **oracle**（= 每頁最後一次成功寫入的
    // 內容）走訪整棵樹，重新數出每層節點數。走訪不經 gram_->read()，
    // 因此不注入、不計延遲、不動任何 metrics——純粹是給資料品質檢查用的
    // 第二個獨立來源，用來抓「配置計數器」本身的錯誤。
    // 回傳 false = 走訪過程遇到異常（越界 child、重複造訪、層級溢位），
    // 此時 out[] 仍填入已數到的部分。
    bool walk_level_counts(uint64_t out[MAX_LEVELS], uint32_t& max_level_out) const;

    // E19：以 oracle 走訪所有 leaf，統計真 key 數、帶右/左 dummy 的真 key 數、dummy 數
    // E17 診斷（只印 stderr）：以 oracle 走訪，數出違反範圍不變量的節點數
    uint64_t oracle_range_violations() const;
    void slack_scan(uint64_t& real, uint64_t& with_right, uint64_t& with_left,
                    uint64_t& dummies) const;

    // 本 op 內是否發生過「truth corrupt 且未偵測」的讀取；note_op_boundary 清零
    bool fn_seen_this_op() const { return fn_seen_; }
    // 本 op 內是否有任何一次 guarded read 報警；note_op_boundary 清零。
    // n_wrong_undetected（metrics.hpp：結果錯且全程無報警）以此判定，
    // 與 fn_seen 不同：跨 op 的持久毀損（oracle 已被污染）讀取 truth=false，
    // 不算 FN，但只要全程無報警、結果又錯，仍是真 SDC。
    bool alarm_seen_this_op() const { return alarm_seen_; }
    void note_op_boundary();   // 轉呼 gram_->note_op_boundary() 並清 fn_seen_/alarm_seen_

private:
    GuardedRAM* gram_;
    uint64_t root_page_id_;
    uint32_t order_, page_size_;
    uint32_t height_ = 1;
    double   current_time_ = 0.0;
    bool     fn_seen_ = false;
    bool     alarm_seen_ = false;
    uint64_t level_counts_[MAX_LEVELS] = {0};
    uint64_t level_overflow_ = 0;
    // 每次 gram_->allocate() 之後、以該新節點的 level 呼叫一次
    void note_alloc(uint8_t level) {
        if (level < MAX_LEVELS) ++level_counts_[level];
        else                    ++level_overflow_;
    }

    // level 慣例：leaf = 0；某節點的 level = height_ - 1 - 目前深度。
    BTreeNode read_node(uint64_t page_id, uint8_t level, bool& ok,
                        const ChildBounds* b = nullptr, bool* held_bad = nullptr);
    void      write_node(const BTreeNode& node, uint8_t level);
    void      fill_ssd_header(std::vector<uint8_t>& image) const;
    void insert_recursive(uint64_t node_id, uint8_t level, uint64_t key, uint64_t value,
                          bool& did_split, uint64_t& split_key, uint64_t& split_page,
                          const ChildBounds& b);
    bool search_pass(uint64_t key, uint64_t& value_out, bool& found);
    void split_leaf    (BTreeNode& leaf, uint64_t& new_key, uint64_t& new_page);
    void split_internal(BTreeNode& node, uint64_t& new_key, uint64_t& new_page);
};

} // namespace bfx
