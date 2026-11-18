#pragma once

#include "r265_native_contract_v1.h"
#include <span>

namespace r339 {
inline constexpr char kind[] = "dpdfnet-private-model2-five-data-arguments-native-v1";

template<const std::array<std::size_t, 7>& Sizes>
struct Prepared {
  int model;
  std::vector<char> initializer;
  std::array<std::array<std::span<const char>, 7>, 2> nn;
  std::array<std::vector<char>, 3> commands;
  std::unique_ptr<xrt::xclbin> image;

  static Prepared load(const r265::path& registry, int model, int qualified_model,
                       const char* arm, const char* expected_digest) {
    using r265::require;
    const auto root = r189::fs::canonical(registry.parent_path());
    const auto content = r20::read_file(registry, 64 * 1024);
    require(r20::digest(content) == expected_digest, "Unqualified resident precision registry");
    const auto binding = r265::Json::parse(content);
    r265::exact(binding.at("version"), 1);
    require(model == qualified_model && binding.at("model") == model && binding.at("arm") == arm &&
            binding.at("runtime_default") == false && binding.at("kind") == kind && binding.at("precision") == "bf16",
            "Wrong resident precision owner");
    Prepared prepared{};
    prepared.model = model;
    prepared.initializer = r189::file(binding.at("initializer"), root);
    std::span<const char> bytes(prepared.initializer);
    for (auto& lane : prepared.nn) {
      for (std::size_t slot = 0; slot < Sizes.size(); ++slot) {
        if (slot == 5 && &lane == &prepared.nn[1]) {
          lane[slot] = prepared.nn[0][slot];
          continue;
        }
        require(Sizes[slot] <= bytes.size(), "Short precision initializer");
        lane[slot] = bytes.first(Sizes[slot]);
        bytes = bytes.subspan(Sizes[slot]);
      }
    }
    require(bytes.empty(), "Trailing precision initializer bytes");
    const auto& commands = binding.at("commands");
    require(commands.size() == prepared.commands.size(), "Expected three precision dispatches");
    for (std::size_t i = 0; i < prepared.commands.size(); ++i) {
      auto& stream = prepared.commands[i];
      stream = r189::file(commands.at(i), root);
      require(!stream.empty() && stream.size()%4 == 0 && stream.size() < 1024*1024, "Bad resident dispatch extent");
    }
    prepared.image = std::make_unique<xrt::xclbin>(r189::file(binding.at("xclbin"), root));
    const auto kernels = prepared.image->get_kernels();
    require(kernels.size() == 1 && kernels.front().get_name() == "MLIR_AIE", "Wrong resident kernel");
    const auto args = kernels.front().get_args();
    require(args.size() == 8, "Expected five resident data arguments");
    for (std::size_t i = 0; i < args.size(); ++i) {
      const auto name = i == 0 ? "opcode" : i == 1 ? "instr" : i == 2 ? "ninstr" : "bo" + std::to_string(i-3);
      require(args[i].get_name() == name && args[i].get_size() == (i == 2 ? 4u : 8u), "Wrong resident argument ABI");
    }
    return prepared;
  }
};
}  // namespace r339
