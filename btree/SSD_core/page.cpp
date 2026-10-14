#include "page.hpp"
#include "../tools/checksums.hpp"

page::page(uint32_t pageId, uint32_t page_size_bytes): 
           page_meta_{},
           page_header_{},
           page_data_{}
{

    if(page_size_bytes <= sizeof(header)) {
        throw std::invalid_argument("this page is too small\n");
    }
    page_meta_.pageId = pageId;
    page_meta_.access_cnt = 0;
    page_meta_.read_cnt = 0;
    page_meta_.write_cnt = 0;

    page_header_.CRC32 = 0;
    page_header_.version = 0;
    page_header_.page_size_bytes = page_size_bytes;
    page_header_.order = byte_order::litte_endian;
    //useful header size 
    page_meta_.data_size = static_cast<uint32_t>(page_header_.page_size_bytes - sizeof(header));    

    page_meta_.state = page_state::free;

    //full_page_(page_header_.page_size_bytes);
}

bool page::program(const uint32_t logical_page_id, const std::vector<uint8_t>& data){

    if(page_meta_.state != page_state::free) return false;

    if(data.size() != page_header_.page_size_bytes) return false;

    //data[0-15] -> header
    std::vector<uint8_t> header_vector;
    header h;
    for(size_t i = 0; i < 16; i++) header_vector.push_back(data[i]);

    h = v2h(header_vector);
    if(h.page_size_bytes != page_header_.page_size_bytes){
        return false;
    }

    page_header_ = h;
    //page_data_
    page_data_.clear();
    for(size_t i = 16; i < data.size(); i++) page_data_.push_back(data[i]);

    // Intentionally do not verify CRC here: a programmed page may contain a
    // corrupted image. verifyCRC() and read() report that corruption.
    page_meta_.pageId = logical_page_id;
    page_meta_.state = page_state::programmed;
    ++page_meta_.write_cnt;
    ++page_meta_.access_cnt;
    return true;
}

bool page::read(std::vector<uint8_t>& output){
    if(page_meta_.state != page_state::programmed) return false;
    
    output = header2Vector();
    for(auto it : page_data_) output.push_back(it);
    ++page_meta_.read_cnt;
    ++page_meta_.access_cnt;
    return true;
}

bool page::verifyCRC(){
    if(page_meta_.state != page_state::programmed) return false;
    if(page_data_.size() != page_meta_.data_size) return false;
    return page_header_.CRC32 == calculateCRC();
}


void page::setFree(){
    //printf("A\n");
    page_meta_.state = page_state::free;
    page_meta_.pageId = UINT32_MAX;
    //printf("B\n");
    return;
}

const header& page::getHeader() const{
    return page_header_;
}

const meta_data& page::getMetaData() const{
    return page_meta_;
}

const page_state& page::getPagestate() const{
    return page_meta_.state;
}

const std::vector<uint8_t>& page::getPagedata() const{
    return page_data_;
}

const std::vector<uint8_t> page::getFullPage(){
    std::vector<uint8_t> tmp = header2Vector();
    for(auto i : page_data_){
        tmp.push_back(i);
    }
    return tmp;
}

uint32_t page::calculateCRC(){
    //full page crc
    //1. {meta_data_ without crc , page_data_} -> calculate crc
    //2. {meta_data_ with crc, page_data_}
    header tmp = page_header_;
    tmp.CRC32 = 0;
    std::vector<uint8_t> page = h2v(tmp);
    for(auto it : page_data_) page.push_back(it);
    return pageCRC32(page);
}

std::vector<uint8_t> page::header2Vector(){
    return h2v(page_header_);
}


std::vector<uint8_t> h2v(header page_header){
    std::vector<uint8_t> r;
    std::vector<uint8_t> tmp;

    tmp = _32to8_(page_header.CRC32);
    for(auto i : tmp) r.push_back(i);
    tmp = _32to8_(page_header.page_size_bytes);
    for(auto i : tmp) r.push_back(i);
    tmp = _32to8_(page_header.version);
    for(auto i : tmp) r.push_back(i);
    if(page_header.order == byte_order::litte_endian) tmp = _32to8_((uint32_t)0);
    //else tmp = _32to8_((uint32_t)1);
    for(auto i : tmp) r.push_back(i);

    return r;
}

header v2h(const std::vector<uint8_t>& input){
    if(input.size() < 16) return header{};
    header h = {};
    std::vector<std::vector<uint8_t>> tmp(4);
    for(size_t i = 0; i < 4; i++){
        for(size_t j = 0; j < 4; j++){
            tmp[i].push_back(input[i*4 + j]);
        }
    }
    h.CRC32 = _8to32_(tmp[0]);
    h.page_size_bytes = _8to32_(tmp[1]);
    h.version = _8to32_(tmp[2]);
    h.order = static_cast<byte_order>(_8to32_(tmp[3]));
    return h;
}