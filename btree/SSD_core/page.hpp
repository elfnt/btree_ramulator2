#pragma once
#include "../utility.hpp"
enum class page_state : uint32_t{
    free = 0,
    programmed,
    //invalid,
};

enum class byte_order : uint32_t{
    litte_endian,
    //big_endian
};

//don't put onto disk page
struct meta_data{
    uint32_t pageId;            //logical
    //uint32_t offset;            //phsical block offset (for initialization)
    page_state state;           

    uint32_t access_cnt;        //statistic
    uint32_t read_cnt;          //statistic
    uint32_t write_cnt;         //statistic 

    uint32_t data_size;         //tracking payload size
    
    //uint32_t last_verify;     //theta related variable
};

//header
struct header{
    uint32_t page_size_bytes;
    uint32_t version;
    uint32_t CRC32;
    byte_order order;
};

std::vector<uint8_t> h2v(header h);
header v2h(const std::vector<uint8_t>& input);

class page {
private:
    meta_data page_meta_;
    header page_header_;
    std::vector<uint8_t> page_data_;
    uint32_t calculateCRC();
    std::vector<uint8_t> header2Vector();
    //std::vector<uint8_t> full_page_;
public:
    page(uint32_t pageId, uint32_t page_size_bytes);
    page(const page&) = delete;
    page& operator=(const page&) = delete;

    page(page&&) noexcept = default;
    page& operator=(page&&) noexcept = default;

    ~page() = default;
    //write a empty page
    //data = a whole page (header + payload)
    //update version by translating data in to header
    //NOTE: success means the image was programmed, not that its CRC is valid.
    //CRC errors are reported by verifyCRC(); read() still returns the stored image.
    //only program a page whose state is free
    bool program(const uint32_t logical_page_id, const std::vector<uint8_t>& data);
    //only read a page whose state is valid
    bool read(std::vector<uint8_t>& output);
    //reset a page to free state
    void setFree();
    //verify full page crc32
    bool verifyCRC();
    //header layout (little endian)
    // _____________________________________________________
    //|    15-12    |   11-8   |       7-4        |   3-0   |
    //| byte_order  |  version |  page_size_byte  |  CRC32  |
    //|_____________|__________|__________________|_________|
    const header& getHeader() const;
    //get page meta data
    const meta_data& getMetaData() const;
    //get page state
    const page_state& getPagestate() const;
    //debug only (it can get payload without trigger the meta counters)
    const std::vector<uint8_t>& getPagedata() const;
    //get page header + payload
    const std::vector<uint8_t> getFullPage();
};
