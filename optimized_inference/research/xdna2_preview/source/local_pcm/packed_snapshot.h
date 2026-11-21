#pragma once

namespace r848 {

// Reconstruct the existing diagnostic slot with the same bytes and order.
// Each coefficient enters the destination once, directly from the mapped BO.
inline void append_canonical_weights(std::vector<char>& output, const char* source, std::size_t bytes) {
    constexpr std::size_t word_bytes = 2, gate_words = 4224, gate_matrix_words = 4096;
    constexpr std::size_t direction_bytes = 6 * gate_words * word_bytes;
    constexpr std::size_t directions = 8 * 2;
    const auto append = [&](const char* base, std::size_t begin, std::size_t words) {
        const auto* first = base + begin * word_bytes;
        output.insert(output.end(), first, first + words * word_bytes);
    };
    for (std::size_t direction = 0; direction < directions; ++direction) {
        const auto* weights = source + direction * direction_bytes;
        const auto* paired = weights + 3 * gate_words * word_bytes;
        append(weights, 0, 3 * gate_words);
        for (std::size_t gate = 0; gate < 2; ++gate) {
            for (std::size_t k_group = 0; k_group < 8; ++k_group) {
                for (std::size_t out_group = 0; out_group < 8; ++out_group) {
                    const auto band = out_group / 2;
                    const auto col = gate * 16 + (out_group % 2) * 8;
                    for (std::size_t lane = 0; lane < 8; ++lane) {
                        const auto k = k_group * 8 + lane;
                        append(paired, (band * 64 + k) * 32 + col, 8);
                    }
                }
            }
            for (std::size_t band = 0; band < 4; ++band)
                append(paired, 2 * gate_matrix_words + 64 * band + 32 * gate, 32);
        }
        append(weights, 5 * gate_words, gate_words);
    }
    output.insert(output.end(), source + directions * direction_bytes, source + bytes);
}

}  // namespace r848
