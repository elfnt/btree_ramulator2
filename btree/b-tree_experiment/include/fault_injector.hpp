#pragma once
// fault_injector.hpp — 故障注入排程：把組態的錯誤率轉成對 RAM::inject_* 的呼叫
//
// v2 的 Poisson flip 模型只計數、不改資料；真實毀損由本類主動注入。
// 注入只作用於「當下在 RAM 內」的頁（物理正確：flip 發生在 DRAM）。
#include <cstdint>
#include <random>
#include "../../new_RAM_core/new_ram.hpp"
#include "guarded_ram.hpp"
#include "metrics.hpp"

namespace bfx {

class FaultInjector {
public:
    FaultInjector(IRAM* ram, GuardedRAM* gram, const ExpConfig* cfg,
                  Metrics* metrics, uint32_t seed);

    // 把模擬時間從 t_from 推到 t_to，期間：
    //  1. 均勻 BER：n ~ Poisson(lambda_page × |resident| × (t_to - t_from))，
    //     每次均勻挑一個 resident 頁 → ram->inject_random_flip(page)；
    //     metrics->n_flip_events += n。
    //  2. row hammer：m ~ Poisson(hammer_rate_per_s × dt)，每次均勻挑
    //     bank ∈ [0,8)、start_row ∈ [0, rows_per_bank-1) →
    //     ram->inject_row_error(bank, start_row, hammer_flip_ratio)；
    //     metrics->n_hammer_events += m。
    //  3. column fault：若 0 <= colfault_time_s <= t_to 且尚未觸發 →
    //     ram->inject_column_error(...) 一次（t=0 於首個區間觸發）。
    // 事件排程用本類自有的 mt19937（campaign seed）；flip 的 byte/bit 位置
    // 由 RAM 內部 rng 決定（公開 API 行為）。
    void advance(double t_from, double t_to);

private:
    IRAM* ram_; GuardedRAM* gram_;
    const ExpConfig* cfg_; Metrics* metrics_;
    std::mt19937 rng_;
    uint32_t rows_per_bank_;
    bool colfault_done_ = false;
};

} // namespace bfx
