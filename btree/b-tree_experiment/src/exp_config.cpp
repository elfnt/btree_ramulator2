// exp_config.cpp — 組態名稱表與 --key=value 解析
#include "exp_config.hpp"
#include <cctype>
#include <cstdio>
#include <stdexcept>

namespace bfx {

uint32_t scheme_entry_bytes(Scheme s) {
    switch (s) {
        case Scheme::HDR_CRC:    return 12;
        case Scheme::HDR_MIRROR: return 24;
        // CTRL_CRC 的 entry 內容 = 一個 uint32_t CRC（同 HDR_CRC/FULL_CRC），
        // 只有 CRC 的「涵蓋長度」隨節點變動，entry 本身大小固定。
        // （實作上另存 2 B 的 ctrl_len；此處沿用 12 B 讓 budget 軸與
        //   HDR_CRC/FULL_CRC 直接可比，差異已在 SUMMARY_dbscale.md 註明。）
        case Scheme::CTRL_CRC:   return 12;
        case Scheme::FULL_CRC:   return 12;
        case Scheme::HYBRID:     return 12;   // 只有 internal 頁會佔 entry
        case Scheme::INPAGE_CTRL:            // E16：CRC 存在頁內，不佔可靠記憶體
        case Scheme::INPAGE_FULL:
        case Scheme::NONE:
        case Scheme::SANITY:     return 0;
    }
    return 0;
}

const char* scheme_name(Scheme s) {
    switch (s) {
        case Scheme::NONE:       return "NONE";
        case Scheme::SANITY:     return "SANITY";
        case Scheme::HDR_CRC:    return "HDR_CRC";
        case Scheme::HDR_MIRROR: return "HDR_MIRROR";
        case Scheme::CTRL_CRC:   return "CTRL_CRC";
        case Scheme::FULL_CRC:   return "FULL_CRC";
        case Scheme::HYBRID:     return "HYBRID";
        case Scheme::INPAGE_CTRL: return "INPAGE_CTRL";
        case Scheme::INPAGE_FULL: return "INPAGE_FULL";
    }
    return "?";
}

const char* policy_name(Policy p) {
    switch (p) {
        case Policy::BY_LEVEL:   return "BY_LEVEL";
        case Policy::BY_HOTNESS: return "BY_HOTNESS";
        case Policy::LRU:        return "LRU";
        case Policy::RANDOM:     return "RANDOM";
    }
    return "?";
}

const char* verify_mode_name(VerifyMode m) {
    switch (m) {
        case VerifyMode::EVERY_READ: return "EVERY_READ";
        case VerifyMode::PERIODIC:   return "PERIODIC";
    }
    return "?";
}

const char* key_dist_name(KeyDist d) {
    switch (d) {
        case KeyDist::STRIDE:    return "stride";
        case KeyDist::RANDOM64:  return "random64";
        case KeyDist::GEOMGAP:   return "geomgap";
        case KeyDist::CLUSTERED: return "clustered";
    }
    return "?";
}

const char* key_map_name(KeyMap m) {   // E21
    switch (m) {
        case KeyMap::NONE:      return "none";
        case KeyMap::SHIFT:     return "shift";
        case KeyMap::HASHDENSE: return "hashdense";
    }
    return "?";
}

const char* guard_mode_name(GuardMode g) {
    switch (g) {
        case GuardMode::NONE:  return "none";
        case GuardMode::RIGHT: return "right";
        case GuardMode::LEFT:  return "left";
        case GuardMode::BOTH:  return "both";
        case GuardMode::MID:   return "mid";
        case GuardMode::GRID:  return "grid";
    }
    return "?";
}

const char* slack_guard_name(SlackGuard g) {
    switch (g) {
        case SlackGuard::NONE:  return "none";
        case SlackGuard::RIGHT: return "right";
        case SlackGuard::BOTH:  return "both";
    }
    return "?";
}

const char* inject_level_name(InjectLevel l) {
    switch (l) {
        case InjectLevel::ALL:      return "all";
        case InjectLevel::INTERNAL: return "internal";
        case InjectLevel::LEAF:     return "leaf";
    }
    return "?";
}

namespace {

std::string upper(std::string s) {
    for (char& c : s) c = (char)std::toupper((unsigned char)c);
    return s;
}

bool parse_scheme(const std::string& v, Scheme& out) {
    const std::string u = upper(v);
    if      (u == "NONE")       out = Scheme::NONE;
    else if (u == "SANITY")     out = Scheme::SANITY;
    else if (u == "HDR_CRC")    out = Scheme::HDR_CRC;
    else if (u == "HDR_MIRROR") out = Scheme::HDR_MIRROR;
    else if (u == "CTRL_CRC")   out = Scheme::CTRL_CRC;
    else if (u == "FULL_CRC")   out = Scheme::FULL_CRC;
    else if (u == "HYBRID")     out = Scheme::HYBRID;
    else if (u == "INPAGE_CTRL") out = Scheme::INPAGE_CTRL;
    else if (u == "INPAGE_FULL") out = Scheme::INPAGE_FULL;
    else return false;
    return true;
}

bool parse_policy(const std::string& v, Policy& out) {
    const std::string u = upper(v);
    if      (u == "BY_LEVEL")   out = Policy::BY_LEVEL;
    else if (u == "BY_HOTNESS") out = Policy::BY_HOTNESS;
    else if (u == "LRU")        out = Policy::LRU;
    else if (u == "RANDOM")     out = Policy::RANDOM;
    else return false;
    return true;
}

bool parse_verify_mode(const std::string& v, VerifyMode& out) {
    const std::string u = upper(v);
    if      (u == "EVERY_READ") out = VerifyMode::EVERY_READ;
    else if (u == "PERIODIC")   out = VerifyMode::PERIODIC;
    else return false;
    return true;
}

bool parse_key_dist(const std::string& v, KeyDist& out) {
    const std::string u = upper(v);
    if      (u == "STRIDE")    out = KeyDist::STRIDE;
    else if (u == "RANDOM64")  out = KeyDist::RANDOM64;
    else if (u == "GEOMGAP")   out = KeyDist::GEOMGAP;
    else if (u == "CLUSTERED") out = KeyDist::CLUSTERED;
    else return false;
    return true;
}

bool parse_inject_level(const std::string& v, InjectLevel& out) {
    const std::string u = upper(v);
    if      (u == "ALL")      out = InjectLevel::ALL;
    else if (u == "INTERNAL") out = InjectLevel::INTERNAL;
    else if (u == "LEAF")     out = InjectLevel::LEAF;
    else return false;
    return true;
}

bool parse_guard(const std::string& v, GuardMode& out) {
    const std::string u = upper(v);
    if      (u == "NONE")  out = GuardMode::NONE;
    else if (u == "RIGHT") out = GuardMode::RIGHT;
    else if (u == "LEFT")  out = GuardMode::LEFT;
    else if (u == "BOTH")  out = GuardMode::BOTH;
    else if (u == "MID")   out = GuardMode::MID;
    else if (u == "GRID")  out = GuardMode::GRID;
    else return false;
    return true;
}

bool parse_slack(const std::string& v, SlackGuard& out) {
    const std::string u = upper(v);
    if      (u == "NONE")  out = SlackGuard::NONE;
    else if (u == "RIGHT") out = SlackGuard::RIGHT;
    else if (u == "BOTH")  out = SlackGuard::BOTH;
    else return false;
    return true;
}

bool parse_key_map(const std::string& v, KeyMap& out) {   // E21
    const std::string u = upper(v);
    if      (u == "NONE")      out = KeyMap::NONE;
    else if (u == "SHIFT")     out = KeyMap::SHIFT;
    else if (u == "HASHDENSE") out = KeyMap::HASHDENSE;
    else return false;
    return true;
}

bool parse_bool01(const std::string& v, bool& out) {
    if (v == "0") { out = false; return true; }
    if (v == "1") { out = true;  return true; }
    return false;
}

} // namespace

bool ExpConfig::parse_args(int argc, char** argv) {
    for (int i = 1; i < argc; ++i) {
        const std::string arg = argv[i];
        const size_t eq = arg.find('=');
        if (arg.rfind("--", 0) != 0 || eq == std::string::npos || eq <= 2) {
            std::fprintf(stderr, "parse_args: expected --key=value, got '%s'\n", arg.c_str());
            return false;
        }
        const std::string key = arg.substr(2, eq - 2);
        const std::string val = arg.substr(eq + 1);
        bool ok = true;
        try {
            if      (key == "ssd_blocks")        ssd_blocks        = (uint32_t)std::stoul(val);
            else if (key == "pages_per_block")   pages_per_block   = (uint32_t)std::stoul(val);
            else if (key == "page_size")         page_size         = (uint32_t)std::stoul(val);
            else if (key == "ram_rows_per_bank") ram_rows_per_bank = (uint32_t)std::stoul(val);
            else if (key == "scheme")            ok = parse_scheme(val, scheme);
            else if (key == "sanity_always")     ok = parse_bool01(val, sanity_always);
            else if (key == "policy")            ok = parse_policy(val, policy);
            else if (key == "budget_bytes") {
                if (upper(val) == "INF") budget_bytes = UINT64_MAX;
                else                     budget_bytes = (uint64_t)std::stoull(val);
            }
            else if (key == "verify_mode")       ok = parse_verify_mode(val, verify_mode);
            else if (key == "theta_s")           theta_s           = std::stod(val);
            else if (key == "lambda_page" || key == "lambda")
                                                 lambda_page       = std::stod(val);
            else if (key == "hammer_rate_per_s") hammer_rate_per_s = std::stod(val);
            else if (key == "hammer_flip_ratio") hammer_flip_ratio = std::stod(val);
            else if (key == "colfault_time_s")   colfault_time_s   = std::stod(val);
            else if (key == "colfault_bank")     colfault_bank     = (uint32_t)std::stoul(val);
            else if (key == "colfault_byte")     colfault_byte     = (uint32_t)std::stoul(val);
            else if (key == "colfault_bit")      colfault_bit      = (uint8_t)std::stoul(val);
            else if (key == "colfault_rows")     colfault_rows     = (uint32_t)std::stoul(val);
            else if (key == "order")             order             = (uint32_t)std::stoul(val);
            else if (key == "prefill_keys")      prefill_keys      = (uint32_t)std::stoul(val);
            else if (key == "key_stride_log2")   key_stride_log2   = (uint32_t)std::stoul(val);
            else if (key == "key_dist")          ok = parse_key_dist(val, key_dist);
            else if (key == "inject_level")      ok = parse_inject_level(val, inject_level);
            else if (key == "guard")             ok = parse_guard(val, guard);
            else if (key == "key_map")           ok = parse_key_map(val, key_map);   // E21
            else if (key == "map_load")          map_load          = std::stod(val); // E21
            else if (key == "guard_grid_log2")   guard_grid_log2   = (uint32_t)std::stoul(val);
            else if (key == "sanity_range")      ok = parse_bool01(val, sanity_range);
            else if (key == "sanity_align_log2") sanity_align_log2 = (uint32_t)std::stoul(val);
            else if (key == "slack_guard")       ok = parse_slack(val, slack_guard);
            else if (key == "n_ops")             n_ops             = (uint32_t)std::stoul(val);
            else if (key == "read_ratio")        read_ratio        = std::stod(val);
            else if (key == "miss_ratio")        miss_ratio        = std::stod(val);
            else if (key == "dt_op_s")           dt_op_s           = std::stod(val);
            else if (key == "t_mem_s")           t_mem_s           = std::stod(val);
            else if (key == "t_ssd_s")           t_ssd_s           = std::stod(val);
            else if (key == "t_reliable_s")      t_reliable_s      = std::stod(val);
            else if (key == "t_crc_per_byte_s")  t_crc_per_byte_s  = std::stod(val);
            else if (key == "t_sanity_s")        t_sanity_s        = std::stod(val);
            else if (key == "seed")              seed              = (uint32_t)std::stoul(val);
            else if (key == "backend")           backend           = val;
            else if (key == "r2_config")         r2_config_path    = val;
            else if (key == "r2_ecc")            ok = parse_bool01(val, r2_ecc);
            else if (key == "r2_ttl_s")          r2_ttl_s          = std::stod(val);
            else if (key == "run_id")            run_id            = val;
            else if (key == "csv_path" || key == "csv")
                                                 csv_path          = val;
            else {
                std::fprintf(stderr, "parse_args: unknown key '%s'\n", key.c_str());
                return false;
            }
        } catch (const std::exception&) {
            ok = false;
        }
        if (!ok) {
            std::fprintf(stderr, "parse_args: bad value for '%s': '%s'\n",
                         key.c_str(), val.c_str());
            return false;
        }
    }
    return true;
}

} // namespace bfx
