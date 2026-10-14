#include "random_func.hpp"
#include "checksums.hpp"

const std::vector<uint8_t> data_generator(uint32_t bytes, int seed){
    std::mt19937 gen(seed);
    std::uniform_int_distribution<> dis(0, 255);
    std::vector<uint8_t> data;
    for(uint32_t i = 0; i < bytes; i++){
        data.push_back(dis(gen));
    }
    return data;
}

uint32_t pageCRC32(const std::vector<uint8_t>& data){
    size_t length = data.size();
    uint32_t poly = 0xEDB88320; //bitwise reverse of 0x04C11DB7
    uint32_t r = 0xFFFFFFFF;
    for(size_t i = 0; i < length; i++){
   	    r ^= (uint8_t)data[i]; // must be zero extended
	    for(size_t bit = 0; bit < 8; bit++)
	        if(r & 0x01)
  		        r = (r >> 1) ^ poly;
	        else
  		        r >>= 1;
        }
    return r ^ 0xFFFFFFFF;
}

uint32_t pageCRC32_C(const std::vector<uint8_t>& data){
    size_t length = data.size();
    uint32_t poly = 0x82F63B78; // bitwise reverse of 0x1EDC6F41
    uint32_t r = 0xFFFFFFFF;
    for(size_t i = 0; i < length; i++){
   	    r ^= (uint8_t)data[i]; // must be zero extended
	    for(size_t bit = 0; bit < 8; bit++)
	        if(r & 0x01)
  		        r = (r >> 1) ^ poly;
	        else
  		        r >>= 1;
        }
    return r ^ 0xFFFFFFFF;
}