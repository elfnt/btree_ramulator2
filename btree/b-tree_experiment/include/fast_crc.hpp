#pragma once
// fast_crc.hpp — 表驅動 CRC32（實驗層專用，namespace bfx）
// 與 v2 tools 的 pageCRC32 完全同語義：poly 0xEDB88320（reflected）、
// init 0xFFFFFFFF、final XOR 0xFFFFFFFF——只是把逐 bit 迴圈換成 256 項查表，
// 對任意輸入回傳值必須與 pageCRC32 位元相同（driver 啟動時自測驗證）。
#include <cstdint>
#include <vector>

namespace bfx {

uint32_t fast_crc32(const std::vector<uint8_t>& data);

} // namespace bfx
