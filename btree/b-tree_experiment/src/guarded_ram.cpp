#include "guarded_ram.hpp"
#include "exp_btree.hpp"   // bfx::sanity_check（SANITY 偵測器）
#include <algorithm>
#include <cstring>
#include <stdexcept>
#include <string>

namespace bfx {

namespace {

// E7′：keys[] 內單一位元翻轉的歸因結果（bit < 0 = 不適用）
struct KeyFlipInfo {
    int  bit = -1;                  // 0..63，64 位元 key 的 little-endian 位序
    bool leaf = false;              // 該頁（依 oracle）是不是 leaf
    bool multi_touches_key = false; // 相異位元組 ≥ 2 且至少一個落在 keys[]
    int  slot = -1;                 // E13：被翻的 key 在 keys[] 中的索引（bit ≥ 0 時有效）
};

// 毀損歸因（Task 2）：把「讀回 image vs oracle」的相異位元組位置分區計數。
//
// 分界用的 ctrl_len 一律由 **oracle**（地面真相）算出——這裡的目的是描述
// 「這次毀損打在哪一區」，不是偵測，所以用真相邊界才有意義；也因此與
// 驗證路徑「用 entry 凍結值」的規則不衝突。
//
// 為速度先以 64 B 為單位 memcmp，只有不相符的區塊才逐位元組定位；
// 一旦分類已可確定（ssd_header，或 ctrl+payload 皆已命中）即提前收工。
//
// E7′ 追加（純觀測，同樣零決策影響）：回傳「這次毀損是不是恰好一個位元組相異、
// 且該位元組落在 keys[] 陣列」，若是則附上被翻的**位元位置**（0..63，
// 64 位元 key 的 little-endian 位序）。位元位置由 `got[j] ^ oracle[j]` 反推，
// 不需要注入端（new_RAM_core，對本層唯讀）回報任何東西。
KeyFlipInfo attribute_corruption(const std::vector<uint8_t>& got,
                          const std::vector<uint8_t>& oracle,
                          uint32_t page_size, Metrics* m) {
    const uint32_t cl  = ctrl_len_of(oracle, page_size);
    const uint32_t ll  = live_len_of(oracle, page_size);
    const size_t   n   = std::min(got.size(), oracle.size());
    const size_t   ctl_end  = std::min<size_t>(n, (size_t)16 + cl);
    const size_t   live_end = std::min<size_t>(n, (size_t)16 + ll);

    // keys[] 的範圍（leaf 與 internal 佈局相同：header 16 B 之後即 keys[]）
    size_t key_beg = 0, key_end = 0;
    bool   oracle_leaf = false;
    if (oracle.size() >= 32) {
        uint32_t n_keys = 0;
        std::memcpy(&n_keys, oracle.data() + 20, 4);
        oracle_leaf = (oracle[16] == 1);
        key_beg = 32;
        key_end = std::min<size_t>(n, (size_t)32 + (uint64_t)n_keys * 8);
        if (key_end < key_beg) key_end = key_beg;
    }

    // d_val = 落在 values[]（活 payload）；d_slack = 落在其後的未使用補零
    bool d_ssd = false, d_ctrl = false, d_val = false, d_slack = false;
    uint64_t ndiff = 0;          // 相異位元組總數（提前收工時只計到收工點）
    size_t   first_off = 0;      // 第一個相異位元組的位置
    uint8_t  first_xor = 0;      // 該位元組的 XOR 差值
    for (size_t i = 0; i < n; ) {
        const size_t chunk = std::min<size_t>(64, n - i);
        if (std::memcmp(got.data() + i, oracle.data() + i, chunk) != 0) {
            for (size_t j = i; j < i + chunk; ++j) {
                if (got[j] == oracle[j]) continue;
                if (ndiff == 0) { first_off = j; first_xor = (uint8_t)(got[j] ^ oracle[j]); }
                ++ndiff;
                if      (j < 16)        d_ssd   = true;
                else if (j < ctl_end)   d_ctrl  = true;
                else if (j < live_end)  d_val   = true;
                else                    d_slack = true;
            }
            // 四大類已可確定即收工。slack_only 只在 !d_ssd && !d_ctrl 時才可能，
            // 而該情形下這個提前收工條件不會成立，故不會漏判。
            //
            // 對 keys[] 直方圖的安全性：收工只發生在 d_ssd（相異位元組在 [0,16)，
            // 不在 keys[]）或 d_ctrl && payload（此時 ndiff ≥ 2，本來就不合格）。
            // 「恰一個相異位元組且落在 keys[]」永遠不會觸發收工 → ndiff 是全頁真值。
            if (d_ssd || (d_ctrl && (d_val || d_slack))) break;
        }
        i += chunk;
    }

    // keys[] 的位元位置分類
    KeyFlipInfo kf;
    kf.leaf = oracle_leaf;
    if (ndiff == 1 && first_off >= key_beg && first_off < key_end &&
        first_xor != 0 && (first_xor & (uint8_t)(first_xor - 1)) == 0) {
        int bit_in_byte = 0;
        while (((first_xor >> bit_in_byte) & 1u) == 0) ++bit_in_byte;
        kf.bit = (int)((first_off - 32) % 8) * 8 + bit_in_byte;
        kf.slot = (int)((first_off - 32) / 8);
    } else if (ndiff >= 2) {
        // 直方圖排除的多重毀損：只在至少一個相異位元組落在 keys[] 時才計
        bool touches_key = false;
        for (size_t j = key_beg; j < key_end && !touches_key; ++j)
            if (got[j] != oracle[j]) touches_key = true;
        kf.multi_touches_key = touches_key;
    }

    const bool d_pay = d_val || d_slack;

    // 四類互斥且窮盡（呼叫端保證 got != oracle，故至少一個旗標為真）
    if      (d_ssd)            ++m->n_corrupt_reads_ssd_header;
    else if (d_ctrl && d_pay)  ++m->n_corrupt_reads_mixed;
    else if (d_ctrl)           ++m->n_corrupt_reads_ctrl_only;
    else                       ++m->n_corrupt_reads_payload_only;

    // payload_only 的子集：相異位元組全在未使用 slack（語意上無害的毀損）
    if (!d_ssd && !d_ctrl && !d_val && d_slack) ++m->n_corrupt_reads_slack_only;

    return kf;
}

// bit flip 不會改變 image 長度；長度不符只可能是 v2 SSD 的區塊回收 bug
// （erase 不清 page_data_ + program append → 頁面倍長，見 exp_config.hpp
// ssd_blocks 註解）。此時所有指標都已不可信，唯一正確的處置是大聲失敗。
void require_page_size(const std::vector<uint8_t>& img, uint64_t page_id,
                       uint32_t page_size, const char* where) {
    if (img.size() != page_size)
        throw std::runtime_error(std::string(where) + ": page " +
            std::to_string(page_id) + " image is " + std::to_string(img.size()) +
            "B (expected " + std::to_string(page_size) +
            "B) — v2 SSD block-recycling corruption; increase --ssd_blocks");
}
} // namespace

bool leaf_slot_is_dummy(const std::vector<uint8_t>& leaf_image, int slot) {
    if (leaf_image.size() < 32 || slot < 0) return false;
    uint32_t nk = 0;
    std::memcpy(&nk, leaf_image.data() + 20, 4);
    if ((uint32_t)slot >= nk) return false;
    const size_t voff = 32 + (size_t)nk * 8 + (size_t)slot * 8;
    uint64_t v = 0;
    if (voff + 8 > leaf_image.size()) return false;
    std::memcpy(&v, leaf_image.data() + voff, 8);
    return v == GUARD_SENTINEL_VALUE;
}

GuardedRAM::GuardedRAM(IRAM* ram, SSD* ssd, ShadowStore* shadow,
                       Metrics* metrics, const ExpConfig* cfg)
    : ram_(ram), ssd_(ssd), shadow_(shadow), metrics_(metrics), cfg_(cfg) {}

uint64_t GuardedRAM::allocate(double t, double& latency_out) {
    uint64_t page_id = ram_->allocate(t);

    // oracle 初始 image = RAM::allocate 寫入 SSD 的內容：全零 + SSD header
    // （bytes 4..7 = page_size，其餘 header 欄位為零）
    std::vector<uint8_t> init(cfg_->page_size, 0);
    uint32_t ps = cfg_->page_size;
    std::memcpy(init.data() + 4, &ps, 4);
    oracle_[page_id] = std::move(init);

    next_hint_ = page_id + 1;
    latency_out += cfg_->t_ssd_s + cfg_->t_mem_s;
    return page_id;
}

GuardedReadResult GuardedRAM::read(uint64_t page_id, double t, uint8_t level,
                                   const ChildBounds* bounds) {
    GuardedReadResult out;

    // 1. DRAM 讀取
    RAMReadResult r = ram_->read(page_id, t);
    require_page_size(r.data, page_id, cfg_->page_size, "GuardedRAM::read");
    out.latency_s = r.latency;
    // r2 後端（RamulatorRAM::read）在 DRAM miss 時會從 SSD 重載頁面，但回傳的延遲只含 DDR4 讀取時間；
    // ram 後端（RAM::read）在 miss 時另加 t_ssd。為讓兩後端的延遲模型一致，r2 的 miss 在此補上 t_ssd。
    // 只有 DRAM 容量小於樹時（E5）才會發生 miss；全常駐的實驗不受影響。
    if (cfg_->backend == "r2" && !r.hit) out.latency_s += cfg_->t_ssd_s;

    // 2. 地面真相（只評分，不進偵測決策）
    const std::vector<uint8_t>& orc = oracle_.at(page_id);
    out.truth_corrupt = (r.data != orc);

    // 2b. 毀損歸因（control-plane vs payload）——同樣只評分，零決策影響
    KeyFlipInfo kf;
    if (out.truth_corrupt)
        kf = attribute_corruption(r.data, orc, cfg_->page_size, metrics_);

    // 3a. 可靠記憶體驗證
    bool predicted = false;
    bool verified  = false;   // 本次是否真的執行了驗證（供 ReadPolicy 回呼）
    ShadowEntry* entry = shadow_->lookup(page_id, tick_);
    const Scheme s = cfg_->scheme;
    // policy_ 可要求跳過驗證（ttl_theta_experiment 的「cold page 免驗證」實驗臂）
    const bool skip = policy_ && policy_->skip_verify(page_id);
    if (entry && !skip &&
        (s == Scheme::HDR_CRC || s == Scheme::HDR_MIRROR ||
         s == Scheme::CTRL_CRC || s == Scheme::FULL_CRC || s == Scheme::HYBRID)) {
        bool due = (cfg_->verify_mode == VerifyMode::EVERY_READ) ||
                   (t - entry->last_verified_s > cfg_->theta_s);
        if (due) {
            verified = true;
            // 明列每個 scheme（不留 default 落空分支）：漏掉一個 case 會讓
            // predicted 靜默維持 false ＝ 該 scheme 變成「永不報警」的假 NONE。
            switch (s) {
                case Scheme::HDR_CRC:
                    out.latency_s += cfg_->t_reliable_s + 16.0 * cfg_->t_crc_per_byte_s;
                    predicted = (ShadowStore::crc_of(s, r.data, 0) != entry->crc);
                    break;
                case Scheme::CTRL_CRC:
                case Scheme::HYBRID:   // E10：有 entry ＝ internal 頁 → 完全同 CTRL_CRC
                    // ⚠️ 用 entry 凍結的 ctrl_len，**不**從 r.data 重算：
                    // 若 flip 打中 n_keys，重算會讓驗證器檢查錯誤範圍而漏掉它。
                    out.latency_s += cfg_->t_reliable_s
                                   + (16.0 + (double)entry->ctrl_len) * cfg_->t_crc_per_byte_s;
                    predicted = (ShadowStore::crc_of(s, r.data, entry->ctrl_len)
                                 != entry->crc);
                    break;
                case Scheme::FULL_CRC:
                    out.latency_s += cfg_->t_reliable_s + 4096.0 * cfg_->t_crc_per_byte_s;
                    predicted = (ShadowStore::crc_of(s, r.data, 0) != entry->crc);
                    break;
                case Scheme::HDR_MIRROR:   // 直接位元組比對，免雜湊
                    out.latency_s += cfg_->t_reliable_s;
                    predicted = (std::memcmp(r.data.data() + 16, entry->hdr, 16) != 0);
                    break;
                case Scheme::NONE:
                case Scheme::SANITY:
                case Scheme::INPAGE_CTRL:  // E16：無 entry，走下方 3a′
                case Scheme::INPAGE_FULL:
                    break;                 // 外層條件已排除，列出以窮盡 enum
            }
            entry->last_verified_s = t;
        }
    }

    // 3a′. E16：頁內 CRC（無 shadow entry、無可靠記憶體存取）。
    //      涵蓋範圍由讀回的 image 重算（INPAGE_CTRL）或固定 [0,page_size-4)（INPAGE_FULL）；
    //      成本 = 涵蓋位元組數 × t_crc_per_byte（同 CTRL_CRC/FULL_CRC，但不含 t_reliable）。
    //      每次讀都驗（EVERY_READ；PERIODIC 無 last_verified 狀態可用，driver 拒絕此組合）。
    if (is_inpage(s) && !skip) {
        verified = true;
        const uint32_t end = inpage_cover_end(s, r.data, cfg_->page_size);
        out.latency_s += (double)end * cfg_->t_crc_per_byte_s;
        if (inpage_mismatch(s, r.data, cfg_->page_size)) predicted = true;
    }

    // 3b. 免費結構檢查
    //     HYBRID（E10）：沒有 entry ＝ leaf 頁 → 改跑免費結構檢查
    if (s == Scheme::SANITY || cfg_->sanity_always || (s == Scheme::HYBRID && !entry)) {
        out.latency_s += cfg_->t_sanity_s;
        bool fatal = false;
        SanityExt ext;
        ext.align_log2 = cfg_->sanity_align_log2;
        ext.slack      = (cfg_->slack_guard != SlackGuard::NONE);
        if (!sanity_check(r.data, page_id, cfg_->order, cfg_->page_size,
                          next_hint_, fatal, &ext))
            predicted = true;
        // 3c. E17：parent–child 範圍檢查（結構檢查通過才做 → 佈局可安全讀取）。
        //     成本：首尾兩次比較，計 0（相對 t_sanity_s = 50 ns 可忽略）。
        else if (bounds && cfg_->sanity_range && !range_check(r.data, *bounds, ext.slack)) {
            predicted = true;
            out.range_alarm = true;
            metrics_->n_range_alarms++;
            if (out.truth_corrupt) metrics_->n_range_child_bad++;
        }
    }

    // 4. 分類記帳
    metrics_->page_read.add(out.truth_corrupt, predicted);
    // 4a′. E7′：keys[] 的翻轉位元位置直方圖（predicted 已定案才記）
    if (kf.bit >= 0) {
        ++metrics_->keybit_seen[kf.bit];
        ++metrics_->n_keyflip_single;
        if (kf.leaf) ++metrics_->n_keyflip_single_leaf;
        if (predicted) {
            ++metrics_->keybit_tp[kf.bit];
            ++metrics_->n_keyflip_single_tp;
            if (kf.leaf) ++metrics_->n_keyflip_single_leaf_tp;
        }
        // E13：leaf 的單一 key 翻轉，依 oracle 的 value slot 分成真 key / dummy key
        if (kf.leaf && kf.slot >= 0) {
            if (leaf_slot_is_dummy(orc, kf.slot)) {
                ++metrics_->n_keyflip_dummy;
                if (predicted) ++metrics_->n_keyflip_dummy_tp;
            } else {
                ++metrics_->n_keyflip_real;
                ++metrics_->kbr_seen[kf.bit];
                if (predicted) { ++metrics_->n_keyflip_real_tp; ++metrics_->kbr_tp[kf.bit]; }
            }
        }
    } else if (kf.multi_touches_key) {
        ++metrics_->n_keyflip_multi;
        if (predicted) ++metrics_->n_keyflip_multi_tp;
    }
    metrics_->n_guarded_reads++;
    if (entry) metrics_->n_protected_reads++;
    out.detected = predicted;

    // 4b. 實驗層回呼（分冷熱統計等）；policy_ 為 nullptr 時完全不執行
    if (policy_) policy_->on_read(page_id, out.truth_corrupt, predicted, verified, t);

    // 5. 報警 → 從 SSD 取乾淨副本復原
    if (predicted) {
        std::vector<uint8_t> clean;
        ssd_status st = ssd_->read(static_cast<uint32_t>(page_id), clean);
        out.latency_s += cfg_->t_ssd_s;
        if (st == ssd_status::success) {
            require_page_size(clean, page_id, cfg_->page_size, "GuardedRAM recovery");
            ram_->write(page_id, clean, t);   // 同內容 write-through，無害
            out.latency_s += cfg_->t_mem_s;
            shadow_->protect(page_id, clean, level, tick_);
            metrics_->n_recoveries++;
            out.recovered = true;
            out.data = std::move(clean);
            return out;
        }
        // 不應發生：SSD 也讀不到 → 無法復原，視同當機事件，交回毀損內容
        metrics_->n_would_crash++;
    }

    // 6. 未報警（或無法復原）→ 原樣交回
    out.returned_corrupt = out.truth_corrupt;
    out.data = std::move(r.data);
    return out;
}

void GuardedRAM::recover_from_ssd(uint64_t page_id, double t, uint8_t level,
                                  double& latency_out) {
    std::vector<uint8_t> clean;
    ssd_status st = ssd_->read(static_cast<uint32_t>(page_id), clean);
    latency_out += cfg_->t_ssd_s;
    if (st != ssd_status::success) { metrics_->n_would_crash++; return; }
    require_page_size(clean, page_id, cfg_->page_size, "GuardedRAM::recover_from_ssd");
    ram_->write(page_id, clean, t);
    latency_out += cfg_->t_mem_s;
    shadow_->protect(page_id, clean, level, tick_);
    metrics_->n_recoveries++;
    metrics_->n_range_anc_recoveries++;
}

double GuardedRAM::write(uint64_t page_id, const std::vector<uint8_t>& image,
                         double t, uint8_t level, bool derived_from_fn) {
    oracle_[page_id] = image;
    if (level_of_.size() <= page_id) level_of_.resize(page_id + 1, -1);
    level_of_[page_id] = (int8_t)level;   // E11：page → level（B+ 樹中為不變量）
    shadow_->protect(page_id, image, level, tick_);
    ram_->write(page_id, image, t);

    double lat = cfg_->t_mem_s + cfg_->t_ssd_s;   // write-through
    switch (cfg_->scheme) {                       // 校驗寫入可靠記憶體的成本
        case Scheme::HDR_CRC:    lat += cfg_->t_reliable_s + 16.0   * cfg_->t_crc_per_byte_s; break;
        case Scheme::FULL_CRC:   lat += cfg_->t_reliable_s + 4096.0 * cfg_->t_crc_per_byte_s; break;
        case Scheme::HDR_MIRROR: lat += cfg_->t_reliable_s; break;
        // CTRL_CRC：成本隨這個節點的實際控制平面長度變動（image 為剛序列化的
        // 可信內容，可安全現算——與 protect() 內凍結進 entry 的是同一個值）。
        case Scheme::CTRL_CRC:
            lat += cfg_->t_reliable_s
                 + (16.0 + (double)ctrl_len_of(image, cfg_->page_size)) * cfg_->t_crc_per_byte_s;
            break;
        case Scheme::HYBRID:                       // E10：只有 internal 寫入可靠記憶體
            if (level >= 1)
                lat += cfg_->t_reliable_s
                     + (16.0 + (double)ctrl_len_of(image, cfg_->page_size)) * cfg_->t_crc_per_byte_s;
            break;
        // E16：頁內 CRC——只算 CRC 計算成本，無可靠記憶體存取（image 已 stamp 過）
        case Scheme::INPAGE_CTRL:
        case Scheme::INPAGE_FULL:
            lat += (double)inpage_cover_end(cfg_->scheme, image, cfg_->page_size)
                 * cfg_->t_crc_per_byte_s;
            break;
        case Scheme::NONE:
        case Scheme::SANITY:     break;            // 無可靠記憶體
    }
    if (derived_from_fn) metrics_->n_poisoned_writes++;
    return lat;
}

std::vector<uint8_t> GuardedRAM::crash_rescue(uint64_t page_id, double t,
                                              uint8_t level, double& latency_out) {
    metrics_->n_would_crash++;

    // r2 後端無 SSD：直接讓 ram->read（ECC 修正後）當作 clean copy
    if (!ssd_) {
        RAMReadResult r = ram_->read(page_id, t);
        latency_out += r.latency;
        shadow_->protect(page_id, r.data, level, tick_);
        return std::move(r.data);
    }

    std::vector<uint8_t> clean;
    ssd_status st = ssd_->read(static_cast<uint32_t>(page_id), clean);
    latency_out += cfg_->t_ssd_s;
    if (st != ssd_status::success) {
        // 不應發生：連 SSD 都讀不到 → 交回 DRAM 現況
        RAMReadResult r = ram_->read(page_id, t);
        latency_out += r.latency;
        return std::move(r.data);
    }

    require_page_size(clean, page_id, cfg_->page_size, "GuardedRAM::crash_rescue");
    ram_->write(page_id, clean, t);
    latency_out += cfg_->t_mem_s;
    shadow_->protect(page_id, clean, level, tick_);   // 收留與否交由 policy
    return clean;
}

std::vector<uint8_t> GuardedRAM::reload_clean(uint64_t page_id, double t,
                                              uint8_t level, double& latency_out) {   // E21
    std::vector<uint8_t> clean;
    if (ssd_ && ssd_->read(static_cast<uint32_t>(page_id), clean) == ssd_status::success) {
        latency_out += cfg_->t_ssd_s;
        require_page_size(clean, page_id, cfg_->page_size, "GuardedRAM::reload_clean");
        ram_->write(page_id, clean, t);
        latency_out += cfg_->t_mem_s;
        shadow_->protect(page_id, clean, level, tick_);
        metrics_->n_recoveries++;
        return clean;
    }
    RAMReadResult r = ram_->read(page_id, t);   // r2 後端（無 SSD）或 SSD 讀失敗
    latency_out += r.latency;
    return std::move(r.data);
}

std::vector<uint64_t> GuardedRAM::resident_pages() const {
    std::vector<uint64_t> pages;
    for (uint64_t id = 0; id < next_hint_; ++id)
        if (ram_->is_in_ram(id)) pages.push_back(id);
    return pages;
}

// E11：只回傳指定層級的常駐頁。ALL 直接轉呼 resident_pages()（逐位元組同舊行為）。
// 尚未被 write() 過的頁（level 未知 = -1）不屬於任何一層。
std::vector<uint64_t> GuardedRAM::resident_pages_filtered(InjectLevel f) const {
    if (f == InjectLevel::ALL) return resident_pages();
    std::vector<uint64_t> pages;
    for (uint64_t id = 0; id < next_hint_; ++id) {
        const int lv = (id < level_of_.size()) ? level_of_[id] : -1;
        if (lv < 0) continue;
        const bool want = (f == InjectLevel::INTERNAL) ? (lv >= 1) : (lv == 0);
        if (want && ram_->is_in_ram(id)) pages.push_back(id);
    }
    return pages;
}

const std::vector<uint8_t>& GuardedRAM::oracle(uint64_t page_id) const {
    return oracle_.at(page_id);
}

void GuardedRAM::note_op_boundary() { ++tick_; }

} // namespace bfx
