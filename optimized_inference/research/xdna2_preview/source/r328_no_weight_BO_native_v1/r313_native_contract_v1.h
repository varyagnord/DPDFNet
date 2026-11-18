#pragma once

#include "r294_native_contract_v1.h"
#include "r313_host_reply_v1.h"

namespace r296 {

struct Backend : r101::Backend {
  void NN(unsigned, std::size_t, const float*, float*) final {
    throw std::runtime_error("Expected the compact PCM callback");
  }
  void GRU(unsigned, const float*, const float*, float*) final {
    throw std::runtime_error("Expected the compact PCM callback");
  }
  virtual void FullFrame(const r313::Inputs&, const r313::Outputs&) = 0;
  virtual void materialize(std::span<float>, std::span<float>) = 0;
};
using r294::Json;
using r294::NN_TOTAL;
using r294::SIZES;
using r294::exact;
using r308::input_words;
using r294::path;
inline constexpr auto public_reply_words = r313::hot_words;
inline constexpr auto reply_bytes = public_reply_words * sizeof(float);
inline constexpr auto request_bytes = input_words * sizeof(float);
inline constexpr std::array<std::size_t, 6> bo_bytes{
    request_bytes, 2 * SIZES[1], 2 * SIZES[2], 2 * SIZES[3], 2 * SIZES[4],
    r313::total_output_words * sizeof(float)};
inline constexpr auto physical_bytes = [] {
  std::size_t bytes = 0;
  for (const auto extent : bo_bytes) bytes += extent;
  return bytes;
}();
static_assert(physical_bytes == 3115840);
static_assert(request_bytes == 26304);
using r294::require;
using r294::set_graph;

inline std::size_t command_count(const Json& runtime) {
  require(runtime == "split", "Resident GRU requires the matched split regime");
  return 2;
}

struct Prepared {
  int model;
  std::array<std::array<std::vector<char>, 7>, 2> nn;
  std::vector<std::vector<char>> instructions;
  std::unique_ptr<xrt::xclbin> image;

  static Prepared load(const path& registry, int model) {
    const auto root = r189::fs::canonical(registry.parent_path());
    const auto source = Json::parse(r20::read_file(registry, 4 * 1024 * 1024));
    exact(source.at("version"), 1);
    require((model == 2 || model == 8) && source.at("kind") == "dpdfnet-private-context-weights-no-host-slot-v1" &&
            source.at("precision") == "bf16" && source.at("runtime_default") == false,
            "Invalid matched BF16 registry");
    (void)command_count(source.at("regime"));
    constexpr std::size_t count = 3;
    const auto& base = source.at("prior");
    require(r189::fs::canonical(base.at("path").get<std::string>()) == root / "R294_BF16_NATIVE_REGISTRY_V1.json",
            "Unexpected match-control prior registry");
    (void)r189::file(base, root);
    require(source.at("audit").at("sha256") == "ac1c8dc92807da6a17d9f0ad046fbcd65ca50d36d49e9620e291859498a318c8",
            "Unapproved resident GRU device image");
    const auto audited = r254::document(source.at("audit"), root, "R328_WEIGHT_STATIC_V1.json");
    require(audited.at("passed") == true, "Resident GRU image proof");
    exact(audited.at("requested_hot_sync_bytes"), reply_bytes);
    const auto& proof = r279::model_row(audited.at("models"), model);
    exact(proof.at("resources").at("core_count"), 32);
    exact(audited.at("physical_data_BOs"), bo_bytes.size());
    exact(audited.at("physical_data_bytes"), physical_bytes);
    require(proof.at("exact_PDI") == true, "Resident context image differs");
    const auto& initial = proof.at("nn_initial_state");
    std::array<std::array<std::vector<char>, 7>, 2> banks;
    require(initial.size() == banks.size(), "Expected two NN banks");
    for (std::size_t lane = 0; lane < banks.size(); ++lane) {
      require(initial.at(lane).size() == SIZES.size(), "Expected the original snapshot shape");
      for (std::size_t slot = 0; slot < SIZES.size(); ++slot) {
        auto& bytes = banks[lane][slot];
        bytes = r189::file(initial.at(lane).at(slot), root);
        require(bytes.size() == SIZES[slot], "Invalid retained NN input size");
        r189::words(bytes, bytes.size() - 128, r279::NN_GUARD);
      }
    }
    require(banks[0][5] == banks[1][5], "Logical scratch snapshot must be stable");
    for (const auto& route : proof.at("routes")) {
      const auto& request = route.at("descriptors").at(0);
      exact(request.at("slot"), 0);
      exact(request.at("offset"), r293::recurrent_offset);
      exact(request.at("count"), r308::packet_words);
    }
    const auto& commands = proof.at("commands");
    require(commands.size() == 3, "Unexpected matched command count");
    std::vector<std::vector<char>> instructions;
    instructions.reserve(count);
    for (const auto* name : {"front_and_encoder", "recurrent_tail_0", "recurrent_tail_1"}) {
      instructions.push_back(r189::file(commands.at(name), root));
    }
    for (const auto& sequence : instructions) {
      require(!sequence.empty() && sequence.size() % 4 == 0 && sequence.size() < 1024 * 1024,
              "Matched instruction extent invalid");
    }
    const auto& image = proof.at("xclbin");
    require(path(image.at("path").get<std::string>()).extension() == ".xclbin", "Expected matched xclbin");
    auto executable = std::make_unique<xrt::xclbin>(r189::file(image, root));
    const auto kernels = executable->get_kernels();
    require(kernels.size() == 1 && kernels.front().get_name() == "MLIR_AIE", "Matched xclbin kernel differs");
    const auto args = kernels.front().get_args();
    require(args.size() == 3 + bo_bytes.size(), "Matched xclbin must bind six data BOs");
    for (std::size_t i = 0; i < args.size(); ++i) {
      const auto name = i == 0 ? "opcode" : i == 1 ? "instr" : i == 2 ? "ninstr" : "bo" + std::to_string(i - 3);
      require(args[i].get_name() == name && args[i].get_size() == (i == 2 ? 4u : 8u),
              "Matched xclbin argument ABI differs");
    }
    return {model, std::move(banks), std::move(instructions), std::move(executable)};
  }
};

}  // namespace r296
