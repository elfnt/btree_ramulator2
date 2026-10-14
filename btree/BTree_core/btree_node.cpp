#include "btree_node.hpp"
#include <cstring>

void BTreeNode::serialize(std::vector<uint8_t>& image) const {
    // image[0..15] = SSD header（由外部填入，這裡只管 payload）
    size_t off = 16;  // SSD header 之後

    // 1. 寫 NodeHeader
    NodeHeader hdr;
    hdr.node_type = this->node_type;
    hdr.pad[0] = hdr.pad[1] = hdr.pad[2] = 0;
    hdr.n_keys  = static_cast<uint32_t>(this->keys.size());
    hdr.next_leaf = this->next_leaf;
    std::memcpy(image.data() + off, &hdr, sizeof(hdr));
    off += sizeof(hdr);  // off = 32

    // 2. 寫 keys[] 
    for (uint64_t k : keys) {
        std::memcpy(image.data() + off, &k, 8);
        off += 8;
    }
    // 3. 寫 children[] 或 values[]
    for (uint64_t c : (is_leaf() ? values : children)) {
        std::memcpy(image.data() + off, &c, 8);
        off += 8;
    }
}

BTreeNode BTreeNode::deserialize(uint64_t page_id, const std::vector<uint8_t>& image) {
    BTreeNode node;
    node.page_id = page_id;

    // 1. 讀 NodeHeader
    size_t off = 16;   // 跳過 SSD header
    NodeHeader hdr;
    std::memcpy(&hdr, image.data() + off, sizeof(hdr));
    off += sizeof(hdr);  // off = 32

    node.node_type = hdr.node_type;
    node.next_leaf = hdr.next_leaf;
    uint32_t n_keys = hdr.n_keys;

    // 2. 讀 keys[]
    for (uint32_t i = 0; i < n_keys; ++i) {
        uint64_t k;
        std::memcpy(&k, image.data() + off, 8);
        node.keys.push_back(k);
        off += 8;
    }

    // 3. 讀 children[] 或 values[]
    uint32_t arr_size = node.is_leaf() ? n_keys : n_keys + 1;
    for (uint32_t i = 0; i < arr_size; ++i) {
        uint64_t v;
        std::memcpy(&v, image.data() + off, 8);
        if (node.is_leaf()) node.values.push_back(v);
        else                node.children.push_back(v);
        off += 8;
    }

    return node;
}
