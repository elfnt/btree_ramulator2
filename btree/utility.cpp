#include "utility.hpp"

std::vector<uint8_t>_32to8_(uint32_t input){
    uint32_t mask = 0x000000FF;
    std::vector<uint8_t> r;
    for(auto byte = 0; byte < 4; byte++){
        r.push_back((input >> (byte*8)) & mask);
    }
    return r;
}

uint32_t _8to32_(const std::vector<uint8_t>& input){
    uint32_t word = 0x00000000;
    for(auto byte = 0; byte < 4; byte++){
        word |= static_cast<uint32_t>(input[byte]) << (byte*8);
    }
    return word;
}