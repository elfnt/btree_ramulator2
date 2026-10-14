#pragma once
// keymap.hpp — E21：應用 key → 樹 key 的映射層（樹本身不變）。
//
// SHIFT（--key_map=shift）：stride key K = i·2^k 存成 K >> k。保序、零成本。
//   低 k 位非零的 X 不可能存在 → 直接回「不存在」（0 次探測）。
//
// HASHDENSE（--key_map=hashdense --map_load=α）：在樹的 key 空間鋪一張
//   開放定址雜湊表。M = ceil(N_total/α) 個槽；home(K) = mix64(K) mod M；線性探測。
//   每個應用 key 佔兩個相鄰樹 entry：(2s → 原始 K)、(2s+1 → value)。
//   Insert：探測 s, s+1, …（每次 = 一次樹搜尋 2s）直到找不到 → 插入兩個 entry；
//           L_max = 歷來最大探測距離（唯一的可信純量）。
//   Lookup(X)：自 home 起探測。找不到 → 不存在。stored == X → 取 2s+1 的 value。
//           stored = v ≠ X → 一致性檢查：dist(v, s) = (s − home(v)) mod M ≤ L_max？
//           否 → v 不可能合法住在這裡 → 報警、重載該 leaf、重試一次；是 → 真碰撞、繼續探測。
//           key entry 缺 value entry → 同樣報警。探測距離 > L_max → 不存在（無刪除時成立）。
#include <cstdint>
#include "exp_config.hpp"
#include "exp_btree.hpp"
#include "metrics.hpp"

namespace bfx {

// splitmix64 finalizer（好的 64 位元混合器）
inline uint64_t mix64(uint64_t x) {
    x += 0x9e3779b97f4a7c15ull;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ull;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebull;
    return x ^ (x >> 31);
}

class KeyMapper {
public:
    // n_total = prefill + 本 run 將執行的 insert 數（HASHDENSE 用來定 M）
    KeyMapper(ExpBTree* tree, const ExpConfig& cfg, uint64_t n_total, Metrics* metrics);

    void insert(uint64_t K, uint64_t V, double& lat);
    // probes_out = 本次的槽探測數（樹搜尋 2s 的次數，含重試）；slot_out = 命中槽（測試用）
    bool lookup(uint64_t X, uint64_t& V, double& lat, uint64_t& probes_out,
                uint64_t* slot_out = nullptr);

    uint64_t slots() const { return M_; }
    uint64_t lmax()  const { return lmax_; }
    uint64_t home(uint64_t K) const { return mix64(K) % M_; }
    uint64_t dist(uint64_t v, uint64_t s) const { return (s + M_ - home(v) % M_) % M_; }
    bool consistent(uint64_t v, uint64_t s) const { return dist(v, s) <= lmax_; }

private:
    ExpBTree* tree_;
    KeyMap    mode_;
    uint32_t  shift_;
    uint64_t  M_ = 0;
    uint64_t  lmax_ = 0;
    Metrics*  metrics_;
    void alarm(uint64_t leaf_a, uint64_t leaf_b, double& lat);
};

// N_total 的精確預測：以同一 seed 的 wrng 重播主迴圈的 draw 序列，回傳 insert 次數。
// （須與 main_experiment.cpp 主迴圈的 draw 順序逐一相同；driver 期末斷言相等。）
uint64_t keymap_predict_inserts(const ExpConfig& cfg, uint64_t prefill_size);

// 自測（失敗即 abort）：
//  (m1) 乾淨樹上 10^5 個 random key 往返：全部找回、10^5 個不存在 key 全部不存在、0 報警
//  (m2) 邏輯層：每個已存 key 的 64 個單位元翻轉 → 一致性檢查抓到比例 ≈ 1 − (L_max+1)/M
//  (m3) 端到端：在 DRAM 裡實際翻轉存放的原始 key（flip_bit），lookup 必須
//       「報警 + 重載 + 回正確 value」或「未抓到 → 回不存在」，且抓到比例與 (m2) 一致
// 回傳摘要字串（driver 印到 stderr）。
void keymap_self_test(const ExpConfig& base);

} // namespace bfx
