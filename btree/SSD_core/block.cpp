#include "block.hpp"

// 與 ssd.cpp 相同的追蹤開關：預設關閉，加 -DSSD_TRACE 可拿回
#ifdef SSD_TRACE
  #define SSD_TRACE_OUT(...)  printf(__VA_ARGS__)
#else
  #define SSD_TRACE_OUT(...)  ((void)0)
#endif

block::block(uint32_t block_id, uint32_t capacity, uint32_t page_size_bytes):
            block_id_(block_id),
            page_size_bytes_(page_size_bytes),
            capacity_(capacity)
{
    SSD_TRACE_OUT("block %u construct\n", block_id_);
    if(capacity == 0){
        throw std::invalid_argument("capacity should not be 0\n");
    }
    if(page_size_bytes <= sizeof(header)) {
        throw std::invalid_argument("the page is too small\n");
    }
    slots_.resize(capacity_);
    //printf("slots_.size() = %u\n", slots_.size());
    for(size_t i = 0; i < capacity_; i++){
        //printf("%u ", i);
        auto new_page = std::make_unique<page>(4294967295, page_size_bytes_);
        //printf("a");
        slots_[i] = std::move(new_page);
        //printf("b\n");
    }
    next_offset_ = 0;
}
/*
page *block::pageAt(uint32_t offset){
    if(offset >= capacity_){
        return nullptr;
    }
    return slots_[offset].get();
}

const page *block::pageAt(uint32_t offset) const{
    if(offset >= capacity_){
        return nullptr;
    }
    return slots_[offset].get();
}

bool block::isFree(uint32_t offset) const{
    if(offset >= capacity_){
        return false;
    }
    return slots_[offset].get()->getMetaData().state == page_state::free;
}

ssd_status block::findFreeSlot(uint32_t &offset) const{
    if(next_free_offset_ >= capacity_){
        return ssd_status::no_free_page;
    }
    if(isFree(next_free_offset_)){
        offset = next_free_offset_;
        return ssd_status::success;
    }
    return ssd_status::internal_invariant_error;
}
*/

ssd_status block::program(uint32_t offset, uint32_t logical_page_id, const std::vector<uint8_t> &image){
    //printf("block::program LA = %u\n", logical_page_id);
    if(offset >= capacity_){
        //fprintf(stderr, "block::program(offset = %u, logical_page_id = %u) failed: invalid_physical_address\n", offset, logical_page_id);
        return ssd_status::invalid_physical_address;
    }
    if(image.size() != page_size_bytes_){
        //fprintf(stderr, "block::program(offset = %u, logical_page_id = %u) failed: invalid_page_image\n", offset, logical_page_id);
        return ssd_status::invalid_page_image;
    }
    //auto new_page = std::make_unique<page>(logical_page_id, page_size_bytes_);
    //printf("\tpage::program\n");
    if(!slots_[offset].get()->program(logical_page_id, image)){
        //fprintf(stderr, "block::program(offset = %u, logical_page_id = %u) failed: invalid_page_image\n", offset, logical_page_id);
        return ssd_status::invalid_page_image;
    }
    //slots_[offset] = std::move(new_page);
    ++next_offset_;
    //fprintf(stderr, "block::program(offset = %u, logical_page_id = %u) success\n", offset, logical_page_id);
    return ssd_status::success;
}



ssd_status block::erase(){
    for(size_t i = 0; i < capacity_; i++){
        slots_[i].get()->setFree();
    }
    next_offset_ = 0;
    
    return ssd_status::success;
}

ssd_status block::read(uint32_t offset, std::vector<uint8_t>& output){
    if(offset >= capacity_){
        return ssd_status::invalid_physical_address;
    }
    if(slots_[offset].get()->getMetaData().state != page_state::programmed){
        return ssd_status::physical_page_invalid;
    }

    if(slots_[offset].get()->read(output)){
        return ssd_status::success;
    }
    return ssd_status::physical_page_invalid;
}

page* block::getPage(const uint32_t offset) const{
    if(offset >= capacity_){
        return nullptr;
    }
    return slots_[offset].get();
}

ssd_status block::getFreeslot(uint32_t& offset) const{
    //printf("block::getFreeslot\n");
    if(next_offset_ >= capacity_){
        return ssd_status::no_free_page;
    }
    offset = next_offset_;
    return ssd_status::success;
}

/*
uint32_t block::id() const{
    return block_id_;
}

uint32_t block::page_size_bytes() const{
    return page_size_bytes_;
}

uint32_t block::capacity() const{
    return capacity_;
}*/

block_stats block::stats() const{
    block_stats b{0, 0};
    for(size_t i = 0; i < capacity_; i++){
        //valid vs invalid is an FTL-layer distinction, the block cannot answer it
        if(slots_[i].get()->getMetaData().state == page_state::free) ++b.free_slots_cnt;
        else ++b.programmed_slots_cnt;
    }
    if(b.free_slots_cnt + b.programmed_slots_cnt == capacity_)
        return b;
    return block_stats();
}

uint32_t block::freePageCount() const{
    return stats().free_slots_cnt;
}

uint32_t block::programmedPageCount() const{
    return next_offset_;
}

bool block::isFull() const{
    return next_offset_ >= capacity_;
}

bool block::isEmpty() const{
    return next_offset_ == 0;
}

char* statusTostring(ssd_status s){
    switch (s)
    {
    case ssd_status::success :
        return "success\0";
        break;
    case ssd_status::block_not_erasable :
        return "block_not_erasable\0";
        break;
    case ssd_status::internal_invariant_error : 
        return "internal_invariant_error\0";
        break;
    case ssd_status::invalid_config : 
        return "invalid_config\0";
        break;
    case ssd_status::invalid_logical_page_id : 
        return "invalid_logical_page_id\0";
        break;
    case ssd_status::invalid_page_image : 
        return "invalid_page_image\0";
        break;
    case ssd_status::invalid_physical_address : 
        return "invalid_physical_address\0";
        break;
    case ssd_status::max_block_count_reached : 
        return "max_block_count_reached\0";
        break;
    case ssd_status::no_free_page : 
        return "no_free_page\0";
        break;
    case ssd_status::physical_page_invalid : 
        return "physical_page_invalid\0";
        break;
    case ssd_status::physical_slot_empty : 
        return "physical_slot_empty\0";
        break;
    case ssd_status::physical_slot_not_free : 
        return "physical_slot_not_free\0";
        break;
    case ssd_status::unmapped_page : 
        return "unmapped_page\0";
        break;
    case ssd_status::no_need_to_gc :
        return "no_need_to_gc\0";
        break;
    default:
        return "\0";
        break;
    }
}

bool physical_address::operator==(const physical_address &rhs) const{
    return this->blockId == rhs.blockId && this->offset == rhs.offset;
}

bool physical_address::operator!=(const physical_address &rhs) const{
    return this->blockId != rhs.blockId || this->offset != rhs.offset;
}
