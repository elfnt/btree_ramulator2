#include "new_ram.hpp"
#include <algorithm>
#include <cmath>       // std::isinf（TTL 政策）
#include <cstring>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>

// ── SECDED Hamming ECC（64-bit word，8-bit parity）─────────────────────────
//
// 72-bit codeword 佈局：
//   Parity 位置（2 的冪次）：1, 2, 4, 8, 16, 32, 64
//   Data   位置（其餘）    ：3,5,6,7,9..15,17..31,33..63,65..71
//
// parity_byte 格式：
//   bits 0-6 = 7-bit Hamming syndrome（syndrome_h）
//   bit  7   = overall parity（syndrome_op，用於區分單雙 bit 錯誤）
//
// 讀取時：
//   syndrome_h == 0, syndrome_op == 0  → 無錯誤
//   syndrome_h == 0, syndrome_op == 1  → overall parity bit 本身出錯，data 正確
//   syndrome_h != 0, syndrome_op == 1  → 奇數 bit 錯誤，ECC 修正（可能為 miscorrection）
//   syndrome_h != 0, syndrome_op == 0  → 偶數 bit 錯誤（2/4/6+），UE（偵測不修正）

// 64 個 data bit 在 72-bit codeword 中的位置（1-indexed，跳過 1/2/4/8/16/32/64）
static constexpr int HAMMING_POS[64] = {
     3,  5,  6,  7,  9, 10, 11, 12, 13, 14, 15,
    17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
    33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47,
    48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63,
    65, 66, 67, 68, 69, 70, 71
};

// 7-bit Hamming syndrome：XOR of HAMMING_POS[d] for all set data bits
static uint8_t hamming7(uint64_t word) {
    uint8_t s = 0;
    for (int d = 0; d < 64; ++d)
        if ((word >> d) & 1ULL)
            s ^= static_cast<uint8_t>(HAMMING_POS[d] & 0x7F);
    return s;
}

// 8-bit ECC parity byte for a 64-bit word
//   bits 0-6 = hamming7(word)
//   bit  7   = popcount(word) & 1  XOR  popcount(hamming7) & 1
static uint8_t ecc_compute(uint64_t word) {
    uint8_t h  = hamming7(word);
    uint8_t op = static_cast<uint8_t>((__builtin_popcountll(word) & 1)
                                     ^ (__builtin_popcount(h) & 1));
    return static_cast<uint8_t>(h | (op << 7));
}

// ECC 檢查結果
enum class EccStatus { OK, CORRECTED, UNCORRECTABLE, MISCORRECTED };
struct EccWordResult { EccStatus status; uint64_t word; };

// 對單一 64-bit word 套用 SECDED，回傳狀態與（可能已修正的）word
static EccWordResult ecc_check(uint64_t word, uint8_t stored_parity) {
    uint8_t h          = hamming7(word);
    uint8_t stored_h   = static_cast<uint8_t>(stored_parity & 0x7F);
    uint8_t syndrome_h = static_cast<uint8_t>(h ^ stored_h);

    // overall parity 必須用「實際存在記憶體裡的」parity bits（stored_h），
    // 不能用從已損毀資料重算出來的 h。
    //
    // 真實 ECC DIMM 的 parity 晶片與資料晶片是分開的：資料位元翻轉時
    // parity bits 並不會跟著變。因此 receiver 要檢查的是
    //   parity(收到的 data  +  存著的 parity bits)  vs  存著的 overall parity。
    //
    // 舊版用重算的 h 代入，會使 syndrome_op = 1 ^ (popcount(HAMMING_POS[d]) & 1)。
    // 對 HAMMING_POS 為奇 popcount 的資料位元（7, 11, 13, 14, 19, ...），
    // 單一位元翻轉會算出 syndrome_op = 0 而被誤判為 UNCORRECTABLE，
    // 明明是 SECDED 該修好的 1-bit error。
    //
    // 改用 stored_h 後：syndrome_op ≡ (翻轉的資料位元數) mod 2，
    //   1 bit → 1（修正）、2 bit → 0（UE）、3 bit → 1（miscorrection），皆正確。
    uint8_t op         = static_cast<uint8_t>((__builtin_popcountll(word) & 1)
                                              ^ (__builtin_popcount(stored_h) & 1));
    uint8_t syndrome_op = static_cast<uint8_t>(op ^ ((stored_parity >> 7) & 1));

    if (syndrome_h == 0) {
        // syndrome_op == 0 → 無錯誤；syndrome_op == 1 → overall parity bit 本身出錯（data 正確）
        return {EccStatus::OK, word};
    }
    if (syndrome_op == 0) {
        // 偶數 bit 錯誤（2/4/6+）：偵測到，不修正
        return {EccStatus::UNCORRECTABLE, word};
    }
    // syndrome_op == 1, syndrome_h != 0：奇數 bit 錯誤，查找對應 data bit
    int pos = static_cast<int>(syndrome_h);
    for (int d = 0; d < 64; ++d) {
        if (HAMMING_POS[d] == pos) {
            // 修正此 data bit（1-bit error → CORRECTED；3-bit error → MISCORRECTED，無法區分）
            uint64_t corrected = word ^ (1ULL << d);
            return {EccStatus::CORRECTED, corrected};
        }
    }
    // syndrome_h 指向 parity bit 位置或超出範圍：data 不動，標記為 MISCORRECTED
    return {EccStatus::MISCORRECTED, word};
}

// ── Constructor ───────────────────────────────────────────────────────────────

RAM::RAM(RAMConfig config, SSD* ssd)
    : config_(config), ssd_(ssd), rng_(config.seed)
{
    if (config_.rows_per_bank == 0)
        throw std::invalid_argument("rows_per_bank must be > 0");
    if (!ssd_)
        throw std::invalid_argument("SSD pointer must not be null");

    // 初始化 8 個 bank，每個 bank 有 rows_per_bank 個空 slot
    banks_.assign(DRAM_NUM_BANKS,
                  std::vector<RAMSlot>(config_.rows_per_bank));

    // 所有物理格一開始都是空閒的
    for (uint32_t b = 0; b < DRAM_NUM_BANKS; ++b)
        for (uint32_t r = 0; r < config_.rows_per_bank; ++r)
            free_slots_.push({b, r});
}

// ── 地址轉換 ──────────────────────────────────────────────────────────────────

// 查動態映射表；page 不在 RAM 時丟例外
DRAMAddress RAM::to_phys(uint64_t page_id) const {
    auto it = page_to_slot_.find(page_id);
    if (it == page_to_slot_.end())
        throw std::logic_error(
            "to_phys: page_id " + std::to_string(page_id) + " is not currently in RAM");
    return it->second;
}

// 從物理格反查 page_id（透過 owner_page_id 欄位）
uint64_t RAM::to_page_id(DRAMAddress addr) const {
    return banks_[addr.bank][addr.row].owner_page_id;
}

// 檢查 page_id 是否已分配（不是 in-RAM 的檢查，而是「有沒有呼叫過 allocate」）
void RAM::validate_page_id(uint64_t page_id) const {
    if (page_id >= next_page_id_)
        throw std::out_of_range(
            "page_id " + std::to_string(page_id) + " has not been allocated");
}

// slot() 需要 page 在 RAM 內（否則丟例外）
RAMSlot& RAM::slot(uint64_t page_id) {
    auto it = page_to_slot_.find(page_id);
    if (it == page_to_slot_.end())
        throw std::logic_error(
            "slot(): page_id " + std::to_string(page_id) + " is not in RAM");
    auto [b, r] = it->second;
    return banks_[b][r];
}

const RAMSlot& RAM::slot(uint64_t page_id) const {
    auto it = page_to_slot_.find(page_id);
    if (it == page_to_slot_.end())
        throw std::logic_error(
            "slot(): page_id " + std::to_string(page_id) + " is not in RAM");
    auto [b, r] = it->second;
    return banks_[b][r];
}

// ── SSD header ────────────────────────────────────────────────────────────────
// h2v() 的序列化順序：CRC32(0-3)、page_size_bytes(4-7)、version(8-11)、byte_order(12-15)

void RAM::fill_ssd_header(std::vector<uint8_t>& image) const {
    uint32_t zero      = 0;
    uint32_t page_size = DRAM_PAGE_SIZE;
    std::memcpy(image.data() + 0,  &zero,      4);
    std::memcpy(image.data() + 4,  &page_size, 4);
    std::memcpy(image.data() + 8,  &zero,      4);
    std::memcpy(image.data() + 12, &zero,      4);
}

// ── 查詢 ─────────────────────────────────────────────────────────────────────

bool RAM::is_in_ram(uint64_t page_id) const {
    return page_to_slot_.count(page_id) > 0;
}

uint32_t RAM::occupied() const {
    return static_cast<uint32_t>(page_to_slot_.size());
}

// ── TTL 懶惰逐出 ──────────────────────────────────────────────────────────────

bool RAM::check_ttl(uint64_t page_id, double t) {
    auto it = page_to_slot_.find(page_id);
    if (it == page_to_slot_.end()) return false;

    auto [b, r] = it->second;
    auto& s = banks_[b][r];
    if (!s.is_cold) return false;

    // 到期判定基準：
    //   residency（ttl_theta_experiment）：t − load_time —— 不論讀取頻率
    //   idle      （舊行為，預設）        ：t − last_access
    const double age = config_.ttl_residency ? (t - s.load_time)
                                             : (t - s.last_access);
    if (age <= s.ttl) return false;

    // 逐出：歸還物理格
    s.valid         = false;
    s.data.clear();
    s.owner_page_id = UINT64_MAX;
    free_slots_.push({b, r});
    page_to_slot_.erase(it);
    stats_.n_ttl_evictions++;
    return true;
}

// ── LRU 逐出 ─────────────────────────────────────────────────────────────────

void RAM::do_evict_lru(double /*t*/) {
    uint32_t lru_bank = 0, lru_row = 0;
    double   oldest   = std::numeric_limits<double>::max();
    bool     found    = false;

    for (uint32_t b = 0; b < DRAM_NUM_BANKS; ++b) {
        for (uint32_t r = 0; r < config_.rows_per_bank; ++r) {
            auto& s = banks_[b][r];
            if (s.valid && s.last_access < oldest) {
                oldest   = s.last_access;
                lru_bank = b;
                lru_row  = r;
                found    = true;
            }
        }
    }
    if (!found) return;

    auto& s = banks_[lru_bank][lru_row];
    page_to_slot_.erase(s.owner_page_id);  // 從映射表移除
    s.valid         = false;
    s.data.clear();
    s.owner_page_id = UINT64_MAX;
    free_slots_.push({lru_bank, lru_row}); // 歸還物理格
    stats_.n_lru_evictions++;
}

// ── SSD 載入 ─────────────────────────────────────────────────────────────────

void RAM::do_load(uint64_t page_id, double t) {
    // 呼叫方需確保 free_slots_ 非空
    DRAMAddress addr = free_slots_.front();
    free_slots_.pop();

    auto& s = banks_[addr.bank][addr.row];

    ssd_status st = ssd_->read(static_cast<uint32_t>(page_id), s.data);
    if (st != ssd_status::success) {
        free_slots_.push(addr);  // 讀取失敗，歸還格子
        throw std::runtime_error(
            "RAM::do_load: SSD read failed for page_id " +
            std::to_string(page_id));
    }

    s.valid         = true;
    s.owner_page_id = page_id;
    s.last_access   = t;
    s.last_check    = t;
    s.last_verified = t;
    s.load_time     = t;                                  // 曝露窗 T_reload 歸零
    s.is_cold       = false;
    s.ttl           = std::numeric_limits<double>::infinity();

    page_to_slot_[page_id] = addr;

    // 重新套用持久化的 TTL 政策 —— 否則 TTL 只會觸發一次
    apply_ttl_policy(page_id);
}

// ── Bit flip 取樣（Poisson，不修改 data）────────────────────────────────────

int RAM::sample_flips(uint64_t page_id, double t) {
    if (config_.lambda_eff <= 0.0) return 0;
    auto& s  = slot(page_id);   // page 此時必在 RAM
    double dt = std::max(t - s.last_check, 0.0);
    s.last_check = t;
    if (dt <= 0.0) return 0;
    std::poisson_distribution<int> dist(config_.lambda_eff * dt);
    return dist(rng_);
}

// ── read ─────────────────────────────────────────────────────────────────────

RAMReadResult RAM::read(uint64_t page_id, double current_time) {
    validate_page_id(page_id);
    current_time_ = current_time;
    stats_.n_reads++;

    // 1. TTL 懶惰檢查
    bool hit = is_in_ram(page_id);
    if (hit && check_ttl(page_id, current_time)) hit = false;

    double latency = config_.t_mem;

    // 2. Cache miss：從 SSD 載入
    if (!hit) {
        stats_.n_misses++;
        if (free_slots_.empty()) do_evict_lru(current_time);
        do_load(page_id, current_time);
        latency += config_.t_ssd;
    } else {
        stats_.n_hits++;
        slot(page_id).last_access = current_time;
    }

    // 3. Theta-verify
    if (config_.enable_verify) {
        auto& sv = slot(page_id);
        if ((current_time - sv.last_verified) > config_.theta) {
            sv.last_verified = current_time;
            stats_.n_verifications++;
        }
    }

    // 無 ECC：bit flip 由 inject_* 方法注入，read 不做任何修正
    return {slot(page_id).data, hit, latency, 0, 0, 0, to_phys(page_id)};
}

// ── write ────────────────────────────────────────────────────────────────────

void RAM::write(uint64_t page_id,
                   const std::vector<uint8_t>& data,
                   double current_time) {
    validate_page_id(page_id);
    current_time_ = current_time;
    stats_.n_writes++;

    if (!is_in_ram(page_id)) {
        // 不在 RAM：從 free_slots_ 取一格（必要時先逐出）
        if (free_slots_.empty()) do_evict_lru(current_time);
        DRAMAddress addr = free_slots_.front();
        free_slots_.pop();

        auto& s         = banks_[addr.bank][addr.row];
        s.valid         = true;
        s.owner_page_id = page_id;
        s.last_check    = current_time;
        s.load_time     = current_time;
        s.is_cold       = false;
        s.ttl           = std::numeric_limits<double>::infinity();
        page_to_slot_[page_id] = addr;
        apply_ttl_policy(page_id);    // 重新套用持久化 TTL 政策
    }

    auto& s       = slot(page_id);
    s.data          = data;
    s.last_access   = current_time;
    s.last_check    = current_time;   // 重置 flip 計時（資料已更新）
    s.last_verified = current_time;   // 資料全新，verify epoch 從現在起算
    s.load_time     = current_time;   // 寫入即刷新：曝露窗 T_reload 歸零
                                      //（資料與 SSD 一致，累積的 flip 已被覆蓋）

    // Write-through：同步寫回 SSD
    ssd_status st = ssd_->write(static_cast<uint32_t>(page_id), data);
    if (st != ssd_status::success)
        throw std::runtime_error(
            "RAM::write: SSD write failed for page_id " +
            std::to_string(page_id));
}

// ── allocate ─────────────────────────────────────────────────────────────────

uint64_t RAM::allocate(double current_time) {
    current_time_ = current_time;

    uint64_t new_id = next_page_id_++;

    // 空白頁（含合法 SSD header）
    std::vector<uint8_t> empty(DRAM_PAGE_SIZE, 0);
    fill_ssd_header(empty);

    // 先寫 SSD（確保 page 存在於持久層）
    ssd_status st = ssd_->write(static_cast<uint32_t>(new_id), empty);
    if (st != ssd_status::success)
        throw std::runtime_error(
            "RAM::allocate: SSD write failed for new_id " +
            std::to_string(new_id));

    // 若 RAM 已滿則先逐出，再取空閒格
    if (free_slots_.empty()) do_evict_lru(current_time);
    DRAMAddress addr = free_slots_.front();
    free_slots_.pop();

    auto& s         = banks_[addr.bank][addr.row];
    s.data          = empty;
    s.valid         = true;
    s.owner_page_id = new_id;
    s.last_access   = current_time;
    s.last_check    = current_time;
    s.last_verified = current_time;
    s.load_time     = current_time;
    s.is_cold       = false;
    s.ttl           = std::numeric_limits<double>::infinity();

    page_to_slot_[new_id] = addr;

    // 全局 TTL 開關：自動將新頁設為冷頁
    if (config_.enable_ttl)
        set_ttl(new_id, config_.ttl_seconds);
    else
        apply_ttl_policy(new_id);   // 若外部曾為此 page_id 設過政策則套回

    stats_.n_allocations++;
    return new_id;
}

// ── free_page ────────────────────────────────────────────────────────────────

void RAM::free_page(uint64_t page_id) {
    validate_page_id(page_id);

    auto it = page_to_slot_.find(page_id);
    if (it != page_to_slot_.end()) {
        auto [b, r] = it->second;
        auto& s     = banks_[b][r];
        s.valid         = false;
        s.data.clear();
        s.owner_page_id = UINT64_MAX;
        free_slots_.push({b, r});
        page_to_slot_.erase(it);
    }

    ttl_policy_.erase(page_id);   // 頁面釋放 → TTL 政策一併移除
    ssd_->trim(static_cast<uint32_t>(page_id));
}

// ── set_ttl ───────────────────────────────────────────────────────────────────

void RAM::set_ttl(uint64_t page_id, double ttl_seconds) {
    validate_page_id(page_id);

    // 1. 更新持久化政策（不論該頁此刻在不在 RAM 內）
    //    這是與舊版的關鍵差異：舊版對不在 RAM 的頁直接 return，
    //    且 do_load/allocate 又會把 is_cold 重設為 false，
    //    導致 TTL 最多只觸發一次。
    if (std::isinf(ttl_seconds)) ttl_policy_.erase(page_id);
    else                         ttl_policy_[page_id] = ttl_seconds;

    // 2. 若該頁目前在 RAM 內，立即套用到 slot
    apply_ttl_policy(page_id);
}

// ── apply_ttl_policy ─────────────────────────────────────────────────────────
// 把 ttl_policy_ 中的設定套回目前的 slot。頁不在 RAM 內時為 no-op
//（等下次 do_load/allocate 時再套）。
void RAM::apply_ttl_policy(uint64_t page_id) {
    auto it = page_to_slot_.find(page_id);
    if (it == page_to_slot_.end()) return;

    auto [b, r] = it->second;
    auto& s     = banks_[b][r];

    auto pit = ttl_policy_.find(page_id);
    if (pit == ttl_policy_.end()) {
        s.is_cold = false;
        s.ttl     = std::numeric_limits<double>::infinity();
    } else {
        s.is_cold = true;
        s.ttl     = pit->second;
    }
}

// ── residency ────────────────────────────────────────────────────────────────
// 曝露窗 T_reload：自上次從 SSD 載入（或配置）至今的駐留時間。
// 頁不在 RAM 內 → 0（下次讀取必然重載，曝露從零起算）。
double RAM::residency(uint64_t page_id, double now) const {
    auto it = page_to_slot_.find(page_id);
    if (it == page_to_slot_.end()) return 0.0;
    const auto& s = banks_[it->second.bank][it->second.row];
    if (!s.valid) return 0.0;
    return (now > s.load_time) ? (now - s.load_time) : 0.0;
}

// ── 指定位置的注入（FaultModel 用）──────────────────────────────────────────

bool RAM::flip_bit(uint64_t page_id, uint32_t byte, uint8_t bit) {
    if (byte >= DRAM_PAGE_SIZE || bit >= 8) return false;
    auto it = page_to_slot_.find(page_id);
    if (it == page_to_slot_.end()) return false;      // 不在 RAM，無 DRAM 副本可翻
    auto& s = banks_[it->second.bank][it->second.row];
    if (!s.valid || s.data.size() <= byte) return false;
    s.data[byte] ^= static_cast<uint8_t>(1u << bit);
    return true;                                       // XOR 必定改變資料
}

bool RAM::force_bit(uint64_t page_id, uint32_t byte, uint8_t bit, bool value) {
    if (byte >= DRAM_PAGE_SIZE || bit >= 8) return false;
    auto it = page_to_slot_.find(page_id);
    if (it == page_to_slot_.end()) return false;
    auto& s = banks_[it->second.bank][it->second.row];
    if (!s.valid || s.data.size() <= byte) return false;

    const uint8_t mask = static_cast<uint8_t>(1u << bit);
    const bool    cur  = (s.data[byte] & mask) != 0;
    if (cur == value) return false;                    // 已是卡住的值 → 資料未改變
    if (value) s.data[byte] |=  mask;
    else       s.data[byte] &= static_cast<uint8_t>(~mask);
    return true;
}

// ── evict ────────────────────────────────────────────────────────────────────
// 主動逐出（積極 TTL 用）。與 check_ttl 的逐出路徑相同，
// 差別只在不檢查到期條件 —— 由呼叫端負責判斷。
// SSD 上有 write-through 的乾淨副本，因此丟掉 DRAM 副本是安全的。
bool RAM::evict(uint64_t page_id) {
    auto it = page_to_slot_.find(page_id);
    if (it == page_to_slot_.end()) return false;   // 不在 RAM

    auto [b, r] = it->second;
    auto& s = banks_[b][r];
    s.valid         = false;
    s.data.clear();
    s.owner_page_id = UINT64_MAX;
    free_slots_.push({b, r});
    page_to_slot_.erase(it);
    stats_.n_ttl_evictions++;
    return true;
}

// ── Error Injection ───────────────────────────────────────────────────────────

// 1. 隨機翻 1 bit
void RAM::inject_random_flip(uint64_t page_id) {
    validate_page_id(page_id);
    if (!is_in_ram(page_id)) return;
    auto& s = slot(page_id);

    std::uniform_int_distribution<uint32_t> col_dist(0, DRAM_PAGE_SIZE - 1);
    std::uniform_int_distribution<int>      bit_dist(0, 7);
    uint32_t col = col_dist(rng_);
    int      bit = bit_dist(rng_);
    s.data[col] ^= static_cast<uint8_t>(1u << bit);
}

// 2. 指定 bank 內連續 2 個 row 翻 flip_ratio 比例的 bit（物理 row hammer）
void RAM::inject_row_error(uint32_t bank, uint32_t start_row, double flip_ratio) {
    if (bank >= DRAM_NUM_BANKS) return;
    std::bernoulli_distribution flip_dist(flip_ratio);
    for (uint32_t r = start_row; r < start_row + 2 && r < config_.rows_per_bank; ++r) {
        auto& s = banks_[bank][r];
        if (!s.valid) continue;
        for (auto& byte : s.data)
            for (int b = 0; b < 8; ++b)
                if (flip_dist(rng_))
                    byte ^= static_cast<uint8_t>(1u << b);
    }
}

// 3. 同 bank 內連續 num_rows 個 row，各翻 (col_byte, bit) 這個 bit（column 故障）
void RAM::inject_column_error(uint32_t bank,
                                  uint32_t start_row,
                                  uint32_t col_byte,
                                  uint8_t  bit,
                                  uint32_t num_rows) {
    if (bank >= DRAM_NUM_BANKS || col_byte >= DRAM_PAGE_SIZE || bit >= 8) return;
    uint32_t end_row = std::min(start_row + num_rows, config_.rows_per_bank);
    for (uint32_t r = start_row; r < end_row; ++r) {
        auto& s = banks_[bank][r];
        if (!s.valid) continue;
        s.data[col_byte] ^= static_cast<uint8_t>(1u << bit);
    }
}

// ── ECC_RAM：write / read / free_page ────────────────────────────────────────

// write：呼叫基底類別後，計算並儲存每個 8-byte word 的 Hamming parity
void ECC_RAM::write(uint64_t page_id,
                    const std::vector<uint8_t>& data,
                    double current_time) {
    RAM::write(page_id, data, current_time);

    static constexpr int WORDS = DRAM_PAGE_SIZE / 8;  // 512
    auto& p = parity_[page_id];
    p.resize(WORDS);
    for (int w = 0; w < WORDS; ++w) {
        uint64_t word = 0;
        std::memcpy(&word, data.data() + w * 8, 8);
        p[w] = ecc_compute(word);
    }
}

// read：呼叫基底類別取得（可能已損壞的）data，再逐 word 套用 SECDED
RAMReadResult ECC_RAM::read(uint64_t page_id, double current_time) {
    RAMReadResult result = RAM::read(page_id, current_time);

    auto pit = parity_.find(page_id);
    if (pit == parity_.end()) {
        // 尚未寫入過（全零頁），parity 全 0，ecc_check 也不會找到錯誤
        return result;
    }
    const auto& p = pit->second;
    static constexpr int WORDS = DRAM_PAGE_SIZE / 8;

    int n_corrected = 0, n_ue = 0, n_misc = 0;
    for (int w = 0; w < WORDS; ++w) {
        uint64_t word = 0;
        std::memcpy(&word, result.data.data() + w * 8, 8);
        auto r = ecc_check(word, p[w]);
        switch (r.status) {
            case EccStatus::CORRECTED:
                std::memcpy(result.data.data() + w * 8, &r.word, 8);
                n_corrected++;
                stats_.n_hw_corrected++;
                break;
            case EccStatus::UNCORRECTABLE:
                n_ue++;
                stats_.n_ecc_ue++;
                break;
            case EccStatus::MISCORRECTED:
                // syndrome 指向無效位置：data 不動但有錯誤，靜默損壞
                std::memcpy(result.data.data() + w * 8, &r.word, 8);
                n_misc++;
                stats_.n_hw_silent++;
                break;
            case EccStatus::OK:
            default:
                break;
        }
    }

    // theta-verify：若剛觸發驗證，記錄 ECC 偵測到的問題數（UE + miscorrected）
    if (config_.enable_verify) {
        uint64_t detected = static_cast<uint64_t>(n_ue + n_misc);
        if (detected > 0) stats_.n_verify_detections += detected;
    }

    result.n_corrected = n_corrected;
    result.n_ecc_ue    = n_ue;
    result.n_silent    = n_misc;
    return result;
}

// free_page：清除 parity 記錄後交給基底類別
void ECC_RAM::free_page(uint64_t page_id) {
    parity_.erase(page_id);
    RAM::free_page(page_id);
}

// 4. 單一 SECDED ECC word（8 bytes / 64 bits）內翻 num_flips 個不重複的 bit
//
// ⚠️ 粒度必須等於 ECC_WORD_BYTES。舊版用 16 bytes，橫跨「兩個」64-bit ECC word，
//    使得「N 個翻轉落在同一個 ECC word」的語意失效：
//    例如 num_flips=3 可能散成 2+1，得到 1 個 UE（偶數錯）+ 1 個修正，
//    而非預期的單一 word 內 3-bit 奇數錯（miscorrection）。
//
// 對齊之後的行為是確定的：
//    num_flips=1 → CORRECTED
//    num_flips=2 → UNCORRECTABLE（DED）
//    num_flips=3 → 奇數錯 → 誤修正（CORRECTED 或 MISCORRECTED），不會是 UE
void RAM::inject_ecc_word_error(uint64_t page_id,
                                    uint32_t ecc_word_offset,
                                    int      num_flips) {
    validate_page_id(page_id);
    if (!is_in_ram(page_id)) return;
    auto& s = slot(page_id);

    uint32_t base = ecc_word_offset * ECC_WORD_BYTES;
    if (base + ECC_WORD_BYTES > DRAM_PAGE_SIZE) return;

    std::uniform_int_distribution<uint32_t> col_dist(base, base + ECC_WORD_BYTES - 1);
    std::uniform_int_distribution<int>      bit_dist(0, 7);

    std::set<std::pair<uint32_t, int>> positions;
    int attempts = num_flips * 20;
    while (static_cast<int>(positions.size()) < num_flips && attempts-- > 0)
        positions.insert({col_dist(rng_), bit_dist(rng_)});

    for (auto [col, bit] : positions)
        s.data[col] ^= static_cast<uint8_t>(1u << bit);
}
