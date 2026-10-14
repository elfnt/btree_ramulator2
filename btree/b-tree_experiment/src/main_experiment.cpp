// main_experiment.cpp — 單一 run 的 driver：組態 → 建棧 → prefill →
// 主迴圈（注入 + 工作負載 + 評分）→ 完整性掃描 → CSV。
//
// 後端選擇（--backend=ram|r2）：
//   ram（預設）: 純 C++ RAM + SSD 模擬，與原版行為完全相同。
//   r2          : Ramulator2 DDR4 後端（需以 --r2 flag 建置，見 build.sh），
//                 需額外加 --r2_config=<yaml path>。
//
// v2 SSD 對 stdout 大量列印除錯訊息，parse 後即把 stdout 導向 NUL；
// 本程式的進度與摘要一律走 stderr。
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <map>
#include <memory>
#include <numeric>
#include <random>
#include <string>
#include <unordered_set>
#include <vector>

#include "exp_config.hpp"
#include "metrics.hpp"
#include "shadow_store.hpp"
#include "guarded_ram.hpp"
#include "exp_btree.hpp"
#include "fault_injector.hpp"
#include "fast_crc.hpp"
#include "keymap.hpp"   // E21
#include "../../tools/checksums.hpp"   // v2 pageCRC32：自測的參考實作

// ── Ramulator2 後端（僅在 -DHAVE_RAMULATOR2 時編譯）──────────────────────────
#ifdef HAVE_RAMULATOR2
#include "ramulator/base/base.h"
#include "ramulator/base/config.h"
#include "ramulator/base/factory.h"
#include "ramulator/frontend/i_frontend.h"
#include "ramulator/memory_system/i_memory_system.h"
#include "r2_btree_ram.hpp"

using namespace Ramulator;

// NullFrontend：r2 backend 不需要 trace-driven frontend
class NullFrontend : public IFrontEnd, public Implementation {
    RAMULATOR_REGISTER_IMPLEMENTATION(IFrontEnd, NullFrontend, "NullFrontend")
public:
    void init()        override {}
    void tick()        override {}
    bool is_finished() override { return true; }
};
#endif  // HAVE_RAMULATOR2

// ── 啟動自測 ─────────────────────────────────────────────────────────────────
// bfx::fast_crc32（表驅動）必須與 v2 pageCRC32（逐 bit）對任意輸入完全相同。
static void fast_crc_self_test() {
    std::mt19937 rng(0xC5C32u);
    std::uniform_int_distribution<uint32_t> len_dist(0, 8192);
    std::uniform_int_distribution<int> byte_dist(0, 255);
    for (int i = 0; i < 16; ++i) {
        std::vector<uint8_t> buf(len_dist(rng));
        for (auto& b : buf) b = (uint8_t)byte_dist(rng);
        const uint32_t fast = bfx::fast_crc32(buf);
        const uint32_t ref  = pageCRC32(buf);
        if (fast != ref) {
            fprintf(stderr,
                    "FATAL: fast_crc32 self-test failed (buf %d, len %zu): "
                    "fast=0x%08X ref=0x%08X\n",
                    i, buf.size(), fast, ref);
            std::abort();
        }
    }
}

// ── CTRL_CRC 邊界自測 ────────────────────────────────────────────────────────
//
// CTRL_CRC 的整個賣點是「涵蓋範圍恰好落在 control plane 與 payload 的交界」。
// 這個界線若偏了，方案要嘛退化成 FULL_CRC（沒省到成本）、要嘛退化成 HDR_CRC
// （沒買到偵測）。三個斷言正是這條界線的操作型定義：
//
//   (a) 乾淨往返永不誤報          → precision 不會被自身實作汙染
//   (b) [16, 16+ctrl_len) 內任一位元組翻轉必被抓到（含 n_keys 欄位本身，
//       且驗證用的是 protect() 時凍結的 ctrl_len，不是重算值）
//   (c) LEAF 的 [16+ctrl_len, page_size) 內翻轉恆不被抓到
//       → 證明 values[] 確實在保護範圍外（這正是它與 FULL_CRC 的差別，
//         也是 SUMMARY 中 payload_only 那條結論所依賴的前提）
//
// 任一項不成立即 abort（同 fast_crc_self_test 的風格）。
static void ctrl_crc_self_test() {
    const uint32_t page_size = 4096;

    // 以 v2 的 BTreeNode::serialize 產生 image，確保格式與實驗跑的完全一致
    auto make_image = [&](bool leaf, uint32_t n_keys) {
        BTreeNode node{};
        node.page_id   = 7;
        node.node_type = leaf ? 1 : 0;
        for (uint32_t i = 0; i < n_keys; ++i) {
            node.keys.push_back(100ull + i * 3);
            if (leaf) node.values.push_back(900ull + i);
        }
        if (!leaf)
            for (uint32_t i = 0; i <= n_keys; ++i) node.children.push_back(11ull + i);
        node.next_leaf = leaf ? 42ull : INVALID_PAGE;

        std::vector<uint8_t> image(page_size, 0);
        uint32_t ps = page_size, zero = 0;
        std::memcpy(image.data() + 0,  &zero, 4);   // SSD header：CRC32 = 0
        std::memcpy(image.data() + 4,  &ps,   4);   // page_size_bytes
        std::memcpy(image.data() + 8,  &zero, 4);
        std::memcpy(image.data() + 12, &zero, 4);
        node.serialize(image);
        return image;
    };

    auto fail = [](const char* what, bool leaf, uint32_t n_keys, size_t off) {
        fprintf(stderr,
                "FATAL: CTRL_CRC self-test failed: %s (node=%s n_keys=%u byte=%zu)\n",
                what, leaf ? "leaf" : "internal", n_keys, off);
        std::abort();
    };

    for (bool leaf : {true, false}) {
        for (uint32_t n_keys : {0u, 1u, 5u, 100u, 253u}) {
            const std::vector<uint8_t> clean = make_image(leaf, n_keys);

            // 凍結的 ctrl_len + 基準 CRC（等同 ShadowStore::protect() 的行為）
            const uint32_t ctrl_len = bfx::ctrl_len_of(clean, page_size);
            const uint32_t expect =
                16u + n_keys * 8u + (leaf ? 0u : (n_keys + 1u) * 8u);
            if (ctrl_len != expect) fail("ctrl_len formula mismatch", leaf, n_keys, ctrl_len);

            const uint32_t base =
                bfx::ShadowStore::crc_of(bfx::Scheme::CTRL_CRC, clean, ctrl_len);

            // (a) 乾淨往返：不得誤報
            if (bfx::ShadowStore::crc_of(bfx::Scheme::CTRL_CRC, clean, ctrl_len) != base)
                fail("(a) clean round-trip false positive", leaf, n_keys, 0);

            // (b) 涵蓋區內任一位元組翻轉必被抓到（逐位元組，翻 bit 0）
            for (size_t off = 16; off < 16u + ctrl_len; ++off) {
                std::vector<uint8_t> bad = clean;
                bad[off] ^= 0x01;
                if (bfx::ShadowStore::crc_of(bfx::Scheme::CTRL_CRC, bad, ctrl_len) == base)
                    fail("(b) flip inside coverage NOT caught", leaf, n_keys, off);
            }

            // (b2) 關鍵不變量：n_keys 欄位本身被翻成離譜值時，用「凍結的」
            //      ctrl_len 驗證仍必須抓到。若改用讀回 image 重算 ctrl_len，
            //      檢查範圍會跟著位移，正是本測試要排除的失效模式。
            {
                std::vector<uint8_t> bad = clean;
                const uint32_t bogus = 0xDEADBEEFu;
                std::memcpy(bad.data() + 20, &bogus, 4);
                if (bfx::ShadowStore::crc_of(bfx::Scheme::CTRL_CRC, bad, ctrl_len) == base)
                    fail("(b2) corrupted n_keys NOT caught with frozen ctrl_len",
                         leaf, n_keys, 20);
                const uint32_t rederived = bfx::ctrl_len_of(bad, page_size);
                if (rederived == ctrl_len)
                    fail("(b2) test is vacuous: re-derived ctrl_len unchanged",
                         leaf, n_keys, 20);
                // 且重算值必須仍被夾在頁內——沒有夾擠的話 n_keys 被翻成
                // 0xDEADBEEF 就會讓驗證器讀出頁面邊界（真正的記憶體安全問題，
                // 這才是「凍結 ctrl_len」最硬的理由）。
                if ((size_t)16 + rederived > page_size)
                    fail("(b2) re-derived ctrl_len escapes the page", leaf, n_keys, rederived);
            }

            // (d) SSD header（offset 0-15）內的翻轉必被抓到——CTRL_CRC 自 0 起算
            for (size_t off = 0; off < 16; ++off) {
                std::vector<uint8_t> bad = clean;
                bad[off] ^= 0x01;
                if (bfx::ShadowStore::crc_of(bfx::Scheme::CTRL_CRC, bad, ctrl_len) == base)
                    fail("(d) flip in SSD header NOT caught", leaf, n_keys, off);
            }

            // (c) LEAF 的 payload 區（values[] 與其後補零）翻轉恆不被抓到。
            //     internal 節點的 ctrl_len 已涵蓋全部內容，此項不適用。
            if (leaf) {
                for (size_t off = 16u + ctrl_len; off < page_size; ++off) {
                    std::vector<uint8_t> bad = clean;
                    bad[off] ^= 0x01;
                    if (bfx::ShadowStore::crc_of(bfx::Scheme::CTRL_CRC, bad, ctrl_len) != base)
                        fail("(c) flip outside coverage WAS caught "
                             "(boundary is not where intended)", leaf, n_keys, off);
                }
            }
        }
    }
}

// ── HYBRID（E10）自測 ────────────────────────────────────────────────────────
//   (h1) scheme_entry_bytes(HYBRID) == 12
//   (h2) leaf（level 0）protect → false、不佔 entry、bytes_used 不變
//   (h3) internal（level ≥ 1）protect → true、ctrl_len 凍結 = ctrl_len_of、
//        [0,16+ctrl_len) 內任一位元組翻轉都被 CRC 抓到
//   (h4) leaf 的 key 翻轉：sanity_check 失敗 ⇔ 翻轉後 keys 不再嚴格遞增
//        （逐 key、逐 64 位元窮舉）
static void hybrid_self_test() {
    const uint32_t page_size = 4096;
    auto fail = [](const char* what, int a, int b) {
        fprintf(stderr, "FATAL: HYBRID self-test failed: %s (%d, %d)\n", what, a, b);
        std::abort();
    };
    if (bfx::scheme_entry_bytes(bfx::Scheme::HYBRID) != 12) fail("(h1) entry bytes", 0, 0);

    auto make_image = [&](bool leaf, uint32_t n_keys) {
        BTreeNode node{};
        node.page_id   = 7;
        node.node_type = leaf ? 1 : 0;
        for (uint32_t i = 0; i < n_keys; ++i) {
            node.keys.push_back(100ull + i * 3);
            if (leaf) node.values.push_back(900ull + i);
        }
        if (!leaf)
            for (uint32_t i = 0; i <= n_keys; ++i) node.children.push_back(11ull + i);
        node.next_leaf = leaf ? 42ull : INVALID_PAGE;
        std::vector<uint8_t> image(page_size, 0);
        uint32_t ps = page_size;
        std::memcpy(image.data() + 4, &ps, 4);
        node.serialize(image);
        return image;
    };

    bfx::ExpConfig cfg;
    cfg.scheme = bfx::Scheme::HYBRID;
    cfg.order  = 253;
    bfx::ShadowStore st(cfg, nullptr, 1);

    // (h2)
    const std::vector<uint8_t> leaf = make_image(true, 100);
    if (st.protect(3, leaf, 0, 1)) fail("(h2) leaf protect returned true", 0, 0);
    if (st.is_protected(3) || st.bytes_used() != 0) fail("(h2) leaf got an entry", 0, 0);

    // (h3)
    for (uint32_t n_keys : {1u, 100u, 253u}) {
        const std::vector<uint8_t> in = make_image(false, n_keys);
        if (!st.protect(5, in, 1, 1)) fail("(h3) internal protect returned false", n_keys, 0);
        bfx::ShadowEntry* e = st.lookup(5, 1);
        if (!e || e->ctrl_len != bfx::ctrl_len_of(in, page_size))
            fail("(h3) ctrl_len not frozen", n_keys, 0);
        if (bfx::ShadowStore::crc_of(bfx::Scheme::HYBRID, in, e->ctrl_len) != e->crc)
            fail("(h3) clean false positive", n_keys, 0);
        for (size_t off = 0; off < 16u + e->ctrl_len; ++off) {
            std::vector<uint8_t> bad = in;
            bad[off] ^= 0x01;
            if (bfx::ShadowStore::crc_of(bfx::Scheme::HYBRID, bad, e->ctrl_len) == e->crc)
                fail("(h3) internal flip NOT caught", n_keys, (int)off);
        }
    }
    if (st.bytes_used() != 12) fail("(h3) bytes_used != 1 entry", (int)st.bytes_used(), 0);

    // (h4)
    const uint32_t nk = 100;
    for (uint32_t ki : {0u, 1u, 50u, nk - 1}) {
        for (int b = 0; b < 64; ++b) {
            std::vector<uint8_t> bad = leaf;
            bad[32 + ki * 8 + b / 8] ^= (uint8_t)(1u << (b % 8));
            std::vector<uint64_t> keys(nk);
            std::memcpy(keys.data(), bad.data() + 32, nk * 8);
            bool increasing = true;
            for (uint32_t i = 1; i < nk; ++i) if (keys[i] <= keys[i - 1]) increasing = false;
            bool fatal = false;
            const bool ok = bfx::sanity_check(bad, 7, 253, page_size, 1000, fatal);
            if (ok != increasing) fail("(h4) leaf sanity != ordering", (int)ki, b);
        }
    }
}

// ── E13：guard key 候選（碰撞過濾由呼叫端負責）────────────────────────────────
// 邊界：K == 0 無左鄰、K == 2^64-1 無右鄰（直接略過，等同碰撞）。
// MID 需 kstride ≥ 1（driver 已驗證）。
// GRID（E22）：K + j·2^grid（j = 1 … 2^(kstride−grid) − 1，升冪）；需 1 ≤ grid < kstride（driver 已驗證）。
static std::vector<uint64_t> guard_candidates(uint64_t K, bfx::GuardMode g, uint32_t kstride,
                                              uint32_t grid = 0) {
    std::vector<uint64_t> d;
    switch (g) {
        case bfx::GuardMode::NONE:  break;
        case bfx::GuardMode::RIGHT: if (K != UINT64_MAX) d.push_back(K + 1); break;
        case bfx::GuardMode::LEFT:  if (K != 0) d.push_back(K - 1); break;
        case bfx::GuardMode::BOTH:
            if (K != 0) d.push_back(K - 1);
            if (K != UINT64_MAX) d.push_back(K + 1);
            break;
        case bfx::GuardMode::MID:
            if (kstride >= 1 && K <= UINT64_MAX - (1ull << (kstride - 1)))
                d.push_back(K + (1ull << (kstride - 1)));
            break;
        case bfx::GuardMode::GRID: {
            if (grid < 1 || grid >= kstride) break;
            const uint64_t n = (1ull << (kstride - grid)) - 1;
            for (uint64_t j = 1; j <= n; ++j) {
                const uint64_t off = j << grid;
                if (K > UINT64_MAX - off) break;
                d.push_back(K + off);
            }
            break;
        }
    }
    return d;
}

// ── E16：頁內 CRC 自測 ───────────────────────────────────────────────────────
//   (i0) scheme_entry_bytes == 0；ShadowStore::protect 恆 false、bytes_used 恆 0
//   (i1) 乾淨 image 永不報警；serialize 後尾端 4 B 必為 0（尾端空閒）
//   (i2) 涵蓋區 [0,end) 內每個位元組（bit 0 與 bit 7）翻轉都被抓到
//   (i3) 存放的 CRC 欄位 [ps-4,ps) 內任一位元翻轉被抓到
//   (i4) n_keys 被毀（32 個單一位元翻轉 + 0xDEADBEEF）被抓到，且重算的涵蓋範圍不觸及 CRC 欄位
//   (i5) INPAGE_CTRL：leaf 的 values[]（及其後到 CRC 欄位前的補零）翻轉不被抓到；
//        INPAGE_FULL：同位置被抓到
//   (i6) node_type 翻轉被抓到
static void inpage_self_test() {
    const uint32_t ps = 4096;
    auto fail = [](const char* what, const char* sch, bool leaf, uint32_t nk, size_t off) {
        fprintf(stderr, "FATAL: INPAGE self-test failed: %s (%s %s n_keys=%u off=%zu)\n",
                what, sch, leaf ? "leaf" : "internal", nk, off);
        std::abort();
    };
    auto make_image = [&](bool leaf, uint32_t n_keys) {
        BTreeNode node{};
        node.page_id = 7;
        node.node_type = leaf ? 1 : 0;
        for (uint32_t i = 0; i < n_keys; ++i) {
            node.keys.push_back(((uint64_t)i << 32) + 100);
            if (leaf) node.values.push_back(0x1234567ull * (i + 3));
        }
        if (!leaf) for (uint32_t i = 0; i <= n_keys; ++i) node.children.push_back(11ull + i);
        node.next_leaf = leaf ? 42ull : INVALID_PAGE;
        std::vector<uint8_t> image(ps, 0);
        std::memcpy(image.data() + 4, &ps, 4);
        node.serialize(image);
        return image;
    };
    for (bfx::Scheme sc : {bfx::Scheme::INPAGE_CTRL, bfx::Scheme::INPAGE_FULL}) {
        const char* nm = bfx::scheme_name(sc);
        if (bfx::scheme_entry_bytes(sc) != 0) fail("(i0) entry bytes != 0", nm, true, 0, 0);
        bfx::ExpConfig cfg; cfg.scheme = sc; cfg.order = 253;
        bfx::ShadowStore st(cfg, nullptr, 1);
        for (bool leaf : {true, false}) {
            for (uint32_t nk : {0u, 1u, 5u, 100u, 253u}) {
                std::vector<uint8_t> clean = make_image(leaf, nk);
                for (uint32_t i = ps - 4; i < ps; ++i)
                    if (clean[i] != 0) fail("(i1) tail not free after serialize", nm, leaf, nk, i);
                bfx::inpage_stamp(sc, clean, ps);
                if (st.protect(3, clean, leaf ? 0 : 1, 1) || st.bytes_used() != 0)
                    fail("(i0) protect took an entry", nm, leaf, nk, 0);
                if (bfx::inpage_mismatch(sc, clean, ps)) fail("(i1) clean false positive", nm, leaf, nk, 0);
                const uint32_t end = bfx::inpage_cover_end(sc, clean, ps);
                const uint32_t want = (sc == bfx::Scheme::INPAGE_FULL) ? ps - 4
                                    : 16u + bfx::ctrl_len_of(clean, ps);
                if (end != want || end > ps - 4) fail("(i1) cover end", nm, leaf, nk, end);
                for (size_t off = 0; off < end; ++off)
                    for (int b : {0, 7}) {
                        std::vector<uint8_t> bad = clean;
                        bad[off] ^= (uint8_t)(1u << b);
                        if (!bfx::inpage_mismatch(sc, bad, ps)) fail("(i2) flip in coverage NOT caught", nm, leaf, nk, off);
                    }
                for (size_t off = ps - 4; off < ps; ++off)
                    for (int b = 0; b < 8; ++b) {
                        std::vector<uint8_t> bad = clean;
                        bad[off] ^= (uint8_t)(1u << b);
                        if (!bfx::inpage_mismatch(sc, bad, ps)) fail("(i3) flip in stored CRC NOT caught", nm, leaf, nk, off);
                    }
                for (int b = 0; b <= 32; ++b) {
                    std::vector<uint8_t> bad = clean;
                    uint32_t v; std::memcpy(&v, bad.data() + 20, 4);
                    v = (b == 32) ? 0xDEADBEEFu : (v ^ (1u << b));
                    std::memcpy(bad.data() + 20, &v, 4);
                    if (!bfx::inpage_mismatch(sc, bad, ps)) fail("(i4) corrupted n_keys NOT caught", nm, leaf, nk, (size_t)b);
                    if (bfx::inpage_cover_end(sc, bad, ps) > ps - 4) fail("(i4) cover reaches CRC field", nm, leaf, nk, (size_t)b);
                }
                {
                    std::vector<uint8_t> bad = clean;
                    bad[16] ^= 0x01;
                    if (!bfx::inpage_mismatch(sc, bad, ps)) fail("(i6) node_type flip NOT caught", nm, leaf, nk, 16);
                }
                if (leaf) {
                    for (size_t off = 32 + (size_t)nk * 8; off < ps - 4; ++off) {
                        std::vector<uint8_t> bad = clean;
                        bad[off] ^= 0x10;
                        const bool caught = bfx::inpage_mismatch(sc, bad, ps);
                        if (sc == bfx::Scheme::INPAGE_CTRL && caught)
                            fail("(i5) CTRL caught a values[]/slack flip", nm, leaf, nk, off);
                        if (sc == bfx::Scheme::INPAGE_FULL && !caught)
                            fail("(i5) FULL missed a values[]/slack flip", nm, leaf, nk, off);
                    }
                }
            }
        }
    }
}

// ── E13：guard 自測（單元部分）────────────────────────────────────────────────
//   (g1) guard_candidates 的值與邊界
//   (g2) leaf_slot_is_dummy：依 value == sentinel 判定，越界 → false
//   (g3) sentinel 不等於任何「真 value」7K+13（K ≠ 2^64-1）
static void guard_unit_self_test() {
    auto fail = [](const char* what) {
        fprintf(stderr, "FATAL: guard self-test failed: %s\n", what); std::abort();
    };
    using G = bfx::GuardMode;
    const uint64_t K = 5ull << 16;
    if (!guard_candidates(K, G::NONE, 16).empty()) fail("(g1) none");
    if (guard_candidates(K, G::RIGHT, 16) != std::vector<uint64_t>{K + 1}) fail("(g1) right");
    if (guard_candidates(K, G::LEFT, 16)  != std::vector<uint64_t>{K - 1}) fail("(g1) left");
    if (guard_candidates(K, G::BOTH, 16)  != (std::vector<uint64_t>{K - 1, K + 1})) fail("(g1) both");
    if (guard_candidates(K, G::MID, 16)   != std::vector<uint64_t>{K + (1ull << 15)}) fail("(g1) mid");
    if (!guard_candidates(0, G::LEFT, 16).empty()) fail("(g1) left underflow");
    if (guard_candidates(0, G::BOTH, 16) != std::vector<uint64_t>{1}) fail("(g1) both underflow");
    if (!guard_candidates(UINT64_MAX, G::RIGHT, 16).empty()) fail("(g1) right overflow");
    // (g1) E22 grid：g = k−1 必須與 MID 逐一相同；g = k−2 → 3 個、g = k−3 → 7 個，升冪、間距 2^g
    if (guard_candidates(K, G::GRID, 16, 15) != guard_candidates(K, G::MID, 16)) fail("(g1) grid k-1 != mid");
    if (guard_candidates(K, G::GRID, 16, 14) !=
        (std::vector<uint64_t>{K + (1ull << 14), K + (2ull << 14), K + (3ull << 14)})) fail("(g1) grid k-2");
    {
        const auto v = guard_candidates(K, G::GRID, 16, 13);
        if (v.size() != 7) fail("(g1) grid k-3 count");
        for (size_t j = 0; j < v.size(); ++j) if (v[j] != K + ((j + 1) << 13)) fail("(g1) grid k-3 value");
        if (v.back() >= K + (1ull << 16)) fail("(g1) grid reaches next real key");
    }
    if (!guard_candidates(K, G::GRID, 16, 16).empty() || !guard_candidates(K, G::GRID, 16, 0).empty())
        fail("(g1) grid bad g");
    // (g2)
    BTreeNode node{}; node.page_id = 1; node.node_type = 1; node.next_leaf = INVALID_PAGE;
    for (uint64_t i = 0; i < 10; ++i) {
        node.keys.push_back(100 + i);
        node.values.push_back((i % 3 == 0) ? bfx::GUARD_SENTINEL_VALUE : (100 + i) * 7 + 13);
    }
    std::vector<uint8_t> img(4096, 0);
    node.serialize(img);
    for (int i = 0; i < 10; ++i)
        if (bfx::leaf_slot_is_dummy(img, i) != (i % 3 == 0)) fail("(g2) slot classification");
    if (bfx::leaf_slot_is_dummy(img, 10) || bfx::leaf_slot_is_dummy(img, -1)) fail("(g2) out of range");
    // (g3) 7*(2^64-1)+13 == 6 (mod 2^64)；其他 K 皆不等
    if ((uint64_t)(UINT64_MAX * 7ull + 13ull) != bfx::GUARD_SENTINEL_VALUE) fail("(g3) preimage");
    for (uint64_t k : {0ull, 1ull, 1ull << 32, (1ull << 63) - 1, 1000000ull << 32})
        if (k * 7 + 13 == bfx::GUARD_SENTINEL_VALUE) fail("(g3) collision");
}


// ── E17：parent–child 範圍檢查自測 ───────────────────────────────────────────
//   (r1) 乾淨的父子：每個 child 在 child_bounds 下通過 range_check
//   (r2) child 指標被導向另一個合法頁（同層其他 leaf / 錯誤層級的 internal）→ 抓到
//   (r3) 父節點分隔鍵單一位元翻轉：若父節點仍通過 sanity_check 且翻轉「有害」
//        （改變任何既存 key 的路由），則下一次走訪受影響的 child（s 或 s+1）必抓到
//   (r4) internal child：第一個 key 必須 > lo（inherit 的 lo 亦然），越界抓到
static std::vector<uint8_t> img_of(const BTreeNode& n) {
    std::vector<uint8_t> img(4096, 0);
    uint32_t ps = 4096;
    std::memcpy(img.data() + 4, &ps, 4);
    n.serialize(img);
    return img;
}
static void range_self_test() {
    auto fail = [](const char* what, int a, int b) {
        fprintf(stderr, "FATAL: range self-test failed: %s (%d, %d)\n", what, a, b); std::abort();
    };
    for (uint32_t kst : {0u, 16u, 32u}) {
        // 6 個 leaf，每個 50 key；index 連續 → key = idx << kst
        const int NL = 6, PER = 50;
        std::vector<BTreeNode> leaves(NL);
        BTreeNode parent{}; parent.page_id = 100; parent.node_type = 0; parent.next_leaf = INVALID_PAGE;
        for (int l = 0; l < NL; ++l) {
            BTreeNode& lf = leaves[l];
            lf.page_id = 10 + l; lf.node_type = 1; lf.next_leaf = (l + 1 < NL) ? 11 + l : INVALID_PAGE;
            for (int j = 0; j < PER; ++j) {
                const uint64_t k = (uint64_t)(1000 + l * PER + j) << kst;
                lf.keys.push_back(k); lf.values.push_back(k * 7 + 13);
            }
            parent.children.push_back(lf.page_id);
            if (l > 0) parent.keys.push_back(lf.keys[0]);
        }
        std::vector<std::vector<uint8_t>> li;
        for (auto& lf : leaves) li.push_back(img_of(lf));
        bfx::ChildBounds root; bfx::RangeSrc ps; ps.pid = 100; ps.level = 1;
        // (r1)
        for (int i = 0; i < NL; ++i)
            if (!bfx::range_check(li[i], bfx::child_bounds(parent, i, root, ps, 0), false)) fail("(r1) clean alarm", kst, i);
        // (r2) 同層另一個 leaf
        for (int i = 0; i < NL; ++i)
            for (int j = 0; j < NL; ++j)
                if (i != j && bfx::range_check(li[j], bfx::child_bounds(parent, i, root, ps, 0), false))
                    fail("(r2) redirected child not caught", i, j);
        // (r2b) 指向 internal 頁（錯誤層級）
        {
            const std::vector<uint8_t> pimg = img_of(parent);
            for (int i = 0; i < NL; ++i)
                if (bfx::range_check(pimg, bfx::child_bounds(parent, i, root, ps, 0), false))
                    fail("(r2b) child redirected to internal page not caught", kst, i);
        }
        // (r3) 分隔鍵翻轉
        const std::vector<uint8_t> pimg = img_of(parent);
        for (int s = 0; s < NL - 1; ++s)
            for (int b = 0; b < 64; ++b) {
                std::vector<uint8_t> bad = pimg;
                bad[32 + s * 8 + b / 8] ^= (uint8_t)(1u << (b % 8));
                bool fatal = false;
                if (!bfx::sanity_check(bad, 100, 253, 4096, 1000, fatal)) continue;   // SANITY 已抓
                const BTreeNode bp = BTreeNode::deserialize(100, bad);
                const uint64_t S = parent.keys[s], S2 = bp.keys[s];
                // 有害 ⇔ 某個既存 key 的路由改變：S2 > S（[S,S2) 改走左邊，S 本身即是）
                //        或 S2 < S 且左 child 有 key ≥ S2
                const bool harmful = (S2 > S) || (S2 <= leaves[s].keys.back());
                if (!harmful) continue;
                const bool c_left  = !bfx::range_check(li[s],     bfx::child_bounds(bp, s,     root, ps, 0), false);
                const bool c_right = !bfx::range_check(li[s + 1], bfx::child_bounds(bp, s + 1, root, ps, 0), false);
                if (!c_left && !c_right) fail("(r3) harmful separator flip not caught", s, b);
                // 上翻（S2 > S）只能在走訪右 child 時抓到（左 child 的 keys 仍 < S < S2）
                if (S2 > S && !c_right) fail("(r3) upward flip not caught at right child", s, b);
            }
        // (r4) internal child 的 inherit 界限
        {
            bfx::ChildBounds gb; gb.has_lo = true; gb.lo = parent.keys[0]; gb.lo_src.pid = 200;
            gb.has_hi = true; gb.hi = (uint64_t)5000 << kst; gb.hi_src.pid = 200;
            BTreeNode in{}; in.page_id = 101; in.node_type = 0; in.next_leaf = INVALID_PAGE;
            in.keys = {parent.keys[1], parent.keys[2]}; in.children = {1, 2, 3};
            bfx::ChildBounds cb = bfx::child_bounds(parent, 1, root, ps, 1);   // lo = keys[0], hi = keys[1]
            cb.has_hi = false;
            if (!bfx::range_check(img_of(in), cb, false)) fail("(r4) clean internal alarm", kst, 0);
            in.keys = {parent.keys[0], parent.keys[2]};                        // 首 key == lo → 違規
            if (bfx::range_check(img_of(in), cb, false)) fail("(r4) internal key == lo not caught", kst, 0);
            // leftmost child inherit：lo 來自祖父
            const bfx::ChildBounds c0 = bfx::child_bounds(parent, 0, gb, ps, 0);
            if (!c0.has_lo || c0.lo != gb.lo || c0.lo_src.pid != 200) fail("(r4) inherit lo", kst, 0);
            const bfx::ChildBounds cN = bfx::child_bounds(parent, NL - 1, gb, ps, 0);
            if (!cN.has_hi || cN.hi != gb.hi || cN.hi_src.pid != 200) fail("(r4) inherit hi", kst, 0);
        }
    }
}

// ── E19 / E18：slack dummy 與對齊自測 ────────────────────────────────────────
//   (s1) encode → strip 往返等於原邏輯節點；實體 n_keys ≤ order；通過 sanity_check
//   (s2) 滿的 node 不加 dummy；n ≥ free 時 dummy 數 == free（均勻散佈）
//   (s3) 帶右 dummy 的真 key 往上翻（越過 K+1）必被 sanity_check 抓到；both 另含往下翻
//   (s4) 連續 key（stride 0）：相撞的 dummy 被略過，只有最後一個 key 有右 dummy
//   (s5) 對齊：實體 image（含 dummy）在 align=stride 下通過；真 key 低位被翻 → 抓到；
//        dummy 的 value 被翻離 sentinel（看起來像真 key、低位非 0）→ 抓到
static void slack_self_test() {
    auto fail = [](const char* what, int a, int b) {
        fprintf(stderr, "FATAL: slack self-test failed: %s (%d, %d)\n", what, a, b); std::abort();
    };
    using SG = bfx::SlackGuard;
    for (SG g : {SG::RIGHT, SG::BOTH}) {
        for (uint32_t kst : {8u, 16u, 32u}) {
            for (uint32_t n : {1u, 50u, 126u, 174u, 200u, 253u}) {
                BTreeNode lg{}; lg.page_id = 3; lg.node_type = 1; lg.next_leaf = 9;
                for (uint32_t i = 0; i < n; ++i) {
                    const uint64_t k = (uint64_t)(777 + i) << kst;
                    lg.keys.push_back(k); lg.values.push_back(k * 7 + 13);
                }
                const BTreeNode ph = bfx::add_slack_dummies(lg, 253, g);
                const size_t nd = ph.keys.size() - n;
                if (ph.keys.size() > 253) fail("(s1) over order", (int)n, (int)ph.keys.size());
                const size_t want = std::min<size_t>(253 - n, (g == SG::RIGHT ? 1 : 2) * (size_t)n);
                if (nd != want) fail("(s2) dummy count", (int)n, (int)nd);
                const std::vector<uint8_t> img = img_of(ph);
                bool fatal = false;
                bfx::SanityExt ext; ext.slack = true; ext.align_log2 = kst;
                if (!bfx::sanity_check(img, 3, 253, 4096, 1000, fatal, &ext)) fail("(s1) physical fails sanity+align", (int)n, kst);
                BTreeNode back = BTreeNode::deserialize(3, img);
                bfx::strip_slack_dummies(back);
                if (back.keys != lg.keys || back.values != lg.values || back.next_leaf != lg.next_leaf)
                    fail("(s1) round trip", (int)n, kst);
                // (s3)
                for (size_t j = 0; j < ph.keys.size(); ++j) {
                    if (ph.values[j] == bfx::GUARD_SENTINEL_VALUE) continue;
                    const bool rdum = (j + 1 < ph.keys.size() && ph.values[j + 1] == bfx::GUARD_SENTINEL_VALUE
                                       && ph.keys[j + 1] == ph.keys[j] + 1);
                    const bool ldum = (j > 0 && ph.values[j - 1] == bfx::GUARD_SENTINEL_VALUE
                                       && ph.keys[j - 1] == ph.keys[j] - 1);
                    for (int b = 0; b < 64; ++b) {
                        const bool up = !((ph.keys[j] >> b) & 1);
                        if (!(up ? rdum : ldum)) continue;
                        std::vector<uint8_t> bad = img;
                        bad[32 + j * 8 + b / 8] ^= (uint8_t)(1u << (b % 8));
                        if (bfx::sanity_check(bad, 3, 253, 4096, 1000, fatal, nullptr))
                            fail("(s3) real key flipped across its dummy not caught", (int)j, b);
                    }
                }
                // (s5)
                for (size_t j = 0; j < ph.keys.size(); ++j) {
                    std::vector<uint8_t> bad = img;
                    if (ph.values[j] == bfx::GUARD_SENTINEL_VALUE) {
                        bad[32 + ph.keys.size() * 8 + j * 8] ^= 0x01;      // value 6 → 7
                    } else {
                        bad[32 + j * 8] ^= 0x01;                            // key 低位
                    }
                    if (bfx::sanity_check(bad, 3, 253, 4096, 1000, fatal, &ext))
                        fail("(s5) align violation not caught", (int)j, kst);
                }
            }
        }
        // (s4)
        BTreeNode lg{}; lg.page_id = 3; lg.node_type = 1; lg.next_leaf = INVALID_PAGE;
        for (uint64_t i = 0; i < 100; ++i) { lg.keys.push_back(500 + i); lg.values.push_back((500 + i) * 7 + 13); }
        const BTreeNode ph = bfx::add_slack_dummies(lg, 253, g);
        const size_t want4 = (g == SG::RIGHT) ? 1 : 2;
        if (ph.keys.size() != 100 + want4 || ph.keys.back() != 600) fail("(s4) collisions", (int)ph.keys.size(), 0);
    }
    // internal 不加 dummy
    BTreeNode in{}; in.page_id = 1; in.node_type = 0; in.keys = {10, 20}; in.children = {1, 2, 3};
    if (bfx::add_slack_dummies(in, 253, SG::BOTH).keys.size() != 2) fail("(s2) internal got dummies", 0, 0);
}

// ── main ──────────────────────────────────────────────────────────────────────
int main(int argc, char** argv) {
    fast_crc_self_test();
    ctrl_crc_self_test();
    hybrid_self_test();
    inpage_self_test();
    guard_unit_self_test();
    range_self_test();
    slack_self_test();
    bfx::ExpConfig cfg;
    if (!cfg.parse_args(argc, argv)) return 2;

    // ── E13 / E16 組態檢查 ───────────────────────────────────────────────────
    if (bfx::is_inpage(cfg.scheme) && cfg.verify_mode != bfx::VerifyMode::EVERY_READ) {
        fprintf(stderr, "ERROR: INPAGE_* schemes support EVERY_READ only\n");
        return 2;
    }
    // E21：key 映射組態檢查
    if (cfg.key_map != bfx::KeyMap::NONE) {
        if (cfg.guard != bfx::GuardMode::NONE) {
            fprintf(stderr, "ERROR: --key_map requires --guard=none\n"); return 2;
        }
        if (cfg.key_map == bfx::KeyMap::SHIFT && cfg.key_dist != bfx::KeyDist::STRIDE) {
            fprintf(stderr, "ERROR: --key_map=shift requires --key_dist=stride\n"); return 2;
        }
    }
    if (cfg.guard != bfx::GuardMode::NONE) {
        if ((cfg.guard == bfx::GuardMode::MID || cfg.guard == bfx::GuardMode::GRID) &&
            cfg.key_dist != bfx::KeyDist::STRIDE) {
            fprintf(stderr, "ERROR: --guard=mid/grid requires --key_dist=stride\n");
            return 2;
        }
        if (cfg.guard == bfx::GuardMode::GRID &&
            (cfg.guard_grid_log2 < 1 || cfg.guard_grid_log2 >= cfg.key_stride_log2 ||
             cfg.key_stride_log2 - cfg.guard_grid_log2 > 6)) {
            fprintf(stderr, "ERROR: --guard=grid needs 1 <= guard_grid_log2 < key_stride_log2 "
                            "and at most 63 dummies per key (k - g <= 6)\n");
            return 2;
        }
        const uint32_t need = (cfg.guard == bfx::GuardMode::BOTH) ? 2 : 1;
        if (cfg.key_dist == bfx::KeyDist::STRIDE && cfg.key_stride_log2 < need) {
            fprintf(stderr, "ERROR: --guard=%s needs key_stride_log2 >= %u\n",
                    bfx::guard_mode_name(cfg.guard), need);
            return 2;
        }
    }
    if (cfg.guard != bfx::GuardMode::GRID && cfg.guard_grid_log2 != 0) {
        fprintf(stderr, "ERROR: --guard_grid_log2 requires --guard=grid\n");
        return 2;
    }

    // ── E17–E20 組態檢查 ─────────────────────────────────────────────────────
    const bool ext_on = cfg.sanity_range || cfg.sanity_align_log2 > 0 ||
                        cfg.slack_guard != bfx::SlackGuard::NONE;
    if (ext_on && cfg.scheme != bfx::Scheme::SANITY) {
        fprintf(stderr, "ERROR: --sanity_range/--sanity_align_log2/--slack_guard require --scheme=SANITY\n");
        return 2;
    }
    if (cfg.slack_guard != bfx::SlackGuard::NONE && cfg.guard != bfx::GuardMode::NONE) {
        fprintf(stderr, "ERROR: --slack_guard and --guard are mutually exclusive\n");
        return 2;
    }
    if (cfg.sanity_align_log2 > 0 &&
        (cfg.key_dist != bfx::KeyDist::STRIDE || cfg.sanity_align_log2 > cfg.key_stride_log2 ||
         cfg.guard != bfx::GuardMode::NONE)) {
        fprintf(stderr, "ERROR: --sanity_align_log2 needs stride keys with key_stride_log2 >= it and no --guard\n");
        return 2;
    }

    // ── key 稀疏度（E7′）的溢位護欄 ──────────────────────────────────────────
    // 實際 key = index << key_stride_log2。最大的 index 有兩個來源：
    //   (a) 工作負載：prefill_keys + n_ops（全部 op 都是 insert 的上界）
    //   (b) miss key：1 000 000 000 + U(0, 999 999 999) ≤ 1 999 999 999 < 2^31
    // (b) 恆大於 (a)（本專案的規模 ≤ 5M keys），且 2^31 << 32 = 2^63 < 2^64，
    // 故 stride ≤ 32 一律安全；仍逐項檢查以免日後改參數時靜默溢位。
    if (cfg.key_dist == bfx::KeyDist::GEOMGAP && cfg.key_stride_log2 > 32) {
        fprintf(stderr, "ERROR: geomgap mean gap 2^%u too large (max 2^32)\n",
                cfg.key_stride_log2);
        return 2;
    }
    if (cfg.key_dist == bfx::KeyDist::STRIDE && cfg.key_stride_log2 > 0) {
        const uint64_t max_wl_index = (uint64_t)cfg.prefill_keys + cfg.n_ops;
        const uint64_t max_miss_idx = 1999999999ull;
        const uint64_t max_index    = std::max(max_wl_index, max_miss_idx);
        if (cfg.key_stride_log2 > 63 ||
            max_index > (UINT64_MAX >> cfg.key_stride_log2)) {
            fprintf(stderr,
                    "ERROR: key_stride_log2=%u overflows uint64 "
                    "(max key index %llu << %u)\n",
                    cfg.key_stride_log2, (unsigned long long)max_index,
                    cfg.key_stride_log2);
            return 2;
        }
    }

    if (cfg.run_id.empty()) {
        char buf[192];
        const char* backend_tag = (cfg.backend == "r2") ? "r2_" : "";
        if (cfg.budget_bytes == UINT64_MAX)
            std::snprintf(buf, sizeof buf, "%s%s_%s_l%g_binf_s%u",
                          backend_tag,
                          bfx::scheme_name(cfg.scheme), bfx::policy_name(cfg.policy),
                          cfg.lambda_page, cfg.seed);
        else
            std::snprintf(buf, sizeof buf, "%s%s_%s_l%g_b%llu_s%u",
                          backend_tag,
                          bfx::scheme_name(cfg.scheme), bfx::policy_name(cfg.policy),
                          cfg.lambda_page, (unsigned long long)cfg.budget_bytes, cfg.seed);
        cfg.run_id = buf;
        if (cfg.verify_mode == bfx::VerifyMode::PERIODIC) {
            std::snprintf(buf, sizeof buf, "_p%g", cfg.theta_s);
            cfg.run_id += buf;
        } else {
            cfg.run_id += "_er";
        }
        if (cfg.sanity_always) cfg.run_id += "_sa";
    }

#ifdef _WIN32
    freopen("NUL", "w", stdout);   // 抑制 v2 SSD debug 輸出（Windows）
#else
    freopen("/dev/null", "w", stdout);  // 抑制 v2 SSD debug 輸出（Linux/macOS）
#endif

    if (cfg.key_map != bfx::KeyMap::NONE) bfx::keymap_self_test(cfg);   // E21（失敗即 abort）

    // ── Backend 初始化 ────────────────────────────────────────────────────────
#ifdef HAVE_RAMULATOR2
    IFrontEnd*      r2_fe  = nullptr;
    IMemorySystem*  r2_mem = nullptr;
    RamulatorRAM*   r2ram  = nullptr;
#endif

    SSD* ssd = nullptr;   // ram 後端有；r2 後端為 nullptr
    RAM* ram = nullptr;   // ram 後端有；r2 後端為 nullptr
    IRAM* iram = nullptr;
    RAMStats ram_baseline{};

    if (cfg.backend == "ram") {
        // ── 純 C++ 模擬（原版行為） ──────────────────────────────────────────
        ssd_config sc{};
        sc.max_block_count_    = cfg.ssd_blocks;
        sc.pages_per_block_    = cfg.pages_per_block;
        sc.page_size_bytes_    = cfg.page_size;
        sc.logical_page_count_ = (uint32_t)(cfg.ssd_blocks * cfg.pages_per_block * 0.93);
        ssd = new SSD(sc);

        RAMConfig rc{};
        rc.rows_per_bank = cfg.ram_rows_per_bank ? cfg.ram_rows_per_bank
                                                 : cfg.ssd_blocks * cfg.pages_per_block / 8;
        rc.lambda_eff = 0.0;
        rc.t_mem      = cfg.t_mem_s;
        rc.t_ssd      = cfg.t_ssd_s;
        rc.seed       = cfg.seed;
        ram  = new RAM(rc, ssd);
        iram = ram;
    }
#ifdef HAVE_RAMULATOR2
    else if (cfg.backend == "r2") {
        // ── Ramulator2 DDR4 後端 ─────────────────────────────────────────────
        if (cfg.r2_config_path.empty()) {
            fprintf(stderr, "ERROR: --r2_config=<yaml> is required for --backend=r2\n");
            return 2;
        }
        auto r2cfg = Config::parse_config_file(cfg.r2_config_path);
        r2_fe  = Factory::create_frontend(r2cfg);
        r2_mem = Factory::create_memory_system(r2cfg);
        r2_fe->connect_memory_system(r2_mem);
        r2_mem->connect_frontend(r2_fe);

        // SSD：行為對齊 ram 後端（write-through、LRU reload、crash_rescue 乾淨副本）
        ssd_config sc{};
        sc.max_block_count_    = cfg.ssd_blocks;
        sc.pages_per_block_    = cfg.pages_per_block;
        sc.page_size_bytes_    = cfg.page_size;
        sc.logical_page_count_ = (uint32_t)(cfg.ssd_blocks * cfg.pages_per_block * 0.93);
        ssd = new SSD(sc);

        // DataLayer 容量上限（與 ram 後端的 DRAM 容量計算方式一致）
        const uint64_t cap_pages = cfg.ram_rows_per_bank
            ? (uint64_t)cfg.ram_rows_per_bank * DRAM_NUM_BANKS
            : (uint64_t)(cfg.ssd_blocks * cfg.pages_per_block) / 8;

        // seed 必須明確給定：舊版以物件位址推導種子，受 ASLR 影響導致結果不可重現
        r2ram = new RamulatorRAM(r2_mem, ssd, cap_pages, cfg.r2_ecc,
                                 cfg.seed ^ 0x7a11u);
        iram  = r2ram;
        fprintf(stderr, "[r2] DDR4 tCK=%.3f ns  tx_bytes=%d  cap=%llu pages  ecc=%s\n",
                r2_mem->get_tCK(), r2_mem->get_tx_bytes(),
                (unsigned long long)cap_pages,
                cfg.r2_ecc ? "on" : "off");
    }
#endif
    else {
        fprintf(stderr, "ERROR: unknown backend '%s' (available: ram"
#ifdef HAVE_RAMULATOR2
                ", r2"
#endif
                ")\n", cfg.backend.c_str());
        return 2;
    }

    // ── 建棧 ─────────────────────────────────────────────────────────────────
    bfx::Metrics       metrics;
    bfx::ShadowStore   shadow(cfg, &metrics, cfg.seed ^ 0x9e3779b9u);
    bfx::GuardedRAM    gram(iram, ssd, &shadow, &metrics, &cfg);
    bfx::FaultInjector inj(iram, &gram, &cfg, &metrics, cfg.seed ^ 0x12345u);
    bfx::ExpBTree      tree(&gram, cfg.order, cfg.page_size);

    // E21：key 映射（key_map=none → km 為空，以下所有分支皆走舊路徑）
    const uint64_t km_pred_inserts =
        (cfg.key_map != bfx::KeyMap::NONE) ? bfx::keymap_predict_inserts(cfg, cfg.prefill_keys) : 0;
    std::unique_ptr<bfx::KeyMapper> km;
    if (cfg.key_map != bfx::KeyMap::NONE)
        km.reset(new bfx::KeyMapper(&tree, cfg, (uint64_t)cfg.prefill_keys + km_pred_inserts, &metrics));
    uint64_t km_actual_inserts = 0;
    auto app_insert = [&](uint64_t k, uint64_t v, double& l) {
        if (km) km->insert(k, v, l); else tree.insert(k, v, l);
    };
    auto app_search = [&](uint64_t k, uint64_t& v, double& l, uint64_t& probes) {
        if (km) return km->lookup(k, v, l, probes);
        probes = 1;
        return tree.search(k, v, l);
    };

    // ── prefill（無故障、不推進時間；不計入任何回報數字）─────────────────────
    std::map<uint64_t, uint64_t> ref;
    std::vector<uint64_t> inserted_keys;
    // key 稀疏度（E7′）：實際 key = index << key_stride_log2。
    // stride = 0 時 `idx << 0 == idx`，與舊行為逐位元組相同（回歸護欄）。
    const uint32_t kstride = cfg.key_stride_log2;
    // ── E8：key 分佈產生器（stride 模式完全不觸碰下列任何 RNG）──────────────
    std::mt19937_64 krng(cfg.seed ^ 0x6b657964u);   // key-gen / append / miss 專用
    const double kd_N = (double)std::max<uint32_t>(cfg.prefill_keys, 1);
    // geometric gap（g ≥ 1、平均 = mean）：g = 1 + Geom(p = 1/mean)
    auto geom_gap = [&](double mean) -> uint64_t {
        if (mean <= 1.0) return 1;
        std::geometric_distribution<uint64_t> g(1.0 / mean);
        return 1 + g(krng);
    };
    const double random64_mean_gap = std::ldexp(1.0, 63) / kd_N;   // [0,2^63) 上的均勻點
    const uint64_t CLUSTER_SIZE = 1000;
    auto cluster_key = [&](uint64_t idx) {
        return ((idx / CLUSTER_SIZE) << 32) | (idx % CLUSTER_SIZE);
    };
    auto gen_sorted_keys = [&]() {
        std::vector<uint64_t> v;
        const uint64_t N = cfg.prefill_keys;
        switch (cfg.key_dist) {
            case bfx::KeyDist::STRIDE: break;   // 不產生（沿用 idx << stride）
            case bfx::KeyDist::RANDOM64: {
                std::uniform_int_distribution<uint64_t> u(0, (1ull << 63) - 1);
                while (v.size() < N) {
                    while (v.size() < N) v.push_back(u(krng));
                    std::sort(v.begin(), v.end());
                    v.erase(std::unique(v.begin(), v.end()), v.end());
                }
                break;
            }
            case bfx::KeyDist::GEOMGAP: {
                uint64_t acc = 0;
                const double mean = std::ldexp(1.0, (int)cfg.key_stride_log2);
                for (uint64_t i = 0; i < N; ++i) { acc += geom_gap(mean); v.push_back(acc); }
                break;
            }
            case bfx::KeyDist::CLUSTERED:
                for (uint64_t i = 0; i < N; ++i) v.push_back(cluster_key(i));
                break;
        }
        return v;
    };
    uint64_t kd_max_key = 0;   // 目前最大 key（append 用；只含真 key）
    // E13：dummy key 集合（碰撞過濾）與計數
    std::unordered_set<uint64_t> dummy_set;
    std::vector<uint64_t> prefill_dummies;
    uint64_t n_dummy_keys = 0;
    const bool guarded = (cfg.guard != bfx::GuardMode::NONE);
    {
        // 洗的是 **index**（0..prefill-1），與舊版同一個 RNG、同一個序列；
        // 只有「index → key」這一步多了左移，插入順序完全不變。
        // E8：非 stride 分佈先產生「排序後的 key 集合」sorted_keys，
        // 插入順序 = 同一個 index 洗牌 → key = sorted_keys[idx]（與 stride 同構）。
        const std::vector<uint64_t> sorted_keys = gen_sorted_keys();
        auto real_key = [&](uint64_t idx) {
            return (cfg.key_dist == bfx::KeyDist::STRIDE) ? (idx << kstride) : sorted_keys[idx];
        };
        // E13：dummy key 清單（依真 key 的排序順序產生；與任何真 key 或先前 dummy 相撞者略過）。
        // index 空間 = [0, N) 真 key ∪ [N, N+D) dummy；guard=none 時 D = 0，
        // 洗牌的是同長度的 iota、同一個 RNG → 插入順序與舊版逐一相同。
        const uint64_t N = cfg.prefill_keys;
        if (cfg.guard != bfx::GuardMode::NONE) {
            std::vector<uint64_t> all_real(N);
            for (uint64_t i = 0; i < N; ++i) all_real[i] = real_key(i);
            std::sort(all_real.begin(), all_real.end());
            for (uint64_t i = 0; i < N; ++i)
                for (uint64_t d : guard_candidates(real_key(i), cfg.guard, kstride, cfg.guard_grid_log2)) {
                    if (std::binary_search(all_real.begin(), all_real.end(), d)) continue;
                    if (!dummy_set.insert(d).second) continue;
                    prefill_dummies.push_back(d);
                }
        }
        std::vector<uint64_t> keys(N + prefill_dummies.size());
        std::iota(keys.begin(), keys.end(), uint64_t{0});
        std::shuffle(keys.begin(), keys.end(), std::mt19937(cfg.seed ^ 0x5f3759dfu));
        for (uint64_t idx : keys) {
            if (idx >= N) {                       // E13：dummy entry
                double lat = 0.0;
                tree.insert(prefill_dummies[idx - N], bfx::GUARD_SENTINEL_VALUE, lat);
                if (ssd) ssd->GC();
                tree.note_op_boundary();
                ++n_dummy_keys;
                continue;
            }
            const uint64_t k = real_key(idx);
            if (k * 7 + 13 == bfx::GUARD_SENTINEL_VALUE) {
                fprintf(stderr, "FATAL: real key %llu maps to the guard sentinel value\n",
                        (unsigned long long)k);
                return 3;
            }
            double lat = 0.0;
            app_insert(k, k * 7 + 13, lat);   // E21（none → tree.insert）
            if (ssd) ssd->GC();
            tree.note_op_boundary();
            ref[k] = k * 7 + 13;
            inserted_keys.push_back(k);
            if (k > kd_max_key) kd_max_key = k;
        }
    }
    // E13 端到端自測（只在 guard ≠ none；prefill 期間無注入）：取樣 dummy 必須
    // 「原始搜尋找得到且 value == sentinel」，且對應真 key 搜得到正確 value。
    // 之後的 metrics 重置會抹掉這些讀取。
    if (guarded) {
        if (prefill_dummies.empty()) { fprintf(stderr, "FATAL: guard on but no dummies\n"); return 3; }
        const size_t step = std::max<size_t>(1, prefill_dummies.size() / 500);
        for (size_t i = 0; i < prefill_dummies.size(); i += step) {
            tree.note_op_boundary();
            uint64_t v = 0; double lat = 0.0;
            if (!tree.search(prefill_dummies[i], v, lat) || v != bfx::GUARD_SENTINEL_VALUE) {
                fprintf(stderr, "FATAL: guard e2e self-test: dummy %llu not found raw\n",
                        (unsigned long long)prefill_dummies[i]);
                return 3;
            }
        }
        for (size_t i = 0; i < inserted_keys.size(); i += step) {
            tree.note_op_boundary();
            uint64_t v = 0; double lat = 0.0;
            const uint64_t k = inserted_keys[i];
            if (!tree.search(k, v, lat) || v != k * 7 + 13) {
                fprintf(stderr, "FATAL: guard e2e self-test: real key %llu wrong\n",
                        (unsigned long long)k);
                return 3;
            }
        }
        fprintf(stderr, "guard e2e self-test PASS (%zu dummies, mode=%s)\n",
                prefill_dummies.size(), bfx::guard_mode_name(cfg.guard));
    }
    // E17–E20 端到端自測：prefill 無注入 → 任何報警都是誤報（新規則與真實樹的不變量不符）。
    // 另取樣搜尋：真 key 必須找到正確 value，且過程零報警。之後的 metrics 重置會抹掉這些讀取。
    if (ext_on) {
        if (metrics.page_read.fp || metrics.page_read.tp || metrics.n_range_alarms || metrics.n_recoveries) {
            fprintf(stderr, "FATAL: E17-E20 self-test: clean prefill raised alarms (fp=%llu range=%llu)\n",
                    (unsigned long long)metrics.page_read.fp, (unsigned long long)metrics.n_range_alarms);
            return 3;
        }
        const size_t step = std::max<size_t>(1, inserted_keys.size() / 2000);
        for (size_t i = 0; i < inserted_keys.size(); i += step) {
            tree.note_op_boundary();
            uint64_t v = 0; double lat = 0.0;
            const uint64_t k = inserted_keys[i];
            if (!tree.search(k, v, lat) || v != k * 7 + 13 || tree.alarm_seen_this_op()) {
                fprintf(stderr, "FATAL: E17-E20 self-test: key %llu wrong or alarmed\n", (unsigned long long)k);
                return 3;
            }
        }
        if (cfg.slack_guard != bfx::SlackGuard::NONE) {
            uint64_t r = 0, wr = 0, wl = 0, d = 0;
            tree.slack_scan(r, wr, wl, d);
            if (r != inserted_keys.size() || d == 0) {
                fprintf(stderr, "FATAL: slack self-test: real=%llu (want %zu) dummies=%llu\n",
                        (unsigned long long)r, inserted_keys.size(), (unsigned long long)d);
                return 3;
            }
            fprintf(stderr, "slack after prefill: real=%llu dummies=%llu right=%.3f left=%.3f\n",
                    (unsigned long long)r, (unsigned long long)d, (double)wr / r, (double)wl / r);
        }
        fprintf(stderr, "E17-E20 e2e self-test PASS (range=%d align=%u slack=%s)\n",
                (int)cfg.sanity_range, cfg.sanity_align_log2, bfx::slack_guard_name(cfg.slack_guard));
    }
    metrics = bfx::Metrics{};
    metrics.shadow_bytes_used_max = shadow.bytes_used();
    ram_baseline = iram->get_stats();   // 扣除 prefill 的 RAM 活動（兩後端皆適用）

    // ── TTL 冒煙測試（--r2_ttl_s=<秒>；0 = 停用）─────────────────────────────
    // prefill 之後才套用，避免建樹階段被大量 TTL 重載拖慢。
    // 正式實驗的冷熱分類 TTL 由 ttl_theta_experiment 的 driver 負責。
    if (cfg.r2_ttl_s > 0.0) {
        const uint64_t n_pages = gram.pages_allocated();
        for (uint64_t p = 0; p < n_pages; ++p) iram->set_ttl(p, cfg.r2_ttl_s);
        fprintf(stderr, "[ttl] 對 %llu 頁設定 TTL = %g s\n",
                (unsigned long long)n_pages, cfg.r2_ttl_s);
    }

    // ── 主迴圈 ────────────────────────────────────────────────────────────────
    std::mt19937 wrng(cfg.seed ^ 0xabcdefu);
    std::bernoulli_distribution do_search(cfg.read_ratio);
    std::bernoulli_distribution do_miss(cfg.miss_ratio);
    uint64_t insert_counter = 0;
    const uint32_t progress_step = cfg.n_ops / 10;

    for (uint32_t i = 0; i < cfg.n_ops; ++i) {
        tree.note_op_boundary();
        const double t0 = tree.now();
        tree.advance_time(cfg.dt_op_s);
        inj.advance(t0, tree.now());

        double lat = 0.0;
        if (do_search(wrng)) {
            uint64_t key;
            if (do_miss(wrng) || inserted_keys.empty())
                // miss key = (1e9 + U(0,1e9)) << stride。
                // 為什麼這樣才「保證不存在」：所有真 key 都是 index << stride 且
                // index ≤ prefill_keys + n_ops（本專案 ≤ 5.03e6），而這裡的
                // index ≥ 1e9 → 永遠落在已插入 index 集合之外，**每個 stride 皆然**。
                // 同時它在 stride = 0 時退化成與舊版完全相同的運算式
                // （消耗同一個 RNG draw、同一個值），故 stride=0 是嚴格的 no-op。
                // 另一個好處：miss key 相對「最大真 key」的位置（約 1000 倍）
                // 不隨 stride 改變 → 每個 stride 的搜尋路徑結構相同，可比。
            {
                key = (1000000000ull +
                       std::uniform_int_distribution<uint64_t>(0, 999999999ull)(wrng))
                      << kstride;
                // E8：非 stride 分佈——上面的 wrng draw 照樣消耗（保持 op 序列與
                // stride 模式對齊），miss key 改為在 [0, 2·max_key+1] 均勻抽、
                // 落在 ref 內就重抽（draw-and-reject，查詢當下保證不存在）。
                // 上界取 2·max 而非 max：稠密 key 集合（如 geomgap@k=0）在 [0,max]
                // 內幾乎無空位，會讓重抽不收斂；2·max 保證接受率 ≥ ~1/2。
                if (cfg.key_dist != bfx::KeyDist::STRIDE) {
                    const uint64_t hi = (kd_max_key > (UINT64_MAX - 1) / 2) ? UINT64_MAX
                                                                          : 2 * kd_max_key + 1;
                    std::uniform_int_distribution<uint64_t> u(0, hi);
                    int tries = 0;
                    do { key = u(krng); } while (ref.count(key) && ++tries < 64);
                    // 稠密 key 集合（如 geomgap@0）幾乎抽不到空位：64 次後退回
                    // 「max_key 之上」的保證不存在區間（E8 的分佈拒絕率 ≤ 2^-8，
                    // 實務上不會觸發）。
                    if (ref.count(key)) {
                        std::uniform_int_distribution<uint64_t> up(1, 1ull << 20);
                        key = kd_max_key + up(krng);
                    }
                }
            }
            else
                key = inserted_keys[std::uniform_int_distribution<size_t>(
                          0, inserted_keys.size() - 1)(wrng)];

            uint64_t val = 0, probes = 0;
            bool found = app_search(key, val, lat, probes);   // E21（none → tree.search）
            // E13：dummy 對應用層不可見——讀到 sentinel value 視同找不到
            if (guarded && found && val == bfx::GUARD_SENTINEL_VALUE) found = false;
            metrics.n_searches++;
            const auto it = ref.find(key);
            const bool expect = (it != ref.end());
            if (km) {   // E21
                if (expect) { metrics.n_probes_hit  += probes; metrics.n_map_lookups_hit++; }
                else        { metrics.n_probes_miss += probes; metrics.n_map_lookups_miss++; }
            }
            const bool wrong = (found != expect) || (found && expect && val != it->second);
            if (wrong) {
                metrics.n_wrong_total++;
                const bool sdc = !tree.alarm_seen_this_op();
                if (sdc) metrics.n_wrong_undetected++;
                // E12：三分類（互斥窮盡）
                if (expect && !found)      { metrics.n_wrong_missing++; if (sdc) metrics.n_sdc_missing++; }
                else if (!expect && found) { metrics.n_wrong_phantom++; if (sdc) metrics.n_sdc_phantom++; }
                else                       { metrics.n_wrong_value++;   if (sdc) metrics.n_sdc_value++; }
            }
        } else {
            uint64_t key = 0;
            switch (cfg.key_dist) {
                case bfx::KeyDist::STRIDE:
                    key = ((uint64_t)cfg.prefill_keys + insert_counter++) << kstride; break;
                case bfx::KeyDist::RANDOM64:
                    key = kd_max_key + geom_gap(random64_mean_gap); break;
                case bfx::KeyDist::GEOMGAP:
                    key = kd_max_key + geom_gap(std::ldexp(1.0, (int)kstride)); break;
                case bfx::KeyDist::CLUSTERED:
                    key = cluster_key((uint64_t)cfg.prefill_keys + insert_counter++); break;
            }
            if (key > kd_max_key) kd_max_key = key;
            if (guarded && (dummy_set.count(key) || key * 7 + 13 == bfx::GUARD_SENTINEL_VALUE)) {
                fprintf(stderr, "FATAL: new real key %llu collides with a dummy key / sentinel\n",
                        (unsigned long long)key);
                return 3;
            }
            app_insert(key, key * 7 + 13, lat);   // E21（none → tree.insert）
            ++km_actual_inserts;
            ref[key] = key * 7 + 13;
            inserted_keys.push_back(key);
            // E13：同一個 op 內插入 dummy，延遲累加進本 op（方案的真實成本）
            if (guarded)
                for (uint64_t d : guard_candidates(key, cfg.guard, kstride, cfg.guard_grid_log2)) {
                    if (ref.count(d) || !dummy_set.insert(d).second) continue;
                    tree.insert(d, bfx::GUARD_SENTINEL_VALUE, lat);
                    ++n_dummy_keys;
                }
        }
        metrics.add_op_latency(lat);
        metrics.n_ops++;
        if (ssd) ssd->GC();

        if (progress_step && (i + 1) % progress_step == 0)
            fprintf(stderr, "progress %u%%\n",
                    (unsigned)((uint64_t)(i + 1) * 100 / cfg.n_ops));
    }

    // ── 完整性掃描 ────────────────────────────────────────────────────────────
    for (const auto& kv : ref) {
        tree.note_op_boundary();
        uint64_t val = 0, probes = 0;
        double lat = 0.0;
        bool found = app_search(kv.first, val, lat, probes);   // E21（none → tree.search）
        if (guarded && found && val == bfx::GUARD_SENTINEL_VALUE) found = false;
        if (!found || val != kv.second) metrics.n_final_integrity_errors++;
        if (ssd) ssd->GC();
    }

    // ── E8：以最終 key 集合計算 SANITY 的解析預測（純觀測）────────────────────
    {
        std::vector<uint64_t> ks;
        ks.reserve(ref.size());
        for (const auto& kv : ref) ks.push_back(kv.first);
        const size_t n = ks.size();
        if (n >= 2) {
            double sum_rel = 0.0, sum_exact = 0.0;
            for (size_t i = 0; i < n; ++i) {
                const bool hl = (i > 0), hr = (i + 1 < n);
                const uint64_t gl = hl ? ks[i] - ks[i - 1] : 0;
                const uint64_t gr = hr ? ks[i + 1] - ks[i] : 0;
                const uint64_t m  = (hl && hr) ? std::min(gl, gr) : (hl ? gl : gr);
                const int blind = 63 - __builtin_clzll(m);   // floor(log2(m))，m ≥ 1
                sum_rel += (64.0 - blind) / 64.0;
                int det = 0;
                for (int b = 0; b < 64; ++b) {
                    const uint64_t d = 1ull << b;
                    if ((ks[i] >> b) & 1) { if (hl && d >= gl) ++det; }   // key 變小
                    else                  { if (hr && d >= gr) ++det; }   // key 變大
                }
                sum_exact += det / 64.0;
            }
            metrics.pred_sanity_rel   = sum_rel / (double)n;
            metrics.pred_sanity_exact = sum_exact / (double)n;
        }
    }

    // ── 快照與輸出 ────────────────────────────────────────────────────────────
    metrics.n_pages_allocated = gram.pages_allocated();
    metrics.n_dummy_keys      = n_dummy_keys;
    metrics.tree_height       = tree.height();
    if (km) {   // E21
        metrics.map_slots = km->slots();
        metrics.map_lmax  = km->lmax();
        if (km_actual_inserts != km_pred_inserts) {
            fprintf(stderr, "FATAL: E21 insert prediction %llu != actual %llu\n",
                    (unsigned long long)km_pred_inserts, (unsigned long long)km_actual_inserts);
            return 3;
        }
        fprintf(stderr, "E21 key_map=%s M=%llu L_max=%llu inserts=%llu alarms=%llu\n",
                bfx::key_map_name(cfg.key_map), (unsigned long long)km->slots(),
                (unsigned long long)km->lmax(), (unsigned long long)km_actual_inserts,
                (unsigned long long)metrics.n_map_alarms);
    }
    tree.slack_scan(metrics.slack_real_keys, metrics.slack_with_right,
                    metrics.slack_with_left, metrics.slack_dummies);

    // ── 逐層節點數（E2b′ 儀器）與其自我檢查 ──────────────────────────────────
    //
    // 主要來源 = ExpBTree 的配置計數器（節點離葉高度是 B+ 樹不變量、無刪除
    // → 配置次數 == 期末存活數）。寫進 CSV 的是這一份。
    // 第二來源 = 以 oracle BFS 走訪整棵樹重新數一次（不注入、不動 metrics）。
    // 兩者不合、或總和對不上 n_pages_allocated、或最高層對不上 tree_height − 1，
    // 一律在 stderr 印 LEVELCHK 警告；掃描腳本可 grep 這個字串做批次品管。
    {
        uint64_t sum = 0;
        for (int l = 0; l < bfx::Metrics::MAX_TREE_LEVELS; ++l) {
            metrics.n_nodes_level[l] = tree.level_count(l);
            sum += metrics.n_nodes_level[l];
        }
        metrics.n_internal_total = sum - metrics.n_nodes_level[0];

        uint64_t walk[bfx::ExpBTree::MAX_LEVELS] = {0};
        uint32_t walk_max_level = 0;
        const bool walk_ok = tree.walk_level_counts(walk, walk_max_level);

        int top = 0;
        for (int l = bfx::Metrics::MAX_TREE_LEVELS - 1; l >= 0; --l)
            if (metrics.n_nodes_level[l]) { top = l; break; }

        bool agree = walk_ok;
        for (int l = 0; l < bfx::Metrics::MAX_TREE_LEVELS; ++l)
            if (walk[l] != metrics.n_nodes_level[l]) agree = false;

        const bool sum_ok    = (sum == metrics.n_pages_allocated);
        const bool height_ok = ((uint32_t)top + 1 == metrics.tree_height);
        const bool ovf_ok    = (tree.level_overflow() == 0);

        std::string lv;
        for (int l = 0; l < bfx::Metrics::MAX_TREE_LEVELS; ++l) {
            char b[32];
            std::snprintf(b, sizeof b, "%s%llu", l ? "/" : "",
                          (unsigned long long)metrics.n_nodes_level[l]);
            lv += b;
        }
        fprintf(stderr,
                "LEVELCHK %s levels=%s internal=%llu pages=%llu h=%u "
                "sum_ok=%d height_ok=%d overflow_ok=%d walk_ok=%d walk_agree=%d\n",
                (sum_ok && height_ok && ovf_ok && walk_ok && agree) ? "PASS" : "FAIL",
                lv.c_str(),
                (unsigned long long)metrics.n_internal_total,
                (unsigned long long)metrics.n_pages_allocated,
                metrics.tree_height,
                (int)sum_ok, (int)height_ok, (int)ovf_ok, (int)walk_ok, (int)agree);
        if (!agree || !walk_ok) {
            std::string wv;
            for (int l = 0; l < bfx::ExpBTree::MAX_LEVELS; ++l) {
                char b[32];
                std::snprintf(b, sizeof b, "%s%llu", l ? "/" : "",
                              (unsigned long long)walk[l]);
                wv += b;
            }
            fprintf(stderr, "LEVELCHK walk_levels=%s walk_max_level=%u\n",
                    wv.c_str(), walk_max_level);
        }
    }
    {
        // 兩個後端都透過 IRAM::get_stats() 取；ram 後端的 iram 就是 ram，
        // 因此行為與原本完全相同（r2 後端原本這些欄位恆為 0）。
        const RAMStats rs = iram->get_stats();
        metrics.ram_hits          = rs.n_hits          - ram_baseline.n_hits;
        metrics.ram_misses        = rs.n_misses        - ram_baseline.n_misses;
        metrics.ram_lru_evictions = rs.n_lru_evictions - ram_baseline.n_lru_evictions;
        metrics.ram_ttl_evictions = rs.n_ttl_evictions - ram_baseline.n_ttl_evictions;
    }

    fprintf(stderr, "RANGECHK oracle_nodes_violating=%llu\n",
            (unsigned long long)tree.oracle_range_violations());
    const bool csv_ok = metrics.append_csv(cfg);
    fprintf(stderr,
            "[%s] f1=%.4f recall=%.4f precision=%.4f wrong_total=%llu "
            "wrong_undetected=%llu final_errors=%llu recoveries=%llu would_crash=%llu\n",
            cfg.run_id.c_str(),
            metrics.page_read.f1(), metrics.page_read.recall(),
            metrics.page_read.precision(),
            (unsigned long long)metrics.n_wrong_total,
            (unsigned long long)metrics.n_wrong_undetected,
            (unsigned long long)metrics.n_final_integrity_errors,
            (unsigned long long)metrics.n_recoveries,
            (unsigned long long)metrics.n_would_crash);

    // ── 清理 ─────────────────────────────────────────────────────────────────
#ifdef HAVE_RAMULATOR2
    if (r2_fe)  r2_fe->finalize();
    if (r2_mem) r2_mem->finalize();
    delete r2ram;
#endif
    delete ram;
    delete ssd;

    return csv_ok ? 0 : 1;
}
