// fast_crc.cpp — 表驅動 CRC32，語義同 v2 tools 的 pageCRC32（見 fast_crc.hpp）
#include "fast_crc.hpp"

namespace bfx {

namespace {

// 256 項查表：table[b] = 以逐 bit 法處理單一 byte b 的結果
struct Crc32Table {
    uint32_t t[256];
    Crc32Table() {
        constexpr uint32_t poly = 0xEDB88320u;  // 0x04C11DB7 的位元反轉
        for (uint32_t b = 0; b < 256; ++b) {
            uint32_t r = b;
            for (int bit = 0; bit < 8; ++bit)
                r = (r & 1u) ? (r >> 1) ^ poly : (r >> 1);
            t[b] = r;
        }
    }
};

const Crc32Table g_table;

} // namespace

uint32_t fast_crc32(const std::vector<uint8_t>& data) {
    uint32_t r = 0xFFFFFFFFu;
    for (uint8_t byte : data)
        r = (r >> 8) ^ g_table.t[(r ^ byte) & 0xFFu];
    return r ^ 0xFFFFFFFFu;
}

} // namespace bfx
