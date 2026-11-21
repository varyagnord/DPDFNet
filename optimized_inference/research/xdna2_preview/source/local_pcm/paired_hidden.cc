#include <aie_api/aie.hpp>
#include <array>
#include <utility>

static_assert(__AIE_ARCH__ == 21);

namespace {
constexpr unsigned Hidden = 64;
constexpr unsigned Columns = 16;
constexpr unsigned LaneCount = 2 * Columns;
constexpr unsigned BandWords = Hidden * LaneCount;
using Accumulator = aie::accum<accfloat, LaneCount>;
using InputGroup = aie::vector<bfloat16, 32>;

template <unsigned Lane, std::size_t Count, std::size_t... B>
__attribute__((always_inline)) inline void update_lane(
    const InputGroup& input, const bfloat16* coeff,
    std::array<Accumulator, Count>& accumulators, std::index_sequence<B...>) {
    const auto value = aie::broadcast<decltype(input[Lane]), LaneCount>(input[Lane]);
    ((accumulators[B] = ::mac_elem_32(
        value, aie::load_v<LaneCount>(coeff + BandWords * B + LaneCount * Lane),
        accumulators[B])), ...);
}

template <std::size_t Count, std::size_t... Lane>
__attribute__((always_inline)) inline void update_group(
    const InputGroup& input, const bfloat16* coeff,
    std::array<Accumulator, Count>& accumulators, std::index_sequence<Lane...>) {
    (update_lane<Lane>(input, coeff, accumulators, std::make_index_sequence<Count>{}), ...);
}

template <unsigned Offset>
__attribute__((always_inline)) inline void save_band(
    const Accumulator& acc, const bfloat16* bias, float* output) {
    const aie::vector<float, LaneCount> value = aie::add(acc.to_vector<float>(),
        aie::load_v<2 * LaneCount>(bias + 2 * LaneCount * Offset).cast_to<float>());
    aie::store_v(output + Columns * Offset, value.extract<Columns>(0));
    aie::store_v(output + Hidden + Columns * Offset, value.extract<Columns>(1));
}

template <std::size_t... B>
__attribute__((always_inline)) inline void paired_pipeline(
    const bfloat16 *__restrict input, const bfloat16 *__restrict weights,
    float *__restrict output, std::index_sequence<B...>) {
    constexpr unsigned count = sizeof...(B);
    const auto zero = aie::zeros<float, LaneCount>();
    const auto* coeff = weights;
    const auto* bias = weights + 2 * Hidden * Hidden;
    for (unsigned band = 0; band < 4; band += count) {
        std::array<Accumulator, count> acc{(static_cast<void>(B), Accumulator(zero))...};
        for (unsigned group = 0; group < Hidden; group += 8) {
            const InputGroup hidden = aie::load_v<8>(input + group).grow<32>();
            update_group(hidden, coeff + group * LaneCount, acc, std::make_index_sequence<8>{});
        }
        (save_band<B>(acc[B], bias, output), ...);
        coeff += count * BandWords;
        bias += count * 2 * LaneCount;
        output += count * Columns;
    }
}
}

extern "C" void r553_paired_hidden(const bfloat16* input,
                                      const bfloat16* weights, float* output) {
    paired_pipeline(input, weights, output, std::make_index_sequence<4>{});
}
