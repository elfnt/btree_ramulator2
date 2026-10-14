#pragma once
#include "page.hpp"

struct physical_address{
    uint32_t blockId;
    uint32_t offset;

    bool operator==(const physical_address& rhs) const;
    bool operator!=(const physical_address& rhs) const;
};
inline constexpr physical_address INVALID_PA{UINT32_MAX, UINT32_MAX};
struct ssd_config{
    uint32_t max_block_count_;
    uint32_t pages_per_block_;
    uint32_t page_size_bytes_;
    //max logical id
    uint32_t logical_page_count_;
    //uint32_t initial_block_count_;    
};


enum class ssd_status : uint32_t{
    success,
    invalid_config,
    invalid_logical_page_id,
    invalid_physical_address,
    invalid_page_image,
    unmapped_page,
    no_free_page,
    max_block_count_reached,
    physical_slot_not_free,
    physical_slot_empty,
    block_not_erasable,
    internal_invariant_error,
    physical_page_invalid,
    no_need_to_gc
};

char* statusTostring(ssd_status s);

struct block_stats{
    uint32_t free_slots_cnt;
    uint32_t programmed_slots_cnt;
};

class block{
private:
    uint32_t block_id_;
    uint32_t page_size_bytes_;
    uint32_t capacity_;
    uint32_t next_offset_;
    //no nullptr usage
    std::vector<std::unique_ptr<page>> slots_;

public:
    block(const block&) = delete;
    block& operator=(const block&) = delete;
    block(block&&) noexcept = default;
    block& operator=(block&&) noexcept = default;
    
    block(uint32_t block_id,
          uint32_t capacity,
          uint32_t page_size_bytes);
          
    /*
    //nullptr iff offset over bound
    page* pageAt(uint32_t offset);
    //nullptr iff offset over bound
    const page* pageAt(uint32_t offset) const;

    bool isFree(uint32_t offset) const;
    //get an empty slot
    //offset is an output parameter
    ssd_status findFreeSlot(uint32_t& offset) const;
    */

    //program block[offset] as a logical page(id, data = image)
    ssd_status program(
        uint32_t offset,
        uint32_t logical_page_id,
        const std::vector<uint8_t>& image);

    //erase a block, set all pages to state::free
    //no extra check, be careful for future use
    ssd_status erase();

    //read block[offset]
    ssd_status read(uint32_t offset, std::vector<uint8_t>& output);
    
    //get page at block[offset]
    //nullptr iff over bound
    page* getPage(const uint32_t offset) const;
    
    ssd_status getFreeslot(uint32_t& offset) const;
    /*
    uint32_t id() const;
    uint32_t page_size_bytes() const;
    uint32_t capacity() const;*/

    block_stats stats() const;
    uint32_t freePageCount() const;
    uint32_t programmedPageCount() const;
    bool isFull() const;
    bool isEmpty() const;
};