#pragma once
// metrics.hpp — 混淆矩陣、事件計數、延遲統計、CSV 輸出
#include <cstdint>
#include <string>
#include "exp_config.hpp"

namespace bfx {

// 頁級偵測分類：truth = 「讀到的 image != oracle」、predicted = 「保護層報警」
struct Confusion {
    uint64_t tp = 0, fp = 0, fn = 0, tn = 0;
    void add(bool truth, bool predicted);
    double precision() const;   // 0 分母 → 回傳 -1（CSV 印空欄）
    double recall()    const;   // 同上
    double f1()        const;   // 同上
};

struct Metrics {
    Confusion page_read;            // 每次 guarded read 一筆

    // 事件計數
    uint64_t n_ops              = 0;
    uint64_t n_guarded_reads    = 0;
    uint64_t n_protected_reads  = 0;   // 讀取當下該頁有 shadow entry
    uint64_t n_flip_events      = 0;   // injector 實際執行的注入呼叫數
    uint64_t n_hammer_events    = 0;
    uint64_t n_recoveries       = 0;   // 偵測後 SSD 重載
    uint64_t n_would_crash      = 0;   // 未偵測 + 結構毀損到無法安全解析（fail-stop 續跑）
    uint64_t n_poisoned_writes  = 0;   // 本 op 曾發生 FN 讀，其後仍執行了節點寫回
    uint64_t n_shadow_rejected  = 0;   // 預算不足被拒／擠掉的 protect 次數

    // ── 毀損歸因：control-plane vs payload（每次 truth_corrupt 的 read 一筆）──
    //
    // 以 oracle（地面真相）算出的 ctrl_len 為界，把「讀到的 image 與 oracle 相異的
    // 位元組位置」分成三區：[0,16) SSD header、[16,16+ctrl_len) 控制平面、
    // [16+ctrl_len, page_size) payload（僅 leaf 的 values[] 落在此區；internal
    // 節點的 ctrl_len 已涵蓋全部內容，此區只有補零）。
    //
    // 分類為互斥且窮盡的四類，優先序：
    //   1. ssd_header   — 有任何相異位元組落在 [0,16)
    //   2. mixed        — 控制平面與 payload 同時有相異位元組
    //   3. ctrl_only    — 相異位元組全在控制平面
    //   4. payload_only — 相異位元組全在 payload
    // 四者相加恆等於 page_read.tp + page_read.fn（= truth_corrupt 的讀取次數），
    // 這是資料品質檢查的不變量。
    //
    // 研究用途：ctrl_only + mixed = CTRL_CRC 在原理上「看得見」的毀損；
    // payload_only = 不保護 values[] 就結構上不可能偵測的部分——直接量出
    // 「Task 1 的修補最多能買到多少」與「剩下多少是無解的」。
    uint64_t n_corrupt_reads_ctrl_only    = 0;
    uint64_t n_corrupt_reads_payload_only = 0;
    uint64_t n_corrupt_reads_mixed        = 0;
    uint64_t n_corrupt_reads_ssd_header   = 0;

    // payload_only 的**子集**（不是第五類，不進上面的四類總和）：相異位元組
    // 全部落在 [16+live_len, page_size) 的未使用補零 slack 內。
    //
    // 為什麼需要它：order=253 的葉節點平均只裝 ~174 個 key，頁面有很大一塊是
    // 永遠不會被讀到的補零。落在那裡的 flip 與 oracle 相異（算「毀損」）、
    // FULL_CRC 會偵測並回復它，但它**在語意上完全無害**——B+ 樹只讀
    // n_keys 個 slot。因此
    //     payload_only − slack_only = 真正打到 values[] 的毀損
    // 才是「不保護 values[] 的實際代價」；直接引用 payload_only 會高估。
    uint64_t n_corrupt_reads_slack_only   = 0;

    // ── E7′：key 陣列內的「翻轉位元位置」直方圖 ────────────────────────────────
    //
    // 為什麼在這裡量：注入端（new_RAM_core 的 RAM::inject_random_flip）自己抽
    // (byte, bit) 且回傳 void，實驗層看不到；而 new_RAM_core 對本層是唯讀相依。
    // 但 GuardedRAM::read 已經有 oracle 可比對，`got[j] ^ oracle[j]` 就是
    // 被翻的 bit mask——位元位置因此可以在**不動 v2 任何一行**的前提下取得。
    //
    // 只在「整頁恰有一個位元組相異、且該位元組落在 keys[] 陣列
    // （image[32, 32+n_keys*8)，leaf 與 internal 佈局相同）」時記錄：
    // 這樣 bit 位置對「這個 key 被移動了多少」才有唯一解釋。
    // bit 索引 = ((off-32) % 8) * 8 + (該位元組內的 bit)，即 64 位元 key 的
    // little-endian 位元序（0 = 最低位）。
    //
    // 每個 bucket 兩個計數：
    //   keybit_seen[b] — 觀察到的毀損讀取數（分母，讀取加權）
    //   keybit_tp[b]   — 其中被偵測到的數（偵測後會回復 → 每個毀損事件至多一次，
    //                    故 keybit_tp 近似「事件數」）
    // FULL_CRC 的 keybit_seen == keybit_tp（recall = 1，第一次讀就抓到並回復），
    // 因此它是「每個 bit 位置的曝險事件數」的乾淨分母，供其他 scheme 配對相除。
    static constexpr int KEYBIT_BUCKETS = 64;
    uint64_t keybit_seen[KEYBIT_BUCKETS] = {0};
    uint64_t keybit_tp  [KEYBIT_BUCKETS] = {0};

    // 單一位元組相異（= 上面直方圖的總和）與其偵測數
    uint64_t n_keyflip_single      = 0;
    uint64_t n_keyflip_single_tp   = 0;
    // 上者中落在 leaf 的部分（internal = single − leaf）
    uint64_t n_keyflip_single_leaf    = 0;
    uint64_t n_keyflip_single_leaf_tp = 0;
    // 相異位元組 ≥ 2 且至少一個落在 keys[] 的讀取：被直方圖排除的量，
    // 用來量化「多重 flip 累積」對直方圖造成的取樣偏差上限。
    uint64_t n_keyflip_multi       = 0;
    uint64_t n_keyflip_multi_tp    = 0;

    // ── E13：leaf 單一 key 翻轉，依 oracle value slot 分真 key / dummy key ──────
    uint64_t n_dummy_keys        = 0;   // driver 插入的 dummy 總數（prefill + 主迴圈）
    uint64_t n_keyflip_real      = 0, n_keyflip_real_tp  = 0;
    uint64_t n_keyflip_dummy     = 0, n_keyflip_dummy_tp = 0;
    uint64_t kbr_seen[KEYBIT_BUCKETS] = {0};   // 同 keybit_seen，但只計真 key（leaf）
    uint64_t kbr_tp  [KEYBIT_BUCKETS] = {0};

    // ── E17–E20：SANITY-only 延伸 ────────────────────────────────────────────
    // n_range_alarms      : parent–child 範圍檢查報警次數（每次報警 = 子節點讀取被判 predicted）
    // n_range_parent_bad  : 報警當下，路徑上提供界限／指標的祖先節點（tree 持有的內容）≠ oracle
    // n_range_child_bad   : 報警當下，子節點讀回的 DRAM image ≠ oracle
    //   （兩者可同時成立；兩者皆否 = 持久毀損（SSD/oracle 已被 poisoned write 汙染）造成的報警）
    // n_range_restarts    : 因範圍報警而從 root 重新下降的次數
    // n_range_giveups     : 重新下降 2 次後仍報警 → 放棄檢查、照讀到的內容繼續
    // n_range_anc_recoveries : 為範圍報警而從 SSD 重載的祖先節點數（亦計入 n_recoveries）
    uint64_t n_range_alarms = 0, n_range_parent_bad = 0, n_range_child_bad = 0;
    uint64_t n_range_restarts = 0, n_range_giveups = 0, n_range_anc_recoveries = 0;
    // E19：run 結束時以 oracle 掃描所有 leaf：真 key 數、帶右/左 dummy 的真 key 數、dummy 總數
    uint64_t slack_real_keys = 0, slack_with_right = 0, slack_with_left = 0, slack_dummies = 0;

    // ── E21：key 映射（key_map ≠ none 時才非零）──────────────────────────────
    uint64_t map_slots = 0, map_lmax = 0;            // M 與期末 L_max（最大探測距離）
    uint64_t n_probes_hit = 0, n_probes_miss = 0;    // 主迴圈搜尋的槽探測總數（依 ref 期望分）
    uint64_t n_map_lookups_hit = 0, n_map_lookups_miss = 0;   // 對應的搜尋次數（分母）
    uint64_t n_map_alarms = 0;                       // 一致性檢查報警（含缺 value entry）

    // 端到端
    uint64_t n_searches         = 0;
    uint64_t n_wrong_undetected = 0;   // search 結果錯且該 op 全程無任何報警（真 SDC）
    uint64_t n_wrong_total      = 0;   // search 結果錯（不論有無報警）
    uint64_t n_final_integrity_errors = 0;  // 結束後全 key 掃描不符數

    // ── E12：錯誤搜尋的三分類（互斥窮盡，總和 == n_wrong_total）──────────────
    //   missing : 預期找到、實際沒找到
    //   value   : 找到了但 value 錯
    //   phantom : 預期不存在、實際找到
    // n_sdc_* = 同三分類但只計「該 op 全程無報警」者（總和 == n_wrong_undetected）
    uint64_t n_wrong_missing = 0, n_wrong_value = 0, n_wrong_phantom = 0;
    uint64_t n_sdc_missing   = 0, n_sdc_value   = 0, n_sdc_phantom   = 0;

    // ── E8：key 集合的 SANITY 解析預測（driver 於 run 結束時以最終 key 集合計算）──
    //   pred_sanity_rel   = mean_k (64 − floor(log2(min(gap_l, gap_r)))) / 64（規格公式）
    //   pred_sanity_exact = mean_{k,b}「翻 k 的第 b 位後越過任一全域鄰居」的比例
    //                       （方向敏感、不考慮葉邊界；同為葉層 gap 的預測）
    double pred_sanity_rel   = -1.0;
    double pred_sanity_exact = -1.0;

    // 延遲（模擬秒）
    double   total_latency_s  = 0.0;
    double   max_op_latency_s = 0.0;
    void     add_op_latency(double s);

    // shadow 使用量
    uint64_t shadow_bytes_used_max = 0;

    // 樹/RAM 快照（run 結束時填）
    uint64_t n_pages_allocated = 0;
    uint32_t tree_height       = 0;

    // ── E2b′–E2e′：逐層節點數 ────────────────────────────────────────────────
    //
    // n_nodes_level[l] = 期末「離葉子高度 = l」的節點數（l = 0 即葉節點）。
    // 來源 = ExpBTree 在每次 allocate_page 時依該節點的 level 記一筆
    // （B+ 樹中節點離葉的高度是不變量、且本實驗無刪除，故等於期末存活數）。
    //
    // 不變量（driver 在寫 CSV 前檢查，違反則 stderr 警告）：
    //   Σ_l n_nodes_level[l] == n_pages_allocated
    //   n_internal_total     == n_pages_allocated - n_nodes_level[0]
    //   最高的非零 level     == tree_height - 1
    //
    // 為什麼需要：E2′（§6）宣稱「內部節點只佔全樹 0.42 %，512 B 就全包」，
    // 但 CSV 只有 tree_height 與 n_pages_allocated，這個比例無法從資料直接查證，
    // 只能由 order/N 反推。有了逐層欄位，B_int = n_internal_total × entry_bytes
    // 就是可從 CSV 直接讀出的量。
    static constexpr int MAX_TREE_LEVELS = 8;
    uint64_t n_nodes_level[MAX_TREE_LEVELS] = {0};
    uint64_t n_internal_total = 0;      // = Σ_{l≥1} n_nodes_level[l]
    uint64_t ram_hits = 0, ram_misses = 0, ram_lru_evictions = 0, ram_ttl_evictions = 0;

    // CSV：欄位順序 = 組態回顯 + 上列全部 + 衍生 P/R/F1。
    // 檔案不存在（或為空）時先寫 header 列；一個 run append 一列。
    static std::string csv_header();
    // E7′ 追加欄位的表頭（接在原 60 欄之後；獨立函式方便測試比對）
    static std::string extra_header();
    std::string csv_row(const ExpConfig& cfg) const;
    // 寫入 cfg.csv_path（必要時建目錄）。失敗 → 資料列印到 stderr、回傳 false
    // （driver 據此以非零碼結束，讓 set -e 的掃描腳本停下）。
    bool append_csv(const ExpConfig& cfg) const;
};

} // namespace bfx
