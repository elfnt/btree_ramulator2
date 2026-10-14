#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <random>
#include <map>
#include <memory>
#include <vector>
#include <stdexcept>
#include <cstring>

std::vector<uint8_t> _32to8_(uint32_t input);
uint32_t _8to32_(const std::vector<uint8_t>& input);