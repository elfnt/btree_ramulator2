// shadow_store.cpp — 可靠記憶體模型：容量預算 + Policy 決定去留
#include "shadow_store.hpp"
#include "metrics.hpp"
#include "fast_crc.hpp"
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>

namespace bfx {

uint32_t ctrl_len_of(const std::vector<uint8_t>& trusted_image, uint32_t page_size) {
    // 頁面連 NodeHeader 都放不下：退化成「只蓋得到的部分」。可信 image 不該發生。
    if (trusted_image.size() < 32 || page_size < 32) return 16;

    const uint8_t* p = trusted_image.data();
    const uint8_t  node_type = p[16];              // 0 = internal, 1 = leaf
    uint32_t n_keys;
    std::memcpy(&n_keys, p + 20, 4);

    // 上界夾擠：可信來源理應永遠 n_keys ≤ order，但若上游有 bug 也絕不越界。
    const uint32_t max_span = std::min<uint32_t>(page_size, (uint32_t)trusted_image.size()) - 16;
    const uint64_t arrays   = (uint64_t)n_keys * 8
                            + (node_type == 1 ? 0ull : ((uint64_t)n_keys + 1) * 8);
    const uint64_t len      = 16ull + arrays;
    return (uint32_t)std::min<uint64_t>(len, max_span);
}

uint32_t live_len_of(const std::vector<uint8_t>& trusted_image, uint32_t page_size) {
    if (trusted_image.size() < 32 || page_size < 32) return 16;

    const uint8_t* p = trusted_image.data();
    const uint8_t  node_type = p[16];
    uint32_t n_keys;
    std::memcpy(&n_keys, p + 20, 4);

    const uint32_t max_span = std::min<uint32_t>(page_size, (uint32_t)trusted_image.size()) - 16;
    // internal 的 children[] 已含在 ctrl_len 內；leaf 才要再加 values[]
    const uint64_t len = (uint64_t)ctrl_len_of(trusted_image, page_size)
                       + (node_type == 1 ? (uint64_t)n_keys * 8 : 0ull);
    return (uint32_t)std::min<uint64_t>(len, max_span);
}

uint32_t inpage_cover_end(Scheme s, const std::vector<uint8_t>& image, uint32_t page_size) {
    const uint32_t lim = std::min<uint32_t>(page_size, (uint32_t)image.size());
    const uint32_t crc_off = lim - 4;
    if (s == Scheme::INPAGE_FULL) return crc_off;
    if (s != Scheme::INPAGE_CTRL) {
        std::fprintf(stderr, "FATAL: inpage_cover_end called for non-INPAGE scheme\n");
        std::abort();
    }
    const uint64_t end = 16ull + ctrl_len_of(image, page_size);
    return (uint32_t)std::min<uint64_t>(end, crc_off);
}

uint32_t inpage_crc(Scheme s, const std::vector<uint8_t>& image, uint32_t page_size) {
    const uint32_t end = inpage_cover_end(s, image, page_size);
    return fast_crc32(std::vector<uint8_t>(image.begin(), image.begin() + end));
}

uint32_t inpage_stored_crc(const std::vector<uint8_t>& image, uint32_t page_size) {
    const uint32_t lim = std::min<uint32_t>(page_size, (uint32_t)image.size());
    uint32_t c;
    std::memcpy(&c, image.data() + lim - 4, 4);
    return c;
}

void inpage_stamp(Scheme s, std::vector<uint8_t>& image, uint32_t page_size) {
    const uint32_t c = inpage_crc(s, image, page_size);
    const uint32_t lim = std::min<uint32_t>(page_size, (uint32_t)image.size());
    std::memcpy(image.data() + lim - 4, &c, 4);
}

bool inpage_mismatch(Scheme s, const std::vector<uint8_t>& image, uint32_t page_size) {
    return inpage_crc(s, image, page_size) != inpage_stored_crc(image, page_size);
}

ShadowStore::ShadowStore(const ExpConfig& cfg, Metrics* metrics, uint32_t rng_seed)
    : cfg_(cfg), metrics_(metrics), rng_(rng_seed) {
    const uint32_t eb = scheme_entry_bytes(cfg.scheme);
    capacity_entries_ = (eb == 0) ? 0
                      : (cfg.budget_bytes == UINT64_MAX ? UINT64_MAX
                                                        : cfg.budget_bytes / eb);
}

uint32_t ShadowStore::crc_of(Scheme s, const std::vector<uint8_t>& image,
                             uint32_t ctrl_len) {
    switch (s) {
        case Scheme::HDR_CRC:
            return fast_crc32(std::vector<uint8_t>(image.begin() + 16, image.begin() + 32));
        case Scheme::CTRL_CRC:
        case Scheme::HYBRID: {   // HYBRID 的 internal entry 與 CTRL_CRC 完全同一個 CRC
            // 涵蓋 image[0, 16+ctrl_len)——**含**前 16 B SSD header。
            // ctrl_len 由呼叫端提供：protect() 用可信 image 現算，驗證用 entry 存下的值。
            if (ctrl_len < 16) {
                std::fprintf(stderr,
                    "FATAL: crc_of(CTRL_CRC) got ctrl_len=%u (< 16). "
                    "呼叫端必須傳入 protect() 時凍結的 ctrl_len。\n", ctrl_len);
                std::abort();
            }
            const size_t end = std::min<size_t>(image.size(), (size_t)16 + ctrl_len);
            return fast_crc32(std::vector<uint8_t>(image.begin(), image.begin() + end));
        }
        case Scheme::FULL_CRC:
            return fast_crc32(image);
        case Scheme::NONE:
        case Scheme::SANITY:
        case Scheme::HDR_MIRROR:
        case Scheme::INPAGE_CTRL:   // E16：CRC 在頁內（inpage_crc），不經 shadow
        case Scheme::INPAGE_FULL:
            return 0;   // HDR_MIRROR 直接比對；NONE/SANITY 無校驗
    }
    return 0;
}

bool ShadowStore::protect(uint64_t page_id, const std::vector<uint8_t>& image,
                          uint8_t level, uint64_t tick) {
    if (cfg_.scheme == Scheme::NONE || cfg_.scheme == Scheme::SANITY) return false;
    if (is_inpage(cfg_.scheme)) return false;   // E16：無 shadow entry（也不計 n_shadow_rejected）
    // HYBRID（E10）：leaf 不佔可靠記憶體（交給免費 SANITY）。level 是 B+ 樹不變量，
    // 理論上不會有舊 entry；仍保險地清掉，確保 leaf 永遠走 sanity 路徑。
    if (cfg_.scheme == Scheme::HYBRID && level == 0) { map_.erase(page_id); return false; }

    auto it = map_.find(page_id);
    if (it == map_.end()) {
        if (map_.size() >= capacity_entries_) {
            const bool freed = evict_one(level);
            if (metrics_) ++metrics_->n_shadow_rejected;   // 被拒或逐出，每次一計
            if (!freed) return false;
        }
        ShadowEntry e;
        e.hotness = 1;
        it = map_.emplace(page_id, e).first;
    }
    ShadowEntry& e = it->second;
    // CTRL_CRC：ctrl_len 在此（用剛寫入的可信 image）一次算定並凍結進 entry。
    // 之後每次驗證都用這個值，讀回的 image 就算 n_keys 被翻也不影響檢查範圍。
    e.ctrl_len = (cfg_.scheme == Scheme::CTRL_CRC || cfg_.scheme == Scheme::HYBRID)
                     ? (uint16_t)ctrl_len_of(image, cfg_.page_size)
                     : 0;
    e.crc = crc_of(cfg_.scheme, image, e.ctrl_len);
    if (cfg_.scheme == Scheme::HDR_MIRROR)
        std::memcpy(e.hdr, image.data() + 16, 16);
    e.level = level;
    e.last_use_tick = tick;

    if (metrics_) {
        const uint64_t used = bytes_used();
        if (used > metrics_->shadow_bytes_used_max)
            metrics_->shadow_bytes_used_max = used;
    }
    return true;
}

ShadowEntry* ShadowStore::lookup(uint64_t page_id, uint64_t tick) {
    auto it = map_.find(page_id);
    if (it == map_.end()) return nullptr;
    ++it->second.hotness;
    it->second.last_use_tick = tick;
    return &it->second;
}

void ShadowStore::erase(uint64_t page_id) {
    map_.erase(page_id);
}

uint64_t ShadowStore::bytes_used() const {
    return (uint64_t)map_.size() * entry_bytes();
}

uint32_t ShadowStore::entry_bytes() const {
    return scheme_entry_bytes(cfg_.scheme);
}

bool ShadowStore::is_protected(uint64_t page_id) const {
    return map_.count(page_id) != 0;
}

size_t ShadowStore::size() const {
    return map_.size();
}

bool ShadowStore::evict_one(uint8_t incoming_level) {
    if (map_.empty()) return false;
    auto victim = map_.end();
    switch (cfg_.policy) {
        case Policy::BY_LEVEL:
            for (auto it = map_.begin(); it != map_.end(); ++it) {
                if (victim == map_.end()
                    || it->second.level < victim->second.level
                    || (it->second.level == victim->second.level
                        && it->second.last_use_tick < victim->second.last_use_tick))
                    victim = it;
            }
            if (incoming_level <= victim->second.level) return false;   // 層級不夠高，拒收
            break;
        case Policy::BY_HOTNESS:
            for (auto it = map_.begin(); it != map_.end(); ++it) {
                if (victim == map_.end() || it->second.hotness < victim->second.hotness)
                    victim = it;
            }
            break;
        case Policy::LRU:
            for (auto it = map_.begin(); it != map_.end(); ++it) {
                if (victim == map_.end()
                    || it->second.last_use_tick < victim->second.last_use_tick)
                    victim = it;
            }
            break;
        case Policy::RANDOM: {
            std::uniform_int_distribution<size_t> pick(0, map_.size() - 1);
            victim = std::next(map_.begin(), (std::ptrdiff_t)pick(rng_));
            break;
        }
    }
    map_.erase(victim);
    return true;
}

} // namespace bfx
