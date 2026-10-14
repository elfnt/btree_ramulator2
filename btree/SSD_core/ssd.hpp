#pragma once
#include "block.hpp"
//log-structured FTL
class SSD{
private:
    //std::map<uint32_t, physical_address> map_;
    ssd_config config_;
    
    std::vector<physical_address> l2p_;
    std::vector<block> block_pool_;
    std::vector<uint32_t> block_valid_page_count_;

    //empty blocks the host may never take, so GC always has somewhere to relocate into
    static constexpr uint32_t RESERVED_BLOCKS = 1;
    //GC does nothing while more than this many blocks are still free
    static constexpr uint32_t GC_HIGH_WATERMARK = RESERVED_BLOCKS + 1;
    static constexpr uint32_t INVALID_BLOCK = UINT32_MAX;

    //the two open blocks. host data is hot, GC-relocated data is cold:
    //keeping them apart also keeps write amplification down
    //INVARIANT: host_front_ != gc_front_ at all times
    uint32_t host_front_;
    uint32_t gc_front_;
    uint32_t GC_victim_;
    uint32_t mapped_count_;

    //ssd_status GC();
    void invalidate(physical_address pa);
    //erase a block
    void erase_block(uint32_t bid);
    
    bool is_valid(physical_address pa) const;
    bool valid_LA(uint32_t LA) const;
    //recyclable page count of a block, O(1)
    //derived index for victim ranking only, never for validity decisions
    uint32_t stale_count(uint32_t bid) const;
    //empty blocks that could become a new frontier (both current frontiers excluded)
    uint32_t free_block_count() const;
    //allocate the next writable pa on a frontier, advancing it to a fresh block if full
    //is_host == true is refused once only RESERVED_BLOCKS empty blocks are left
    ssd_status alloc_from(uint32_t& frontier, bool is_host, physical_address& out);
    //the single place l2p_ is updated on a write. does NOT invalidate the old
    //location: host write and relocate retire it at different moments
    ssd_status program_and_map(physical_address pa, uint32_t LA, const std::vector<uint8_t>& content);
    //RULE: move_page() and write() must never call each other, and both go
    //through alloc_from + program_and_map only. calling write() from here (or
    //adding a "GC first if full" line to write()) reintroduces infinite recursion
    ssd_status move_page(physical_address src);
    
public:
    explicit SSD(ssd_config config);
    SSD(const SSD&) = delete;
    SSD& operator=(const SSD&) = delete;
    SSD(SSD&&) noexcept = default;
    SSD& operator=(SSD&&) noexcept = default;

    void show_config();
    void show_page_in_block(uint32_t block_id);
    void show_mapping_table();

    //write content to a LA
    ssd_status write(uint32_t LA, const std::vector<uint8_t>& content);
    
    //read content of a LA to output
    ssd_status read(uint32_t LA, std::vector<uint8_t>& output);
    
    //dead a LA
    ssd_status trim(uint32_t LA);


    
    //garbage collection algorithm
    ssd_status GC();

    //logical pages the host has not claimed yet (definition A: GC never moves this)
    uint32_t available_logical_pages() const;

    //assert that every derived index still agrees with the L2P table.
    //no-op under NDEBUG. called on both sides of GC()
    void check_invariants() const;

    //void run();
};