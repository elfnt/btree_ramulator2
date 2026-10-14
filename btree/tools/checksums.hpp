#pragma once
#include "../utility.hpp"

//create full page crc32
uint32_t pageCRC32(const std::vector<uint8_t>& data);

uint32_t pageCRC32_C(const std::vector<uint8_t>& data);