#include "ssd.hpp"
#include <cassert>

// ── 逐次操作的追蹤輸出 ───────────────────────────────────────────────────────
//
// SSD::read / SSD::write 原本每次呼叫都會列印一行（read 成功那行走的是 stderr，
// 因此連 freopen(stdout) 也攔不掉）。這在 ttl_theta_experiment 是嚴重問題：
// TTL 逐出會刻意製造大量 SSD 重載，每次重載付一次 I/O syscall，
// 既洗掉終端機訊息，也讓 wall-time 被 I/O 主導而非模擬本身。
//
// 因此改為預設關閉。要拿回這些訊息就加 -DSSD_TRACE 重新建置。
// 失敗路徑（invalid_page_image / invalid_logical_page_id / invariant error）
// 一律保留，不受此開關影響。
#ifdef SSD_TRACE
  #define SSD_TRACE_OUT(...)  printf(__VA_ARGS__)
  #define SSD_TRACE_ERR(...)  fprintf(stderr, __VA_ARGS__)
#else
  #define SSD_TRACE_OUT(...)  ((void)0)
  #define SSD_TRACE_ERR(...)  ((void)0)
#endif

SSD::SSD(ssd_config config) : config_(config){
    if(config_.max_block_count_ == 0){
        throw std::invalid_argument("#block should be more than 0\n");
    }
    if(config_.logical_page_count_ == 0){
        throw std::invalid_argument("#logical page should be more than 0\n");

    }
    //2 frontiers + at least 1 victim candidate, on top of the GC reserve
    if(config_.max_block_count_ < 3 + RESERVED_BLOCKS){
        throw std::invalid_argument("#block is too small to run GC\n");
    }
    block_pool_.reserve(config_.max_block_count_);
    for(size_t i = 0; i < config_.max_block_count_; i++){
        block_pool_.emplace_back(block(i, config_.pages_per_block_, config_.page_size_bytes_));
    }
    //two distinct empty blocks, kept far apart
    host_front_ = 0;
    gc_front_ = config_.max_block_count_ - 1;
    GC_victim_ = 0xffffffff;
    l2p_.assign(config_.logical_page_count_, INVALID_PA);
    block_valid_page_count_.assign(config_.max_block_count_, 0);
    mapped_count_ = 0;
}

void SSD::invalidate(physical_address pa){
    if(block_valid_page_count_[pa.blockId] > 0){
        --block_valid_page_count_[pa.blockId];
    }
}

bool SSD::is_valid(physical_address pa) const{
    page* p = block_pool_[pa.blockId].getPage(pa.offset);
    if(!p) return false;
    if(p->getPagestate() != page_state::programmed) return false;

    uint32_t LA = p->getMetaData().pageId;
    if(!valid_LA(LA)) return false;

    return l2p_[LA] == pa;
}

bool SSD::valid_LA(uint32_t LA) const{
    return LA < config_.logical_page_count_;
}

uint32_t SSD::stale_count(uint32_t bid) const{
    //monotonic write pointer: programmedPageCount() == #pages ever written
    return block_pool_[bid].programmedPageCount() - block_valid_page_count_[bid];
}

uint32_t SSD::free_block_count() const{
    //counts exactly what alloc_from's block search can find, so
    //free_block_count() == 0 iff that search fails
    uint32_t cnt = 0;
    for(uint32_t b = 0; b < config_.max_block_count_; b++){
        if(b == host_front_ || b == gc_front_) continue;
        if(block_pool_[b].isEmpty()) ++cnt;
    }
    return cnt;
}

uint32_t SSD::available_logical_pages() const{
    return config_.logical_page_count_ - mapped_count_;
}

ssd_status SSD::alloc_from(uint32_t& frontier, bool is_host, physical_address& out){
    if(frontier >= config_.max_block_count_){
        return ssd_status::internal_invariant_error;
    }
    uint32_t offset;
    ssd_status s = block_pool_[frontier].getFreeslot(offset);
    //the open block still has room: no new block is consumed
    if(s == ssd_status::success){
        out = {frontier, offset};
        return s;
    }
    //only "full" is recoverable here, anything else is a real fault
    if(s != ssd_status::no_free_page){
        return s;
    }

    //from here on a fresh block is needed
    //the host must leave RESERVED_BLOCKS behind, or GC ends up with
    //nowhere to relocate to and neither side can make progress
    if(is_host && free_block_count() <= RESERVED_BLOCKS){
        return ssd_status::no_free_page;
    }
    const uint32_t other = is_host ? gc_front_ : host_front_;
    for(uint32_t b = 0; b < config_.max_block_count_; b++){
        //never steal the other frontier: the two must stay distinct
        if(b == other) continue;
        if(!block_pool_[b].isEmpty()) continue;

        s = block_pool_[b].getFreeslot(offset);
        if(s != ssd_status::success){
            return ssd_status::internal_invariant_error;
        }
        frontier = b;
        out = {frontier, offset};
        return ssd_status::success;
    }
    return ssd_status::no_free_page;
}

void SSD::show_config(){
    printf("SSD config:\n%u blocks\n%u pages per block\n%u bytes per page\n", config_.max_block_count_, config_.pages_per_block_, config_.page_size_bytes_);
}

void SSD::show_page_in_block(uint32_t block_id){
    if(block_id >= config_.max_block_count_){
        printf("out-of-bound\n");
        return;
    }
    //all three come from the SSD layer now: block only knows free vs programmed
    printf("Block %u stats: \n\t%u free pages\n\t%u invalid pages\n\t%u valid pages\n------------------------------------------------\n",
            block_id,
            config_.pages_per_block_ - block_pool_[block_id].programmedPageCount(),
            stale_count(block_id),
            block_valid_page_count_[block_id]
    );
    printf("page_id ");
    for(uint32_t i = 0; i < config_.pages_per_block_; i++){
        printf("%u\t", i);
    }
    printf("\n");
    printf("content\t");
    for(uint32_t i = 0; i < config_.pages_per_block_; i++){
        const page* p = block_pool_[block_id].getPage(i);
        if(p->getPagestate() == page_state::free || p->getPagedata().empty()){
            printf("_\t");
        }else{
            printf("%u\t", p->getPagedata().back());
        }
    }
    printf("\n");
    printf("states \t");
    for(uint32_t i = 0; i < config_.pages_per_block_; i++){
        //V vs I is decided purely by the mapping table, never by the page itself
        if(block_pool_[block_id].getPage(i)->getPagestate() == page_state::free){
            printf("F\t");
        }else if(is_valid(physical_address{block_id, i})){
            printf("V\t");
        }else{
            printf("I\t");
        }
    }
    printf("\n");
    //which LA each page claims to belong to: cross-check this against SMT
    printf("LA     \t");
    for(uint32_t i = 0; i < config_.pages_per_block_; i++){
        const page* p = block_pool_[block_id].getPage(i);
        if(p->getPagestate() == page_state::free){
            printf("_\t");
        }else{
            printf("%u\t", p->getMetaData().pageId);
        }
    }
    printf("\n");
}

void SSD::show_mapping_table(){
    printf("Mapping table: \n");
    bool empty = true;
    for(size_t i = 0; i < l2p_.size(); i++){
        if(l2p_[i] != INVALID_PA){
            empty = false;
            printf("%lu -> {%u, %u}\t", i, l2p_[i].blockId, l2p_[i].offset);
        }
    }
    if(empty){
        printf("empty");
    }
    printf("\n");
}

ssd_status SSD::write(uint32_t LA, const std::vector<uint8_t>& content){
    SSD_TRACE_OUT("SSD::write LA = %u\n", LA);
    if(!valid_LA(LA)){
        return ssd_status::invalid_logical_page_id;
    }
    if(content.size() != config_.page_size_bytes_){
        fprintf(stderr, "SSD::write(logical addr = %u) failed: invalid_page_image\n", LA);
        return ssd_status::invalid_page_image;
    }
    physical_address pa;
    ssd_status s = alloc_from(host_front_, true, pa);
    if(s != ssd_status::success){
        return s;
    }
    physical_address old_pa = l2p_[LA];
    bool isNew = old_pa == INVALID_PA;
    //    l2p_[LA] is updated
    s = program_and_map(pa, LA, content);
    if(s != ssd_status::success){
        return s;
    }
    if(!isNew){
        invalidate(old_pa);
    }else{
        ++mapped_count_;
    }
    return s;
}

ssd_status SSD::read(uint32_t LA, std::vector<uint8_t>& output){
    SSD_TRACE_OUT("SSD::read LA = %u\n", LA);
    if(!valid_LA(LA)){
        return ssd_status::invalid_logical_page_id;
    }
    if(l2p_[LA] == INVALID_PA){
        fprintf(stderr, "SSD::read(logical addr = %u) failed: invalid_logical_page_id\n", LA);
        return ssd_status::invalid_logical_page_id;
    }
    physical_address pa = l2p_[LA];
    if(block_pool_[pa.blockId].getPage(pa.offset)->getMetaData().state != page_state::programmed){
        fprintf(stderr, "SSD::read(logical addr = %u) failed: physical_page_invalid\n", LA);
        return ssd_status::physical_page_invalid;
    }
    if(block_pool_[pa.blockId].getPage(pa.offset)->read(output)){
        SSD_TRACE_ERR("SSD::read(logical addr = %u) success\n", LA);
        return ssd_status::success;
    }
    fprintf(stderr, "SSD::read(logical addr = %u) failed: internal_invariant_error\n", LA);
    return ssd_status::internal_invariant_error;
}

ssd_status SSD::trim(uint32_t LA){
    if(!valid_LA(LA)){
        return ssd_status::invalid_logical_page_id;
    }
    if(l2p_[LA] == INVALID_PA){
        return ssd_status::invalid_logical_page_id;
    }
    invalidate(l2p_[LA]);
    l2p_[LA] = INVALID_PA;
    --mapped_count_;
    return ssd_status::success;
}

void SSD::erase_block(uint32_t bid){
    block_pool_[bid].erase();
    //the easiest line in the whole refactor to forget: without it the counter
    //stays high forever and stale_count() underflows on the next write
    block_valid_page_count_[bid] = 0;
}

ssd_status SSD::program_and_map(physical_address pa, uint32_t LA, const std::vector<uint8_t> &content){
    ssd_status s = block_pool_[pa.blockId].program(pa.offset, LA, content);
    if(s != ssd_status::success) return s;

    l2p_[LA] = pa;
    ++block_valid_page_count_[pa.blockId];
    return s;
}

ssd_status SSD::move_page(physical_address src){
    page* p = block_pool_[src.blockId].getPage(src.offset);
    if(!p){
        return ssd_status::invalid_physical_address;
    }
    if(!is_valid(src)){
        return ssd_status::success;
    }

    uint32_t LA = p->getMetaData().pageId;
    physical_address dest;
    ssd_status s = alloc_from(gc_front_, false, dest);
    if(s != ssd_status::success){
        return s;
    }
    s = program_and_map(dest, LA, p->getFullPage());
    if(s != ssd_status::success){
        return s;
    }
    invalidate(src);
    return s;
}

ssd_status SSD::GC(){
    //physical pressure, not logical capacity: a full disk that is overwritten
    //forever still has plenty of available_logical_pages()
    if(free_block_count() > GC_HIGH_WATERMARK){
        return ssd_status::no_need_to_gc;
    }
    check_invariants();

    //greedy victim: most stale pages wins. O(blocks), no l2p_ lookup at all
    uint32_t best = INVALID_BLOCK;
    uint32_t best_stale = 0;
    for(uint32_t b = 0; b < config_.max_block_count_; b++){
        //erasing an open block would throw away the frontier we are writing to
        if(b == host_front_ || b == gc_front_) continue;
        //nothing to reclaim in a block that was never written
        if(block_pool_[b].isEmpty()) continue;

        uint32_t st = stale_count(b);
        if(st > best_stale){
            best_stale = st;
            best = b;
        }
    }
    //best_stale == 0 means every block is fully valid: relocating frees nothing,
    //so GC must give up and let the next host write report no_free_page
    if(best == INVALID_BLOCK || best_stale == 0){
        return ssd_status::no_need_to_gc;
    }
    GC_victim_ = best;
    SSD_TRACE_OUT("SSD::GC victim = block %u (%u stale / %u programmed)\n",
           GC_victim_, best_stale, block_pool_[GC_victim_].programmedPageCount());

    ssd_status s;
    for(uint32_t i = 0; i < config_.pages_per_block_; i++){
        //is_valid is checked inside move_page, do not duplicate it here
        s = move_page(physical_address{GC_victim_, i});
        if(s != ssd_status::success){
            return s;
        }
    }
    erase_block(GC_victim_);
    check_invariants();
    return ssd_status::success;
}

void SSD::check_invariants() const{
#ifndef NDEBUG
    //(a) forward consistency: every mapped LA points at a programmed page
    //    that claims that same LA back
    for(uint32_t LA = 0; LA < config_.logical_page_count_; LA++){
        if(l2p_[LA] == INVALID_PA) continue;
        physical_address pa = l2p_[LA];
        assert(pa.blockId < config_.max_block_count_);
        const page* p = block_pool_[pa.blockId].getPage(pa.offset);
        assert(p && p->getMetaData().state == page_state::programmed);
        assert(p->getMetaData().pageId == LA);
    }
    //(b) the derived index has not drifted from the single source of truth
    for(uint32_t b = 0; b < config_.max_block_count_; b++){
        uint32_t actual = 0;
        for(uint32_t off = 0; off < config_.pages_per_block_; off++){
            if(is_valid(physical_address{b, off})) ++actual;
        }
        assert(actual == block_valid_page_count_[b]);
        assert(block_valid_page_count_[b] <= block_pool_[b].programmedPageCount());
    }
    //(c) the two write frontiers never collapse onto one block
    assert(host_front_ != gc_front_);

    //(d) capacity accounting has not drifted (definition A)
    uint32_t mapped = 0;
    for(uint32_t LA = 0; LA < config_.logical_page_count_; LA++){
        if(l2p_[LA] != INVALID_PA) ++mapped;
    }
    assert(mapped == mapped_count_);
#endif
}

/*
void SSD::run(){
    using data = std::vector<uint8_t>;
    data d;
    data output;

    FILE* fp = fopen("../log.txt", "w+");
    if(!fp){
        printf("fopen failed\n");
        return 0;
    }
    header h1;
        h1.CRC32 = 0;
        h1.order = byte_order::litte_endian;
        h1.page_size_bytes = config_.page_size_bytes_;
        h1.version = 0;

    show_config();
    ssd_status s;
    char cmd[25];
    uint32_t LA;
    int seed_seed = 67;
    int cnt = 0;
    //uint8_t c;
    while(scanf("%s", &cmd) != EOF){
        //uint32_t LA;
        //uint8_t c;
        if(strcmp("write", cmd) == 0){
            scanf("%u", &LA);
            d = h2v(h1);
            d.push_back(data_generator(config_.page_size_bytes_ - sizeof(header), (cnt + LA) * seed_seed)[0]);
            s = write(LA, d);
            if(s == ssd_status::success) fprintf(fp, "write %u as %u\n", LA, d.back());
            seed_seed << 1;
        }else if(strcmp("SMT", cmd) == 0){
            show_mapping_table();
            seed_seed--;
        }else if(strcmp("SBS", cmd) == 0){
            uint32_t bid;
            scanf("%u", &bid);
            show_page_in_block(bid);
            seed_seed--;
        }else if(strcmp("read", cmd) == 0){
            scanf("%u", &LA);
            printf("LA = %u\n", LA);
            s = read(LA, output);
            if(s == ssd_status::success) fprintf(fp, "read %u as %u\n", LA, output.back());
            seed_seed--;
        }
        cnt++;
    }
    for(size_t i = 0; i < config_.max_block_count_; i++){
        show_page_in_block(i);
        printf("\n");
    }
    fclose(fp);
    return;
}
*/