#pragma once
#include <cstdint>
#include <vector>

// 固定大小的部分用 struct（加 pack 確保無 padding）
#pragma pack(push, 1)
struct NodeHeader {
    uint8_t  node_type;  // 0=internal, 1=leaf
    uint8_t  pad[3];
    uint32_t n_keys;
    uint64_t next_leaf;  // leaf 才有意義，internal 忽略
    // total: 16 bytes，剛好接在 SSD header 後面
};
#pragma pack(pop)

static constexpr uint64_t INVALID_PAGE = UINT64_MAX;

struct BTreeNode {
    uint64_t              page_id;
    uint8_t               node_type;   // 0=internal, 1=leaf
    std::vector<uint64_t> keys;
    std::vector<uint64_t> children;    // internal only, size = n_keys + 1
    std::vector<uint64_t> values;      // leaf only
    uint64_t              next_leaf = INVALID_PAGE;   // leaf only；internal 一律為 INVALID_PAGE

    bool is_leaf() const { return node_type == 1; }

    void serialize(std::vector<uint8_t>& image) const;

    static BTreeNode deserialize(uint64_t page_id, const std::vector<uint8_t>& image);
};