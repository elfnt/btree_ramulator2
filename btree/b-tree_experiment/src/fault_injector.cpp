// fault_injector.cpp — 把組態錯誤率轉成對 RAM::inject_* 的實際呼叫（規格見標頭）
#include "fault_injector.hpp"

namespace bfx {

FaultInjector::FaultInjector(IRAM* ram, GuardedRAM* gram, const ExpConfig* cfg,
                             Metrics* metrics, uint32_t seed)
    : ram_(ram), gram_(gram), cfg_(cfg), metrics_(metrics), rng_(seed),
      rows_per_bank_(cfg->ram_rows_per_bank
                         ? cfg->ram_rows_per_bank
                         : cfg->ssd_blocks * cfg->pages_per_block / DRAM_NUM_BANKS) {}

void FaultInjector::advance(double t_from, double t_to) {
    const double dt = t_to - t_from;
    if (dt <= 0.0) return;

    // 1. 均勻 BER：只打「當下在 RAM 內」的頁
    // E11：inject_level 過濾後仍以 per-page λ 計（均值 = λ × |filtered| × dt）
    const std::vector<uint64_t> resident = gram_->resident_pages_filtered(cfg_->inject_level);
    const double flip_mean = cfg_->lambda_page * (double)resident.size() * dt;
    if (flip_mean > 0.0) {
        std::poisson_distribution<uint64_t> flips(flip_mean);
        const uint64_t n = flips(rng_);
        std::uniform_int_distribution<size_t> pick(0, resident.size() - 1);
        for (uint64_t i = 0; i < n; ++i)
            ram_->inject_random_flip(resident[pick(rng_)]);
        metrics_->n_flip_events += n;
    }

    // 2. row hammer：打物理 (bank, row)，事件本身與 resident 無關
    const double hammer_mean = cfg_->hammer_rate_per_s * dt;
    if (hammer_mean > 0.0 && rows_per_bank_ >= 2) {
        std::poisson_distribution<uint64_t> events(hammer_mean);
        const uint64_t m = events(rng_);
        std::uniform_int_distribution<uint32_t> bank(0, DRAM_NUM_BANKS - 1);
        std::uniform_int_distribution<uint32_t> row(0, rows_per_bank_ - 2);
        for (uint64_t i = 0; i < m; ++i)
            ram_->inject_row_error(bank(rng_), row(rng_), cfg_->hammer_flip_ratio);
        metrics_->n_hammer_events += m;
    }

    // 3. column fault：一次性事件（done 旗標防重複，左界免比對 → t=0 也觸發）
    if (!colfault_done_ && cfg_->colfault_time_s >= 0.0 &&
        cfg_->colfault_time_s <= t_to) {
        ram_->inject_column_error(cfg_->colfault_bank, 0,
                                  cfg_->colfault_byte, cfg_->colfault_bit,
                                  cfg_->colfault_rows);
        colfault_done_ = true;
    }
}

} // namespace bfx
