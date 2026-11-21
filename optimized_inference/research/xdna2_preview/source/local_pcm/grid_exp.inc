// The pinned AIE2P SDK exposes the four-access API. Both pointers
// refer to static SRAM with each 256-bit group present twice.
[[gnu::noinline]] static VF grid_exp(VF arg, const float* ab, const float* cd) {
    constexpr int bits = GRID_BITS;
    constexpr unsigned bins = 1u << bits;
    constexpr float magic = 12582912.0f / bins;
    constexpr unsigned mask = bins - 1;
    const VF x = vmul(arg, splat(1.4426950408889634f));
    const VF shifted = aie::add(x, splat(magic));
    const VF t = aie::sub(x, aie::sub(shifted, splat(magic)));
    const auto word = shifted.cast_to<uint32>();
    const auto grid = aie::sub(word, __builtin_bit_cast(unsigned, magic));
    const auto index = aie::bit_and(mask, grid).cast_to<int32>();
    const auto scale = aie::bit_and(0xff800000u, aie::upshift(grid, 23 - bits));

    aie::lut<4, float> table(bins, ab, cd);
    aie::parallel_lookup<int32, decltype(table)> fetch(table);
    VF seed;
    seed.insert(0, fetch.fetch(index.extract<16>(0)));
    seed.insert(1, fetch.fetch(index.extract<16>(1)));

    using A = aie::accum<accfloat, 32>;
#if GRID_FAST
    const auto one = aie::broadcast<bfloat16, 32>(1.0f);
    const auto c2 = aie::broadcast<bfloat16, 32>(0.240234375f);
    const auto hi = A(t).to_vector<bfloat16>();
    const auto lo = aie::msc(A(t), hi, one).to_vector<bfloat16>();
    const auto inner = aie::mac(A(splat(0.6931471805599453f)), hi, c2);
    const auto inner_hi = inner.to_vector<bfloat16>();
    const auto inner_lo = aie::msc(inner, inner_hi, one).to_vector<bfloat16>();
    auto p = aie::mac(A(splat(1.0f)), inner_hi, hi);
    p = aie::mac(p, inner_hi, lo);
    p = aie::mac(p, inner_lo, hi);
#else
    const auto inner = aie::mac(A(splat(0.6931471805599453f)),
                                t, splat(0.2402265069591007f)).to_vector<float>();
    const auto p = aie::mac(A(splat(1.0f)), t, inner);
#endif
    const auto before_scaling = vmul(seed, p.to_vector<float>());
    return aie::add(before_scaling.cast_to<uint32>(), scale).cast_to<float>();
}
