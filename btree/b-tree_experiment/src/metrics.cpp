// metrics.cpp — 混淆矩陣、延遲統計、CSV 輸出
#include "metrics.hpp"
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>

namespace bfx {

void Confusion::add(bool truth, bool predicted) {
    if (truth) predicted ? ++tp : ++fn;
    else       predicted ? ++fp : ++tn;
}

double Confusion::precision() const {
    const uint64_t d = tp + fp;
    return d ? (double)tp / (double)d : -1.0;
}

double Confusion::recall() const {
    const uint64_t d = tp + fn;
    return d ? (double)tp / (double)d : -1.0;
}

double Confusion::f1() const {
    const uint64_t d = 2 * tp + fp + fn;
    return d ? 2.0 * (double)tp / (double)d : -1.0;
}

void Metrics::add_op_latency(double s) {
    total_latency_s += s;
    if (s > max_op_latency_s) max_op_latency_s = s;
}

namespace {

std::string fmt(double v) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "%.6g", v);
    return buf;
}

std::string fmt_ratio(double v) {    // -1（分母 0）→ 空欄
    return v < 0.0 ? std::string() : fmt(v);
}

} // namespace

std::string Metrics::csv_header() {
    // ⚠️ 舊 CSV（e1–e6b_dbscale.csv）的 60 欄順序**不可更動**：E7′ 新增的欄位
    // 一律接在最後（見下方 extra_header），舊 reader 仍能照原本的位置解析。
    return "run_id,scheme,policy,budget_bytes,verify_mode,theta_s,sanity_always,"
           "lambda_page,hammer_rate_per_s,hammer_flip_ratio,colfault_time_s,"
           "colfault_bank,colfault_byte,colfault_bit,colfault_rows,"
           "dt_op_s,order,prefill_keys,n_ops,"
           "read_ratio,miss_ratio,seed,ssd_blocks,pages_per_block,ram_rows_per_bank,"
           "n_ops_done,n_guarded_reads,n_protected_reads,tp,fp,fn,tn,"
           "precision,recall,f1,n_flip_events,n_hammer_events,n_recoveries,"
           "n_would_crash,n_poisoned_writes,n_shadow_rejected,n_searches,"
           "n_wrong_undetected,n_wrong_total,n_final_integrity_errors,"
           "total_latency_s,mean_op_latency_s,max_op_latency_s,"
           "shadow_bytes_used_max,n_pages_allocated,tree_height,"
           "ram_hits,ram_misses,ram_lru_evictions,ram_ttl_evictions,"
           "n_corrupt_reads_ctrl_only,n_corrupt_reads_payload_only,"
           "n_corrupt_reads_mixed,n_corrupt_reads_ssd_header,n_corrupt_reads_slack_only"
           + extra_header();
}

// E7′ 追加欄位（一律接在 60 欄之後）
std::string Metrics::extra_header() {
    std::ostringstream o;
    o << ",key_stride_log2"
      << ",n_keyflip_single,n_keyflip_single_tp"
      << ",n_keyflip_single_leaf,n_keyflip_single_leaf_tp"
      << ",n_keyflip_multi,n_keyflip_multi_tp";
    for (int b = 0; b < KEYBIT_BUCKETS; ++b) {
        char buf[32];
        std::snprintf(buf, sizeof buf, ",kb_seen_%02d", b);
        o << buf;
    }
    for (int b = 0; b < KEYBIT_BUCKETS; ++b) {
        char buf[32];
        std::snprintf(buf, sizeof buf, ",kb_tp_%02d", b);
        o << buf;
    }
    // ── E2b′–E2e′ 追加欄位（再接在 E7′ 之後；舊 CSV 的欄位位置一律不動）──────────
    for (int l = 0; l < Metrics::MAX_TREE_LEVELS; ++l) {
        char buf[32];
        std::snprintf(buf, sizeof buf, ",n_nodes_level_%d", l);
        o << buf;
    }
    o << ",n_internal_total";
    // ── E8–E12 追加欄位（再接在 E2b′ 之後）──────────────────────────────────────
    o << ",key_dist,inject_level,pred_sanity_rel,pred_sanity_exact"
      << ",n_wrong_missing,n_wrong_value,n_wrong_phantom"
      << ",n_sdc_missing,n_sdc_value,n_sdc_phantom";
    // ── E13 追加欄位（再接在 E8–E12 之後）──────────────────────────────────────
    o << ",guard,n_dummy_keys,n_keyflip_real,n_keyflip_real_tp,n_keyflip_dummy,n_keyflip_dummy_tp";
    for (int b = 0; b < KEYBIT_BUCKETS; ++b) {
        char buf[32];
        std::snprintf(buf, sizeof buf, ",kbr_seen_%02d", b);
        o << buf;
    }
    for (int b = 0; b < KEYBIT_BUCKETS; ++b) {
        char buf[32];
        std::snprintf(buf, sizeof buf, ",kbr_tp_%02d", b);
        o << buf;
    }
    // ── E17–E20 追加欄位（再接在 E13 之後）──────────────────────────────────────
    o << ",sanity_range,sanity_align_log2,slack_guard"
      << ",n_range_alarms,n_range_parent_bad,n_range_child_bad"
      << ",n_range_restarts,n_range_giveups,n_range_anc_recoveries"
      << ",slack_real_keys,slack_dummies,frac_guard_right,frac_guard_left";
    // ── E22 追加欄位（再接在 E17–E20 之後）──────────────────────────────────────
    o << ",guard_grid_log2";
    // ── E21 追加欄位（接在最後，既有欄位順序不變）──
    o << ",key_map,map_load,map_slots,map_lmax,n_probes_hit,n_probes_miss,n_map_alarms"
      << ",n_map_lookups_hit,n_map_lookups_miss";
    return o.str();
}

std::string Metrics::csv_row(const ExpConfig& cfg) const {
    std::ostringstream o;
    o << cfg.run_id
      << ',' << scheme_name(cfg.scheme)
      << ',' << policy_name(cfg.policy)
      << ',' << (cfg.budget_bytes == UINT64_MAX ? std::string("inf")
                                                : std::to_string(cfg.budget_bytes))
      << ',' << verify_mode_name(cfg.verify_mode)
      << ',' << fmt(cfg.theta_s)
      << ',' << (cfg.sanity_always ? 1 : 0)
      << ',' << fmt(cfg.lambda_page)
      << ',' << fmt(cfg.hammer_rate_per_s)
      << ',' << fmt(cfg.hammer_flip_ratio)
      << ',' << fmt(cfg.colfault_time_s)
      << ',' << cfg.colfault_bank
      << ',' << cfg.colfault_byte
      << ',' << (unsigned)cfg.colfault_bit
      << ',' << cfg.colfault_rows
      << ',' << fmt(cfg.dt_op_s)
      << ',' << cfg.order
      << ',' << cfg.prefill_keys
      << ',' << cfg.n_ops
      << ',' << fmt(cfg.read_ratio)
      << ',' << fmt(cfg.miss_ratio)
      << ',' << cfg.seed
      << ',' << cfg.ssd_blocks
      << ',' << cfg.pages_per_block
      << ',' << cfg.ram_rows_per_bank
      << ',' << n_ops
      << ',' << n_guarded_reads
      << ',' << n_protected_reads
      << ',' << page_read.tp
      << ',' << page_read.fp
      << ',' << page_read.fn
      << ',' << page_read.tn
      << ',' << fmt_ratio(page_read.precision())
      << ',' << fmt_ratio(page_read.recall())
      << ',' << fmt_ratio(page_read.f1())
      << ',' << n_flip_events
      << ',' << n_hammer_events
      << ',' << n_recoveries
      << ',' << n_would_crash
      << ',' << n_poisoned_writes
      << ',' << n_shadow_rejected
      << ',' << n_searches
      << ',' << n_wrong_undetected
      << ',' << n_wrong_total
      << ',' << n_final_integrity_errors
      << ',' << fmt(total_latency_s)
      << ',' << fmt(n_ops ? total_latency_s / (double)n_ops : 0.0)
      << ',' << fmt(max_op_latency_s)
      << ',' << shadow_bytes_used_max
      << ',' << n_pages_allocated
      << ',' << tree_height
      << ',' << ram_hits
      << ',' << ram_misses
      << ',' << ram_lru_evictions
      << ',' << ram_ttl_evictions
      << ',' << n_corrupt_reads_ctrl_only
      << ',' << n_corrupt_reads_payload_only
      << ',' << n_corrupt_reads_mixed
      << ',' << n_corrupt_reads_ssd_header
      << ',' << n_corrupt_reads_slack_only
      // ── E7′ 追加欄位（順序須與 extra_header() 完全一致）─────────────────
      << ',' << cfg.key_stride_log2
      << ',' << n_keyflip_single
      << ',' << n_keyflip_single_tp
      << ',' << n_keyflip_single_leaf
      << ',' << n_keyflip_single_leaf_tp
      << ',' << n_keyflip_multi
      << ',' << n_keyflip_multi_tp;
    for (int b = 0; b < KEYBIT_BUCKETS; ++b) o << ',' << keybit_seen[b];
    for (int b = 0; b < KEYBIT_BUCKETS; ++b) o << ',' << keybit_tp[b];
    // E2b′–E2e′ 追加欄位（順序須與 extra_header() 完全一致）
    for (int l = 0; l < MAX_TREE_LEVELS; ++l) o << ',' << n_nodes_level[l];
    o << ',' << n_internal_total;
    // E8–E12 追加欄位（順序須與 extra_header() 完全一致）
    o << ',' << key_dist_name(cfg.key_dist)
      << ',' << inject_level_name(cfg.inject_level)
      << ',' << fmt_ratio(pred_sanity_rel)
      << ',' << fmt_ratio(pred_sanity_exact)
      << ',' << n_wrong_missing << ',' << n_wrong_value << ',' << n_wrong_phantom
      << ',' << n_sdc_missing   << ',' << n_sdc_value   << ',' << n_sdc_phantom;
    // E13 追加欄位（順序須與 extra_header() 完全一致）
    o << ',' << guard_mode_name(cfg.guard) << ',' << n_dummy_keys
      << ',' << n_keyflip_real  << ',' << n_keyflip_real_tp
      << ',' << n_keyflip_dummy << ',' << n_keyflip_dummy_tp;
    for (int b = 0; b < KEYBIT_BUCKETS; ++b) o << ',' << kbr_seen[b];
    for (int b = 0; b < KEYBIT_BUCKETS; ++b) o << ',' << kbr_tp[b];
    // E17–E20 追加欄位（順序須與 extra_header() 完全一致）
    o << ',' << (cfg.sanity_range ? 1 : 0) << ',' << cfg.sanity_align_log2
      << ',' << slack_guard_name(cfg.slack_guard)
      << ',' << n_range_alarms << ',' << n_range_parent_bad << ',' << n_range_child_bad
      << ',' << n_range_restarts << ',' << n_range_giveups << ',' << n_range_anc_recoveries
      << ',' << slack_real_keys << ',' << slack_dummies
      << ',' << fmt(slack_real_keys ? (double)slack_with_right / (double)slack_real_keys : 0.0)
      << ',' << fmt(slack_real_keys ? (double)slack_with_left  / (double)slack_real_keys : 0.0);
    // E22 追加欄位
    o << ',' << cfg.guard_grid_log2;
    // E21 追加欄位（順序須與 extra_header() 完全一致）
    o << ',' << key_map_name(cfg.key_map) << ',' << fmt(cfg.map_load)
      << ',' << map_slots << ',' << map_lmax
      << ',' << n_probes_hit << ',' << n_probes_miss << ',' << n_map_alarms
      << ',' << n_map_lookups_hit << ',' << n_map_lookups_miss;
    return o.str();
}

bool Metrics::append_csv(const ExpConfig& cfg) const {
    // 必要時建目錄；失敗不在此報錯——留給後面的開檔失敗一併回報
    const std::filesystem::path parent =
        std::filesystem::path(cfg.csv_path).parent_path();
    if (!parent.empty()) {
        std::error_code ec;
        std::filesystem::create_directories(parent, ec);
    }

    bool need_header = true;
    {
        std::ifstream in(cfg.csv_path, std::ios::binary | std::ios::ate);
        if (in.is_open() && in.tellg() > 0) need_header = false;
    }
    std::ofstream out(cfg.csv_path, std::ios::app);
    if (!out.is_open()) {
        std::fprintf(stderr, "append_csv: cannot open '%s'; row follows\n%s\n",
                     cfg.csv_path.c_str(), csv_row(cfg).c_str());
        return false;
    }
    if (need_header) out << csv_header() << '\n';
    out << csv_row(cfg) << '\n';
    out.flush();
    return out.good();
}

} // namespace bfx
