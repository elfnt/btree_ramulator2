#include "exp_btree.hpp"
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>

namespace bfx {

// ── sanity_check ─────────────────────────────────────────────────────────────

bool sanity_check(const std::vector<uint8_t>& image, uint64_t self_page_id,
                  uint32_t order, uint32_t page_size, uint64_t pages_allocated,
                  bool& fatal_out, const SanityExt* ext) {
    fatal_out = false;
    if (image.size() < 32) { fatal_out = true; return false; }   // 連 header 都放不下

    const uint8_t* p = image.data();
    uint8_t  node_type = p[16];
    uint32_t n_keys;
    uint64_t next_leaf;
    std::memcpy(&n_keys,    p + 20, 4);
    std::memcpy(&next_leaf, p + 24, 8);

    // 1. node_type ∈ {0,1}（fatal：決定佈局的欄位不可信）
    if (node_type > 1) { fatal_out = true; return false; }
    const bool leaf = (node_type == 1);

    // 3. n_keys 邊界（fatal：陣列越界不可讀）
    const uint64_t limit = std::min<uint64_t>(page_size, image.size());
    const uint64_t arr2  = uint64_t(n_keys) + (leaf ? 0 : 1);
    if (n_keys > order || 32 + uint64_t(n_keys) * 8 + arr2 * 8 > limit) {
        fatal_out = true;
        return false;
    }

    // 2. pad 全零
    if (p[17] | p[18] | p[19]) return false;

    // 4. keys 嚴格遞增
    const uint8_t* kp = p + 32;
    uint64_t prev = 0;
    for (uint32_t i = 0; i < n_keys; ++i) {
        uint64_t k;
        std::memcpy(&k, kp + uint64_t(i) * 8, 8);
        if (i > 0 && k <= prev) return false;
        prev = k;
    }

    // 4b. E18：對齊（key 為 2^k 的倍數；slack dummy 為 K±1）
    if (ext && ext->align_log2 > 0) {
        const uint64_t mask = (ext->align_log2 >= 64) ? ~0ull : ((1ull << ext->align_log2) - 1);
        const uint8_t* vp = kp + uint64_t(n_keys) * 8;   // leaf 的 values[]（n_keys 已驗界）
        for (uint32_t i = 0; i < n_keys; ++i) {
            uint64_t k;
            std::memcpy(&k, kp + uint64_t(i) * 8, 8);
            const uint64_t low = k & mask;
            if (low == 0) continue;
            bool dummy = false;
            if (leaf && ext->slack) {
                uint64_t v;
                std::memcpy(&v, vp + uint64_t(i) * 8, 8);
                dummy = (v == GUARD_SENTINEL_VALUE);
            }
            if (!(dummy && (low == 1 || low == mask))) return false;
        }
    }

    if (!leaf) {
        // 5. internal：children 在範圍內且不指向自己；next_leaf 恆 INVALID_PAGE
        const uint8_t* cp = kp + uint64_t(n_keys) * 8;
        for (uint32_t i = 0; i <= n_keys; ++i) {
            uint64_t c;
            std::memcpy(&c, cp + uint64_t(i) * 8, 8);
            if (c >= pages_allocated || c == self_page_id) return false;
        }
        if (next_leaf != INVALID_PAGE) return false;
    } else {
        // 6. leaf：next_leaf 在範圍內或為串列尾
        if (next_leaf != INVALID_PAGE && next_leaf >= pages_allocated) return false;
    }
    return true;
}

// ── E17：range_check / child_bounds ─────────────────────────────────────────

bool range_check(const std::vector<uint8_t>& image, const ChildBounds& b, bool slack) {
    const uint8_t* p = image.data();
    const bool leaf = (p[16] == 1);
    if (leaf != b.expect_leaf) return false;            // 指標被導向錯誤層級的頁
    uint32_t n;
    std::memcpy(&n, p + 20, 4);
    const uint8_t* kp = p + 32;
    const uint8_t* vp = kp + uint64_t(n) * 8;
    auto key = [&](uint32_t i) { uint64_t k; std::memcpy(&k, kp + uint64_t(i) * 8, 8); return k; };
    auto real = [&](uint32_t i) {
        if (!leaf || !slack) return true;
        uint64_t v; std::memcpy(&v, vp + uint64_t(i) * 8, 8);
        return v != GUARD_SENTINEL_VALUE;
    };
    // 第一個 / 最後一個「真」key（keys 已知嚴格遞增 → 首尾即足）
    int64_t first = -1, last = -1;
    for (uint32_t i = 0; i < n; ++i) if (real(i)) { first = i; break; }
    for (int64_t i = (int64_t)n - 1; i >= 0; --i) if (real((uint32_t)i)) { last = i; break; }
    if (first < 0) return !(b.has_lo || b.has_hi);       // 非 root 節點不可能是空的
    const uint64_t kf = key((uint32_t)first), kl = key((uint32_t)last);
    if (b.has_lo) {
        if (leaf ? (kf != b.lo) : (kf <= b.lo)) return false;
    }
    if (b.has_hi && kl >= b.hi) return false;
    return true;
}

ChildBounds child_bounds(const BTreeNode& parent, size_t i, const ChildBounds& pb,
                         const RangeSrc& parent_src, uint8_t child_level) {
    ChildBounds c;
    if (i > 0) { c.has_lo = true; c.lo = parent.keys[i - 1]; c.lo_src = parent_src; }
    else       { c.has_lo = pb.has_lo; c.lo = pb.lo; c.lo_src = pb.lo_src; }
    if (i < parent.keys.size()) { c.has_hi = true; c.hi = parent.keys[i]; c.hi_src = parent_src; }
    else       { c.has_hi = pb.has_hi; c.hi = pb.hi; c.hi_src = pb.hi_src; }
    c.parent = parent_src;
    c.expect_leaf = (child_level == 0);
    return c;
}

// ── E19：slack dummies ──────────────────────────────────────────────────────

BTreeNode add_slack_dummies(const BTreeNode& logical, uint32_t order, SlackGuard g) {
    const size_t n = logical.keys.size();
    if (g == SlackGuard::NONE || !logical.is_leaf() || n == 0 || n >= order) return logical;
    const size_t free_slots = order - n;
    const std::vector<uint64_t>& K = logical.keys;
    // 候選（依排序順序；與真 key 或前一個候選相撞者略過）
    std::vector<uint64_t> cand;
    cand.reserve(2 * n);
    for (size_t i = 0; i < n; ++i) {
        if (g == SlackGuard::BOTH && K[i] != 0) {
            const uint64_t d = K[i] - 1;
            const bool ok = (i == 0 || d > K[i - 1]) && (cand.empty() || d > cand.back());
            if (ok) cand.push_back(d);
        }
        if (K[i] != UINT64_MAX) {
            const uint64_t d = K[i] + 1;
            if (i + 1 == n || d < K[i + 1]) cand.push_back(d);
        }
    }
    std::vector<uint64_t> sel;
    const size_t m = cand.size();
    if (m <= free_slots) sel = cand;
    else {
        sel.reserve(free_slots);
        for (size_t j = 0; j < free_slots; ++j) sel.push_back(cand[(j * m) / free_slots]);
    }
    BTreeNode out = logical;
    out.keys.clear(); out.values.clear();
    out.keys.reserve(n + sel.size()); out.values.reserve(n + sel.size());
    size_t a = 0, d = 0;
    while (a < n || d < sel.size()) {
        if (d >= sel.size() || (a < n && K[a] < sel[d])) {
            out.keys.push_back(K[a]); out.values.push_back(logical.values[a]); ++a;
        } else {
            out.keys.push_back(sel[d]); out.values.push_back(GUARD_SENTINEL_VALUE); ++d;
        }
    }
    return out;
}

void strip_slack_dummies(BTreeNode& node) {
    if (!node.is_leaf()) return;
    size_t w = 0;
    for (size_t i = 0; i < node.keys.size() && i < node.values.size(); ++i) {
        if (node.values[i] == GUARD_SENTINEL_VALUE) continue;
        node.keys[w] = node.keys[i]; node.values[w] = node.values[i]; ++w;
    }
    node.keys.resize(w); node.values.resize(w);
}

// ── ExpBTree ─────────────────────────────────────────────────────────────────

namespace {

// 私有輔助的簽名（見標頭）沒有延遲/中止通道；模擬為單執行緒，
// 以檔案層級的 op 內容器傳遞。search/insert 進入時由 OpScope 綁定並重置。
struct OpState {
    double* lat = nullptr;    // 本 op 的延遲累加器（constructor 期間 nullptr → 捨棄）
    bool    abort = false;    // insert 中途放棄（毀損重試仍失敗）
    int     depth = 0;        // insert 遞迴深度（毀損指標成環保險）
    uint8_t cur_level = 0;    // split_internal 用（其簽名無 level 參數）
    bool    restart = false;  // E17：範圍報警 → 從 root 重新下降
    int     n_restarts = 0;   // 本 op 已重新下降次數
    bool    range_off = false;// 重試用盡 → 本 op 其餘讀取不再做範圍檢查
};
OpState g_op;

struct OpScope {
    explicit OpScope(double* lat) { g_op = OpState{}; g_op.lat = lat; }
    ~OpScope() { g_op = OpState{}; }
};

inline void add_lat(double s) { if (g_op.lat) *g_op.lat += s; }

} // namespace

ExpBTree::ExpBTree(GuardedRAM* gram, uint32_t order, uint32_t page_size)
    : gram_(gram), root_page_id_(0), order_(order), page_size_(page_size)
{
    double discard = 0.0;
    root_page_id_ = gram_->allocate(current_time_, discard);
    note_alloc(0);                      // 高度 1 的樹：root 就是 leaf → level 0

    BTreeNode root{};
    root.page_id   = root_page_id_;
    root.node_type = 1;                 // 高度 1 → root 即 leaf
    root.next_leaf = INVALID_PAGE;
    write_node(root, 0);
}

// fatal 毀損且未被偵測 → fail-stop 重載後重試一次；仍壞則 ok=false
BTreeNode ExpBTree::read_node(uint64_t page_id, uint8_t level, bool& ok,
                             const ChildBounds* b, bool* held_bad) {
    const ExpConfig& cfg = gram_->config();
    const ChildBounds* rb = (cfg.sanity_range && !g_op.range_off) ? b : nullptr;
    for (int attempt = 0; attempt < 2; ++attempt) {
        GuardedReadResult r = gram_->read(page_id, current_time_, level, rb);
        add_lat(r.latency_s);
        fn_seen_    |= (r.truth_corrupt && !r.detected);
        alarm_seen_ |= r.detected;

        bool fatal = false;
        sanity_check(r.data, page_id, order_, page_size_,
                     gram_->pages_allocated(), fatal);
        if (!fatal) {
            // 非 fatal 違規仍可安全解析；後果由偵測層與端到端指標承接
            ok = true;
            if (held_bad) *held_bad = r.returned_corrupt;
            if (r.range_alarm) {
                // E17：無法分辨父或子誰壞 → 子節點已在 read() 內重載；
                // 這裡重載直接父節點與提供界限的祖先，然後從 root 重新下降。
                const RangeSrc* srcs[3] = {&rb->parent, &rb->lo_src, &rb->hi_src};
                uint64_t done[3]; int nd = 0; bool pbad = false;
                for (const RangeSrc* sp : srcs) {
                    if (sp->pid == UINT64_MAX) continue;
                    bool dup = false;
                    for (int j = 0; j < nd; ++j) dup |= (done[j] == sp->pid);
                    if (dup) continue;
                    done[nd++] = sp->pid;
                    pbad |= sp->bad;
                    double lat = 0.0;
                    gram_->recover_from_ssd(sp->pid, current_time_, sp->level, lat);
                    add_lat(lat);
                }
                gram_->note_range_parent(pbad);
                if (g_op.n_restarts < 2) { g_op.restart = true; ++g_op.n_restarts; gram_->note_range_restart(); }
                else                     { g_op.range_off = true; gram_->note_range_giveup(); }
            }
            BTreeNode node = BTreeNode::deserialize(page_id, r.data);
            if (cfg.slack_guard != SlackGuard::NONE) strip_slack_dummies(node);
            return node;
        }
        if (attempt == 0 && !r.detected) {
            double lat = 0.0;
            gram_->crash_rescue(page_id, current_time_, level, lat);
            add_lat(lat);
        }
    }
    ok = false;
    return BTreeNode{};
}

void ExpBTree::write_node(const BTreeNode& node, uint8_t level) {
    // internal 的 next_leaf 一律落盤 INVALID_PAGE（sanity 不變量；v2 寫入未初始化值）
    BTreeNode out = node;
    if (!out.is_leaf()) out.next_leaf = INVALID_PAGE;
    const SlackGuard sg = gram_->config().slack_guard;
    if (sg != SlackGuard::NONE && out.is_leaf()) out = add_slack_dummies(out, order_, sg);

    std::vector<uint8_t> image(page_size_, 0);
    fill_ssd_header(image);
    out.serialize(image);

    // E16：頁內 CRC 存在最後 4 B。先證明該處未被節點佔用：
    //   leaf 用 32 + n*16 ≤ 4080、internal 用 32 + n*8 + (n+1)*8 ≤ 4088（n ≤ 253）。
    // stamp 在 serialize 之後 → oracle、DRAM、SSD 三份都帶同一個 CRC。
    const Scheme sch = gram_->config().scheme;
    if (is_inpage(sch)) {
        const uint64_t nk   = out.keys.size();
        const uint64_t used = 32 + nk * 8 + (out.is_leaf() ? nk : nk + 1) * 8;
        bool tail_zero = true;
        for (uint32_t i = page_size_ - 4; i < page_size_; ++i) tail_zero &= (image[i] == 0);
        if (used > page_size_ - 4 || !tail_zero) {
            std::fprintf(stderr, "FATAL: INPAGE tail not free (used=%llu, page_size=%u)\n",
                         (unsigned long long)used, page_size_);
            std::abort();
        }
        inpage_stamp(sch, image, page_size_);
    }
    add_lat(gram_->write(out.page_id, image, current_time_, level, fn_seen_));
}

void ExpBTree::fill_ssd_header(std::vector<uint8_t>& image) const {
    uint32_t zero = 0;
    std::memcpy(image.data() + 0,  &zero,       4);  // CRC32 = 0
    std::memcpy(image.data() + 4,  &page_size_, 4);  // page_size_bytes
    std::memcpy(image.data() + 8,  &zero,       4);  // version = 0
    std::memcpy(image.data() + 12, &zero,       4);  // byte_order = 0
}

bool ExpBTree::search(uint64_t key, uint64_t& value_out, double& op_latency_out) {
    OpScope scope(&op_latency_out);
    for (;;) {
        g_op.restart = false;
        bool found = false;
        if (search_pass(key, value_out, found)) return found;
        // E17：範圍報警 → 父子已重載，從 root 重新下降（次數由 read_node 限制）
    }
}

// 回傳 true = 本次下降已有結論（found 為結果）；false = 需從 root 重來
bool ExpBTree::search_pass(uint64_t key, uint64_t& value_out, bool& found) {
    found = false;
    uint64_t cur   = root_page_id_;
    uint8_t  level = static_cast<uint8_t>(height_ - 1);
    ChildBounds cb;                    // root：兩側無界
    cb.expect_leaf = (level == 0);

    // 健康樹的下降剛好 height_ 個節點；毀損指標可能成環 → 以 height_ 為界
    for (uint32_t depth = 0; depth < height_; ++depth) {
        uint64_t next = INVALID_PAGE;
        ChildBounds next_cb;

        for (int attempt = 0; attempt < 2; ++attempt) {
            bool ok = false, hb = false;
            BTreeNode node = read_node(cur, level, ok, &cb, &hb);
            if (!ok) return true;
            if (g_op.restart) return false;

            if (node.is_leaf()) {
                for (size_t i = 0; i < node.keys.size(); ++i)
                    if (node.keys[i] == key) { value_out = node.values[i]; found = true; return true; }
                return true;
            }

            size_t i = 0;
            while (i < node.keys.size() && key >= node.keys[i]) ++i;
            uint64_t child = node.children[i];
            if (child < gram_->pages_allocated()) {
                next = child;
                RangeSrc me; me.pid = cur; me.level = level; me.bad = hb;
                next_cb = child_bounds(node, i, cb, me, level > 0 ? (uint8_t)(level - 1) : 0);
                break;
            }

            // 野指標 = 真實系統的當機點：fail-stop 重載後重試本節點一次
            if (attempt == 0) {
                double lat = 0.0;
                gram_->crash_rescue(cur, current_time_, level, lat);
                add_lat(lat);
            }
        }
        if (next == INVALID_PAGE) return true;    // 重試仍壞 → 放棄本 op
        cur = next;
        cb  = next_cb;
        if (level > 0) --level;
    }
    return true;                                  // 走滿 height_ 層仍非 leaf → 放棄
}

// E21：search 的副本（不改動 search 本身，保持既有 run 逐位元組不變）
bool ExpBTree::search_pair(uint64_t key, uint64_t& value_out, double& op_latency_out,
                           uint64_t& leaf_page_out, bool& next_adjacent_out,
                           uint64_t& next_value_out) {
    OpScope scope(&op_latency_out);
    next_adjacent_out = false;
    leaf_page_out = INVALID_PAGE;
    uint64_t cur   = root_page_id_;
    uint8_t  level = static_cast<uint8_t>(height_ - 1);
    for (uint32_t depth = 0; depth < height_; ++depth) {
        uint64_t next = INVALID_PAGE;
        for (int attempt = 0; attempt < 2; ++attempt) {
            bool ok = false;
            BTreeNode node = read_node(cur, level, ok);
            if (!ok) return false;
            if (node.is_leaf()) {
                leaf_page_out = cur;
                for (size_t i = 0; i < node.keys.size(); ++i)
                    if (node.keys[i] == key) {
                        value_out = node.values[i];
                        if (i + 1 < node.keys.size() && key != UINT64_MAX &&
                            node.keys[i + 1] == key + 1) {
                            next_adjacent_out = true;
                            next_value_out    = node.values[i + 1];
                        }
                        return true;
                    }
                return false;
            }
            size_t i = 0;
            while (i < node.keys.size() && key >= node.keys[i]) ++i;
            uint64_t child = node.children[i];
            if (child < gram_->pages_allocated()) { next = child; break; }
            if (attempt == 0) {
                double lat = 0.0;
                gram_->crash_rescue(cur, current_time_, level, lat);
                add_lat(lat);
            }
        }
        if (next == INVALID_PAGE) return false;
        cur = next;
        if (level > 0) --level;
    }
    return false;
}

void ExpBTree::reload_page(uint64_t page_id, uint8_t level, double& op_latency_out) {
    alarm_seen_ = true;
    if (page_id >= gram_->pages_allocated()) return;
    gram_->reload_clean(page_id, current_time_, level, op_latency_out);
}

void ExpBTree::insert(uint64_t key, uint64_t value, double& op_latency_out) {
    OpScope scope(&op_latency_out);

    bool did_split = false;
    uint64_t split_key = 0, split_page = 0;
    for (;;) {
        g_op.restart = false;
        g_op.depth   = 0;
        ChildBounds cb;                // root：兩側無界
        cb.expect_leaf = (height_ == 1);
        insert_recursive(root_page_id_, static_cast<uint8_t>(height_ - 1), key, value,
                         did_split, split_key, split_page, cb);
        // E17：範圍報警只會發生在下降途中（任何寫入之前）→ 從 root 重來是安全的
        if (!g_op.restart || g_op.abort) break;
    }
    if (g_op.abort || !did_split) return;

    // root 分裂 → 長高
    double lat = 0.0;
    uint64_t new_root_id = gram_->allocate(current_time_, lat);
    add_lat(lat);

    BTreeNode new_root{};
    new_root.page_id   = new_root_id;
    new_root.node_type = 0;
    new_root.keys      = {split_key};
    new_root.children  = {root_page_id_, split_page};
    new_root.next_leaf = INVALID_PAGE;

    ++height_;
    note_alloc(static_cast<uint8_t>(height_ - 1));   // 新 root 的 level = 新高度 - 1
    write_node(new_root, static_cast<uint8_t>(height_ - 1));
    root_page_id_ = new_root_id;
}

void ExpBTree::insert_recursive(uint64_t node_id, uint8_t level,
                                uint64_t key, uint64_t value,
                                bool& did_split, uint64_t& split_key,
                                uint64_t& split_page, const ChildBounds& cb) {
    did_split = false;

    // 毀損指標成環 → 遞迴深度超過樹高即放棄（真實系統會爆棧）
    if (++g_op.depth > static_cast<int>(height_)) {
        --g_op.depth;
        g_op.abort = true;
        return;
    }

    for (int attempt = 0; attempt < 2; ++attempt) {
        bool ok = false, hb = false;
        BTreeNode node = read_node(node_id, level, ok, &cb, &hb);
        if (!ok) { g_op.abort = true; break; }
        if (g_op.restart) break;

        if (node.is_leaf()) {
            size_t i = 0;
            while (i < node.keys.size() && key > node.keys[i]) ++i;
            node.keys.insert  (node.keys.begin()   + i, key);
            node.values.insert(node.values.begin() + i, value);

            if (node.keys.size() <= order_) {
                write_node(node, level);
            } else {
                split_leaf(node, split_key, split_page);
                did_split = true;
            }
            break;
        }

        size_t i = 0;
        while (i < node.keys.size() && key >= node.keys[i]) ++i;
        uint64_t child = node.children[i];
        if (child >= gram_->pages_allocated()) {
            // 野指標：fail-stop 重載後重試本節點一次，仍壞則放棄本 op
            if (attempt == 0) {
                double lat = 0.0;
                gram_->crash_rescue(node_id, current_time_, level, lat);
                add_lat(lat);
                continue;
            }
            g_op.abort = true;
            break;
        }

        bool child_split = false; uint64_t child_key = 0, child_page = 0;
        const uint8_t clevel = level > 0 ? static_cast<uint8_t>(level - 1) : 0;
        RangeSrc me; me.pid = node_id; me.level = level; me.bad = hb;
        const ChildBounds ccb = child_bounds(node, i, cb, me, clevel);
        insert_recursive(child, clevel, key, value, child_split, child_key, child_page, ccb);
        if (g_op.abort || g_op.restart) break;
        if (!child_split) break;

        node.keys.insert    (node.keys.begin()     + i,     child_key);
        node.children.insert(node.children.begin() + i + 1, child_page);

        if (node.keys.size() <= order_) {
            write_node(node, level);
        } else {
            g_op.cur_level = level;
            split_internal(node, split_key, split_page);
            did_split = true;
        }
        break;
    }
    --g_op.depth;
}

void ExpBTree::split_leaf(BTreeNode& leaf, uint64_t& new_key, uint64_t& new_page) {
    size_t mid = leaf.keys.size() / 2;

    double lat = 0.0;
    BTreeNode right{};
    right.page_id   = gram_->allocate(current_time_, lat);
    add_lat(lat);
    note_alloc(0);                      // 分裂出的右葉仍是 leaf
    right.node_type = 1;
    right.keys      = {leaf.keys.begin()   + mid, leaf.keys.end()};
    right.values    = {leaf.values.begin() + mid, leaf.values.end()};
    right.next_leaf = leaf.next_leaf;

    leaf.keys.resize(mid);
    leaf.values.resize(mid);
    leaf.next_leaf = right.page_id;

    write_node(leaf,  0);
    write_node(right, 0);

    new_key  = right.keys[0];
    new_page = right.page_id;
}

void ExpBTree::split_internal(BTreeNode& node, uint64_t& new_key, uint64_t& new_page) {
    size_t mid = node.keys.size() / 2;
    uint64_t push_up = node.keys[mid];

    double lat = 0.0;
    BTreeNode right{};
    right.page_id   = gram_->allocate(current_time_, lat);
    add_lat(lat);
    note_alloc(g_op.cur_level);         // 兄弟節點與被分裂者同層
    right.node_type = 0;
    right.keys      = {node.keys.begin()     + mid + 1, node.keys.end()};
    right.children  = {node.children.begin() + mid + 1, node.children.end()};
    right.next_leaf = INVALID_PAGE;

    node.keys.resize(mid);
    node.children.resize(mid + 1);

    const uint8_t level = g_op.cur_level;   // 呼叫端（insert_recursive）先存好
    write_node(node,  level);
    write_node(right, level);

    new_key  = push_up;
    new_page = right.page_id;
}

// ── walk_level_counts ────────────────────────────────────────────────────────
//
// 以 oracle（每頁最後一次成功寫入的內容）BFS 走訪整棵樹，重新數每層節點數。
// 這是「配置計數器」之外的第二個獨立來源；兩者不合就是儀器有錯。
// 不經 gram_->read()：不注入、不驗證、不計延遲、不動 metrics。
//
// 防禦：oracle 有可能被 poisoned write 汙染（毀損 image 被寫回），
// 因此每一步都檢查 child 是否越界／是否重複造訪，遇到異常回傳 false，
// 讓 driver 把該 run 標成「走訪不可信」而不是靜默給出錯數字。
bool ExpBTree::walk_level_counts(uint64_t out[MAX_LEVELS],
                                 uint32_t& max_level_out) const {
    for (int i = 0; i < MAX_LEVELS; ++i) out[i] = 0;
    max_level_out = 0;

    const uint64_t n_pages = gram_->pages_allocated();
    std::vector<uint8_t> seen(n_pages, 0);
    bool ok = true;

    // (page_id, level)
    std::vector<std::pair<uint64_t, int>> stack;
    if (root_page_id_ >= n_pages) return false;
    stack.push_back({root_page_id_, (int)height_ - 1});

    while (!stack.empty()) {
        const uint64_t pid = stack.back().first;
        const int      lvl = stack.back().second;
        stack.pop_back();

        if (pid >= n_pages) { ok = false; continue; }
        if (seen[pid])      { ok = false; continue; }
        seen[pid] = 1;

        if (lvl < 0 || lvl >= MAX_LEVELS) { ok = false; continue; }
        ++out[lvl];
        if ((uint32_t)lvl > max_level_out) max_level_out = (uint32_t)lvl;

        const std::vector<uint8_t>& img = gram_->oracle(pid);
        if (img.size() < 32) { ok = false; continue; }
        const uint8_t node_type = img[16];
        if (node_type > 1) { ok = false; continue; }
        if (node_type == 1) {                       // leaf：不再往下
            if (lvl != 0) ok = false;               // 葉子必須落在 level 0
            continue;
        }
        if (lvl == 0) { ok = false; continue; }     // internal 不可能在 level 0

        uint32_t n_keys = 0;
        std::memcpy(&n_keys, img.data() + 20, 4);
        if (n_keys > order_ ||
            32ull + (uint64_t)n_keys * 8 + ((uint64_t)n_keys + 1) * 8 > img.size()) {
            ok = false;
            continue;
        }
        const uint8_t* cp = img.data() + 32 + (size_t)n_keys * 8;
        for (uint32_t i = 0; i <= n_keys; ++i) {
            uint64_t c;
            std::memcpy(&c, cp + (size_t)i * 8, 8);
            stack.push_back({c, lvl - 1});
        }
    }
    return ok;
}

void ExpBTree::slack_scan(uint64_t& real, uint64_t& with_right, uint64_t& with_left,
                          uint64_t& dummies) const {
    real = with_right = with_left = dummies = 0;
    const uint64_t n_pages = gram_->pages_allocated();
    std::vector<uint8_t> seen(n_pages, 0);
    std::vector<std::pair<uint64_t, int>> stack;
    if (root_page_id_ >= n_pages) return;
    stack.push_back({root_page_id_, (int)height_ - 1});
    while (!stack.empty()) {
        const uint64_t pid = stack.back().first;
        const int      lvl = stack.back().second;
        stack.pop_back();
        if (pid >= n_pages || seen[pid] || lvl < 0) continue;
        seen[pid] = 1;
        const std::vector<uint8_t>& img = gram_->oracle(pid);
        if (img.size() < 32 || img[16] > 1) continue;
        uint32_t nk = 0;
        std::memcpy(&nk, img.data() + 20, 4);
        const bool leaf = (img[16] == 1);
        if (nk > order_ || 32ull + (uint64_t)nk * 16 + (leaf ? 0 : 8) > img.size()) continue;
        const uint8_t* kp = img.data() + 32;
        const uint8_t* vp = kp + (size_t)nk * 8;
        if (!leaf) {
            if (lvl == 0) continue;
            for (uint32_t i = 0; i <= nk; ++i) {
                uint64_t c; std::memcpy(&c, vp + (size_t)i * 8, 8);
                stack.push_back({c, lvl - 1});
            }
            continue;
        }
        std::vector<uint64_t> k(nk), v(nk);
        if (nk) { std::memcpy(k.data(), kp, (size_t)nk * 8); std::memcpy(v.data(), vp, (size_t)nk * 8); }
        for (uint32_t i = 0; i < nk; ++i) {
            if (v[i] == GUARD_SENTINEL_VALUE) { ++dummies; continue; }
            ++real;
            if (i + 1 < nk && v[i + 1] == GUARD_SENTINEL_VALUE && k[i + 1] == k[i] + 1) ++with_right;
            if (i > 0 && v[i - 1] == GUARD_SENTINEL_VALUE && k[i - 1] == k[i] - 1) ++with_left;
        }
    }
}

uint64_t ExpBTree::oracle_range_violations() const {
    const uint64_t n_pages = gram_->pages_allocated();
    const bool slack = gram_->config().slack_guard != SlackGuard::NONE;
    std::vector<uint8_t> seen(n_pages, 0);
    struct It { uint64_t pid; int lvl; ChildBounds b; };
    std::vector<It> st;
    ChildBounds rb; rb.expect_leaf = (height_ == 1);
    st.push_back({root_page_id_, (int)height_ - 1, rb});
    uint64_t bad = 0;
    while (!st.empty()) {
        It it = st.back(); st.pop_back();
        if (it.pid >= n_pages || seen[it.pid] || it.lvl < 0) continue;
        seen[it.pid] = 1;
        const std::vector<uint8_t>& img = gram_->oracle(it.pid);
        bool fatal = false;
        if (!sanity_check(img, it.pid, order_, page_size_, n_pages, fatal)) { ++bad; if (fatal) continue; }
        else if (!range_check(img, it.b, slack)) ++bad;
        if (img[16] == 1 || it.lvl == 0) continue;
        BTreeNode n = BTreeNode::deserialize(it.pid, img);
        RangeSrc me; me.pid = it.pid;
        for (size_t i = 0; i < n.children.size(); ++i)
            st.push_back({n.children[i], it.lvl - 1, child_bounds(n, i, it.b, me, (uint8_t)(it.lvl - 1))});
    }
    return bad;
}

void ExpBTree::advance_time(double dt) { current_time_ += dt; }

void ExpBTree::note_op_boundary() {
    fn_seen_    = false;
    alarm_seen_ = false;
    gram_->note_op_boundary();
}

} // namespace bfx
