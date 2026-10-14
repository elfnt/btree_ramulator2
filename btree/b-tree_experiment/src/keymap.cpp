#include "keymap.hpp"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <random>
#include <vector>
#include "guarded_ram.hpp"
#include "shadow_store.hpp"

namespace bfx {

KeyMapper::KeyMapper(ExpBTree* tree, const ExpConfig& cfg, uint64_t n_total, Metrics* metrics)
    : tree_(tree), mode_(cfg.key_map), shift_(cfg.key_stride_log2), metrics_(metrics) {
    if (mode_ == KeyMap::HASHDENSE) {
        if (!(cfg.map_load > 0.0 && cfg.map_load < 1.0)) {
            std::fprintf(stderr, "FATAL: --map_load must be in (0,1)\n");
            std::abort();
        }
        M_ = (uint64_t)std::ceil((double)std::max<uint64_t>(n_total, 1) / cfg.map_load);
        if (M_ < n_total + 1) M_ = n_total + 1;
    }
}

void KeyMapper::alarm(uint64_t leaf_a, uint64_t leaf_b, double& lat) {
    if (metrics_) metrics_->n_map_alarms++;
    tree_->reload_page(leaf_a, 0, lat);   // 也設定本 op 的 alarm_seen
    if (leaf_b != leaf_a && leaf_b != INVALID_PAGE) tree_->reload_page(leaf_b, 0, lat);
}

void KeyMapper::insert(uint64_t K, uint64_t V, double& lat) {
    if (mode_ == KeyMap::SHIFT) { tree_->insert(K >> shift_, V, lat); return; }
    uint64_t s = home(K), d = 0, tmp = 0;
    while (tree_->search(2 * s, tmp, lat)) {
        s = (s + 1) % M_;
        if (++d >= M_) { std::fprintf(stderr, "FATAL: hashdense table full\n"); std::abort(); }
    }
    tree_->insert(2 * s, K, lat);
    tree_->insert(2 * s + 1, V, lat);
    if (d > lmax_) lmax_ = d;
}

bool KeyMapper::lookup(uint64_t X, uint64_t& V, double& lat, uint64_t& probes_out,
                       uint64_t* slot_out) {
    probes_out = 0;
    if (mode_ == KeyMap::SHIFT) {
        if (shift_ && (X & ((1ull << shift_) - 1))) return false;   // 不可能存在
        probes_out = 1;
        return tree_->search(X >> shift_, V, lat);
    }
    uint64_t s = home(X), d = 0;
    int retry = 1;
    while (d <= lmax_) {
        ++probes_out;
        uint64_t stored = 0, leaf = INVALID_PAGE, nv = 0;
        bool adj = false;
        if (!tree_->search_pair(2 * s, stored, lat, leaf, adj, nv)) return false;
        if (stored == X) {
            if (!adj) {   // value entry 不在同一 leaf 的下一格 → 第二次走訪
                uint64_t leaf2 = INVALID_PAGE, n2 = 0; bool a2 = false;
                if (!tree_->search_pair(2 * s + 1, nv, lat, leaf2, a2, n2)) {
                    alarm(leaf, leaf2, lat);       // key entry 缺 value entry
                    if (retry-- > 0) continue;
                    return false;
                }
            }
            V = nv;
            if (slot_out) *slot_out = s;
            return true;
        }
        if (!consistent(stored, s)) {             // v 不可能合法住在這裡
            alarm(leaf, INVALID_PAGE, lat);
            if (retry-- > 0) continue;
            return false;
        }
        s = (s + 1) % M_;                          // 真碰撞
        ++d;
    }
    return false;                                  // 距離 > L_max → 不存在
}

uint64_t keymap_predict_inserts(const ExpConfig& cfg, uint64_t prefill_size) {
    std::mt19937 w(cfg.seed ^ 0xabcdefu);
    std::bernoulli_distribution do_search(cfg.read_ratio);
    std::bernoulli_distribution do_miss(cfg.miss_ratio);
    uint64_t size = prefill_size, ins = 0;
    for (uint32_t i = 0; i < cfg.n_ops; ++i) {
        if (do_search(w)) {
            if (do_miss(w) || size == 0)
                (void)std::uniform_int_distribution<uint64_t>(0, 999999999ull)(w);
            else
                (void)std::uniform_int_distribution<size_t>(0, size - 1)(w);
        } else { ++ins; ++size; }
    }
    return ins;
}

// ── 自測 ─────────────────────────────────────────────────────────────────────
namespace {
struct Stack {
    ExpConfig cfg;
    std::unique_ptr<SSD> ssd;
    std::unique_ptr<RAM> ram;
    Metrics metrics;
    std::unique_ptr<ShadowStore> shadow;
    std::unique_ptr<GuardedRAM> gram;
    std::unique_ptr<ExpBTree> tree;
    explicit Stack(const ExpConfig& base) : cfg(base) {
        cfg.scheme = Scheme::NONE; cfg.lambda_page = 0.0;
        cfg.ssd_blocks = 512; cfg.ram_rows_per_bank = 2048;
        ssd_config sc{};
        sc.max_block_count_    = cfg.ssd_blocks;
        sc.pages_per_block_    = cfg.pages_per_block;
        sc.page_size_bytes_    = cfg.page_size;
        sc.logical_page_count_ = (uint32_t)(cfg.ssd_blocks * cfg.pages_per_block * 0.93);
        ssd.reset(new SSD(sc));
        RAMConfig rc{};
        rc.rows_per_bank = cfg.ram_rows_per_bank;
        rc.lambda_eff = 0.0; rc.t_mem = cfg.t_mem_s; rc.t_ssd = cfg.t_ssd_s; rc.seed = 7;
        ram.reset(new RAM(rc, ssd.get()));
        shadow.reset(new ShadowStore(cfg, &metrics, 1));
        gram.reset(new GuardedRAM(ram.get(), ssd.get(), shadow.get(), &metrics, &cfg));
        tree.reset(new ExpBTree(gram.get(), cfg.order, cfg.page_size));
    }
};
[[noreturn]] void kfail(const char* what, unsigned long long a = 0) {
    std::fprintf(stderr, "FATAL: keymap self-test failed: %s (%llu)\n", what, a);
    std::abort();
}
} // namespace

void keymap_self_test(const ExpConfig& base) {
    const uint64_t N = 100000;
    std::mt19937_64 rng(0x6b6d6170ull);
    if (base.key_map == KeyMap::SHIFT) {
        Stack st(base);
        KeyMapper km(st.tree.get(), st.cfg, N, &st.metrics);
        const uint32_t k = base.key_stride_log2;
        std::vector<uint64_t> idx(N);
        for (uint64_t i = 0; i < N; ++i) idx[i] = i;
        std::shuffle(idx.begin(), idx.end(), rng);
        for (uint64_t i : idx) { double l = 0; km.insert(i << k, (i << k) * 7 + 13, l); if (st.ssd) st.ssd->GC(); }
        for (uint64_t i = 0; i < 2 * N; ++i) {
            uint64_t v = 0, p = 0; double l = 0;
            const bool f = km.lookup(i << k, v, l, p);
            if (i < N && (!f || v != (i << k) * 7 + 13)) kfail("(s1) shift lost key", i);
            if (i >= N && f) kfail("(s1) shift phantom", i);
        }
        std::fprintf(stderr, "keymap self-test PASS (shift k=%u: %llu keys round-trip, %llu absent)\n",
                     k, (unsigned long long)N, (unsigned long long)N);
        return;
    }
    if (base.key_map != KeyMap::HASHDENSE) return;

    Stack st(base);
    KeyMapper km(st.tree.get(), st.cfg, N, &st.metrics);
    std::uniform_int_distribution<uint64_t> u(0, (1ull << 63) - 1);
    std::vector<uint64_t> keys;
    while (keys.size() < N) {
        while (keys.size() < N) keys.push_back(u(rng));
        std::sort(keys.begin(), keys.end());
        keys.erase(std::unique(keys.begin(), keys.end()), keys.end());
    }
    std::shuffle(keys.begin(), keys.end(), rng);
    for (uint64_t K : keys) {
        double l = 0; km.insert(K, K * 7 + 13, l); st.ssd->GC(); st.tree->note_op_boundary();
    }
    // (m1)
    std::vector<uint64_t> slot(N);
    uint64_t probes_hit = 0, probes_miss = 0;
    for (uint64_t i = 0; i < N; ++i) {
        uint64_t v = 0, p = 0; double l = 0;
        st.tree->note_op_boundary();
        if (!km.lookup(keys[i], v, l, p, &slot[i]) || v != keys[i] * 7 + 13) kfail("(m1) lost key", i);
        probes_hit += p;
    }
    std::vector<uint64_t> sorted = keys; std::sort(sorted.begin(), sorted.end());
    for (uint64_t i = 0; i < N; ++i) {
        uint64_t X; do { X = u(rng); } while (std::binary_search(sorted.begin(), sorted.end(), X));
        uint64_t v = 0, p = 0; double l = 0;
        st.tree->note_op_boundary();
        if (km.lookup(X, v, l, p)) kfail("(m1) phantom key", i);
        probes_miss += p;
    }
    if (st.metrics.n_map_alarms != 0) kfail("(m1) alarm on clean tree", st.metrics.n_map_alarms);

    // (m2) 邏輯層：每個 key 的 64 個單位元翻轉
    const double p_pass = (double)(km.lmax() + 1) / (double)km.slots();
    uint64_t n2 = 0, caught2 = 0;
    for (uint64_t i = 0; i < N; ++i)
        for (int b = 0; b < 64; ++b) {
            ++n2;
            if (!km.consistent(keys[i] ^ (1ull << b), slot[i])) ++caught2;
        }
    const double exp_unc = n2 * p_pass, unc = (double)(n2 - caught2);
    if (std::fabs(unc - exp_unc) > 6.0 * std::sqrt(exp_unc) + 5.0)
        kfail("(m2) catch rate off model", (unsigned long long)unc);

    // (m3) 端到端：在 DRAM 實際翻轉存放的原始 key
    std::mt19937_64 r3(99);
    const uint64_t T = 3000;
    uint64_t caught3 = 0, missed3 = 0;
    for (uint64_t t = 0; t < T; ++t) {
        const uint64_t i = r3() % N; const int b = (int)(r3() % 64);
        const uint64_t K = keys[i], s = slot[i];
        uint64_t stored = 0, leaf = INVALID_PAGE, nv = 0; bool adj = false; double l = 0;
        st.tree->note_op_boundary();
        if (!st.tree->search_pair(2 * s, stored, l, leaf, adj, nv) || stored != K) kfail("(m3) setup", t);
        const std::vector<uint8_t>& img = st.gram->oracle(leaf);
        uint32_t nk = 0; std::memcpy(&nk, img.data() + 20, 4);
        int pos = -1;
        for (uint32_t j = 0; j < nk; ++j) {
            uint64_t kk; std::memcpy(&kk, img.data() + 32 + j * 8, 8);
            if (kk == 2 * s) { pos = (int)j; break; }
        }
        if (pos < 0) kfail("(m3) key not in leaf image", t);
        const uint32_t off = 32 + nk * 8 + (uint32_t)pos * 8;
        uint64_t chk; std::memcpy(&chk, img.data() + off, 8);
        if (chk != K) kfail("(m3) value-slot offset wrong", t);
        st.ram->flip_bit(leaf, off + b / 8, (uint8_t)(b % 8));
        const uint64_t alarms0 = st.metrics.n_map_alarms;
        st.tree->note_op_boundary();
        uint64_t v = 0, p = 0;
        const bool f = km.lookup(K, v, l, p);
        const bool alarmed = st.metrics.n_map_alarms > alarms0;
        const bool expect_caught = !km.consistent(K ^ (1ull << b), s);
        if (alarmed != expect_caught) kfail("(m3) alarm != consistency prediction", t);
        if (alarmed) {
            if (!f || v != K * 7 + 13) kfail("(m3) caught but not recovered", t);
            ++caught3;
        } else {
            if (f) kfail("(m3) uncaught flip but key found", t);
            ++missed3;
            st.ram->flip_bit(leaf, off + b / 8, (uint8_t)(b % 8));   // 復原
        }
        st.ssd->GC();   // 重載是 write-through 寫入
    }
    std::fprintf(stderr,
        "keymap self-test PASS (hashdense α=%g: N=%llu M=%llu L_max=%llu; "
        "m1 0 lost/0 phantom/0 alarms, probes/hit %.3f probes/miss %.3f; "
        "m2 caught %llu/%llu = %.6f vs expected 1-(L_max+1)/M = %.6f; "
        "m3 e2e caught %llu/%llu, missed %llu)\n",
        base.map_load, (unsigned long long)N, (unsigned long long)km.slots(),
        (unsigned long long)km.lmax(), probes_hit / (double)N, probes_miss / (double)N,
        (unsigned long long)caught2, (unsigned long long)n2, caught2 / (double)n2, 1.0 - p_pass,
        (unsigned long long)caught3, (unsigned long long)T, (unsigned long long)missed3);
}

} // namespace bfx
