#pragma once

#include "r313_native_contract_v1.h"
#include "r306_request_packet_v1.h"

namespace r296 {

class Joint {
  static constexpr std::size_t input_bo = 0, state_bo = 1, output_bo = 5;
  static constexpr std::size_t snapshot_scratch_slot = 5, snapshot_output_slot = 6;
  struct Resources {
    Prepared prepared;
    xrt::device device;
    xrt::hw_context context;
    xrt::kernel kernel;
    std::vector<xrt::bo> instructions;
    std::vector<xrt::bo> data;
    std::array<char*, bo_bytes.size()> maps{};
    std::vector<xrt::run> runs;

    static xrt::hw_context bind(xrt::device& device, const xrt::xclbin& image) {
      device.register_xclbin(image);
      return xrt::hw_context(device, image.get_uuid());
    }
    explicit Resources(Prepared&& assets)
        : prepared(std::move(assets)), device(0), context(bind(device, *prepared.image)),
          kernel(context, "MLIR_AIE") {}
  };

  const pid_t pid_ = getpid();
  const std::thread::id thread_ = std::this_thread::get_id();
  std::unique_ptr<Resources> resources_;
  r189::Ledger ledger_;
  r20::Transfer archive_download_;
  std::array<std::optional<std::uint32_t>, 2> synchronized_archive_;
  std::uint64_t attempted_ = 0, known_ = 0;
  std::vector<std::uint64_t> by_entry_;
  bool leased_ = false, pending_ = false, poisoned_ = false, closed_ = false;

  void owned() const {
    require(pid_ == getpid() && thread_ == std::this_thread::get_id(), "One-command context ownership differs");
  }
  void ready() const {
    owned();
    require(resources_ && !closed_ && !pending_ && !poisoned_ && !r45_containment::pending_or_unknown,
            "One-command context unavailable");
  }
  void transfer(std::size_t slot, xclBOSyncDirection direction, std::size_t bytes,
                r20::Transfer& counter, std::size_t offset = 0) {
    require(offset <= bo_bytes[slot] && bytes <= bo_bytes[slot] - offset, "One-command BO span invalid");
    resources_->data.at(slot).sync(direction, bytes, offset);
    counter.add(bytes);
  }
  void stage(std::size_t slot, std::size_t offset, const std::vector<char>& bytes, r20::Transfer& counter) {
    require(offset <= bo_bytes[slot] && bytes.size() <= bo_bytes[slot] - offset, "One-command BO staging span invalid");
    std::memcpy(resources_->maps[slot] + offset, bytes.data(), bytes.size());
    counter.add(bytes.size());
  }

 public:
  explicit Joint(Prepared&& prepared) {
    require(!r45_containment::pending_or_unknown, "Cannot construct while acceptance is unknown");
    resources_ = std::make_unique<Resources>(std::move(prepared));
    auto& r = *resources_;
    const auto count = r.prepared.instructions.size();
    by_entry_.resize(count);
    require(count == 3, "Matched command extent");
    r.instructions.reserve(count);
    for (const auto& command : r.prepared.instructions) {
      auto& bo = r.instructions.emplace_back(r.device, command.size(), xrt::bo::flags::cacheable, r.kernel.group_id(1));
      std::memcpy(bo.map<void*>(), command.data(), command.size());
      ledger_.initial_staging.add(command.size());
      bo.sync(XCL_BO_SYNC_BO_TO_DEVICE, command.size(), 0);
      ledger_.initial_upload.add(command.size());
    }

    r.data.reserve(bo_bytes.size());
    for (std::size_t slot = 0; slot < bo_bytes.size(); ++slot) {
      auto& bo = r.data.emplace_back(r.device, bo_bytes[slot], xrt::bo::flags::host_only, r.kernel.group_id(int(slot + 3)));
      r.maps[slot] = bo.map<char*>();
      const auto logical_slot = slot == output_bo ? snapshot_output_slot : slot;
      const std::size_t base = slot == output_bo ? r313::dprnn_offset_bytes : 0;
      if (slot == output_bo) {
        r118layout::fill_guard(r.maps[slot], reply_bytes, r279::GRU_GUARD);
        ledger_.initial_staging.add(reply_bytes);
      }
      for (std::size_t lane = 0; lane < 2; ++lane) {
        const auto& initial = r.prepared.nn[lane][logical_slot];
        require(initial.size() == SIZES[logical_slot], "One-command lane extent");
        stage(slot, base + lane * SIZES[logical_slot], initial, ledger_.initial_staging);
      }
      if (slot == input_bo) {
        require(r306::valid_erb_padding(r.maps[slot]), "Invalid initial ERB request padding");
        const auto bytes = request_bytes - 2 * SIZES[slot];
        r118layout::fill_guard(r.maps[slot] + 2 * SIZES[slot], bytes, r279::GRU_GUARD);
        ledger_.initial_staging.add(bytes);
      }
      transfer(slot, XCL_BO_SYNC_BO_TO_DEVICE, bo_bytes[slot], ledger_.initial_upload);
    }
    r.runs.reserve(count);
    for (std::size_t entry = 0; entry < count; ++entry) {
      auto& run = r.runs.emplace_back(r.kernel);
      run.set_arg(0, std::uint64_t{3});
      run.set_arg(1, r.instructions[entry]);
      run.set_arg(2, static_cast<std::uint32_t>(r.prepared.instructions[entry].size()));
      for (std::size_t slot = 0; slot < bo_bytes.size(); ++slot) run.set_arg(int(slot + 3), r.data[slot]);
    }
  }

  std::size_t commands_per_frame() const noexcept { return 2; }

  Joint(const Joint&) = delete;
  Joint& operator=(const Joint&) = delete;
  ~Joint() {
    if (pid_ != getpid()) { resources_.release(); return; }
    if (thread_ != std::this_thread::get_id() || pending_ || r45_containment::pending_or_unknown) {
      for (;;) ::pause();
    }
  }

  std::span<float> begin() {
    ready();
    require(!leased_, "One-command input already leased");
    leased_ = true;
    return {reinterpret_cast<float*>(resources_->maps[input_bo]), input_words};
  }

  std::span<const float> execute() {
    ready();
    require(leased_, "One-command request lease missing");
    try {
      transfer(input_bo, XCL_BO_SYNC_BO_TO_DEVICE, request_bytes, ledger_.hot_input_upload);
      // The same context and BOs span all entries. Between entries the
      // host only waits for the previous completion and submits the next run.
      require(known_ % 2 == 0, "Previous compact frame incomplete");
      const auto selected = std::array<std::size_t, 2>{0, 1 + (known_ / 2) % 2};
      for (const auto entry : selected) {
        ++attempted_;
        pending_ = true;
        r45_containment::pending_or_unknown = 1;
        auto& run = resources_->runs[entry];
        run.start();
#ifdef DPDF_R45_CONTAINMENT_QA
        r45_containment::after_successful_start_for_QA();
#endif
        require(run.wait() == ERT_CMD_STATE_COMPLETED, "Matched completion unknown");
        r45_containment::pending_or_unknown = 0;
        pending_ = false;
        ++known_;
        ++by_entry_[entry];
      }
      leased_ = false;
      transfer(output_bo, XCL_BO_SYNC_BO_FROM_DEVICE, reply_bytes, ledger_.hot_output_download);
      return {reinterpret_cast<const float*>(resources_->maps[output_bo]), public_reply_words};
    } catch (...) {
      poisoned_ = true;
      throw;
    }
  }

  std::span<const float> archive(std::uint32_t frame) {
    ready();
    const auto completed = known_ / 2;
    require(!leased_ && known_ % 2 == 0 && frame < completed && completed - frame <= 2,
            "Compact archive frame is unavailable");
    const auto word_offset = r313::archive_offset(frame);
    auto& synchronized = synchronized_archive_[frame % synchronized_archive_.size()];
    // The frame counter advances monotonically, and each new frame owns
    // exactly one bank. The output range of every other command is disjoint.
    if (synchronized != frame) {
      transfer(output_bo, XCL_BO_SYNC_BO_FROM_DEVICE, r313::archive_words * sizeof(float),
               archive_download_, word_offset * sizeof(float));
      synchronized = frame;
    }
    return {reinterpret_cast<const float*>(resources_->maps[output_bo]) + word_offset, r313::archive_words};
  }

  std::vector<char> snapshot(std::size_t lane) {
    ready();
    require(!leased_ && lane < 2, "One-command snapshot during input lease");
    std::vector<char> full;
    full.reserve(NN_TOTAL);
    for (std::size_t logical = 0; logical < SIZES.size(); ++logical) {
      const auto bytes = SIZES[logical];
      if (logical == snapshot_scratch_slot) {
        const auto& scratch = resources_->prepared.nn[lane][logical];
        full.insert(full.end(), scratch.begin(), scratch.end());
      } else {
        const auto slot = logical == snapshot_output_slot ? output_bo : logical;
        const auto offset = lane * bytes + (slot == output_bo ? r313::dprnn_offset_bytes : 0);
        transfer(slot, XCL_BO_SYNC_BO_FROM_DEVICE, bytes, ledger_.cold_download, offset);
        const auto* data = resources_->maps[slot] + offset;
        full.insert(full.end(), data, data + bytes);
      }
      ledger_.cold_staging.add(bytes);
    }
    require(full.size() == NN_TOTAL, "One-command snapshot extent");
    return full;
  }

  void reset() {
    ready();
    require(!leased_, "One-command reset during input lease");
    synchronized_archive_.fill(std::nullopt);
    try {
      for (std::size_t lane = 0; lane < 2; ++lane) {
        stage(state_bo, lane * SIZES[state_bo], resources_->prepared.nn[lane][state_bo], ledger_.reset_staging);
      }
      transfer(state_bo, XCL_BO_SYNC_BO_TO_DEVICE, bo_bytes[state_bo], ledger_.reset_upload);
    } catch (...) {
      poisoned_ = true;
      throw;
    }
  }

  void close() {
    ready();
    require(!leased_, "One-command close during input lease");
    resources_.reset();
    closed_ = true;
  }

  Json counters() const {
    owned();
    return {{"attempts", attempted_}, {"known", known_}, {"known_by_selector", by_entry_},
            {"closed", closed_}, {"pending_or_unknown", pending_}, {"poisoned", poisoned_},
            {"input_leased", leased_}, {"contexts", resources_ ? 1 : 0},
            {"precreated_runs", by_entry_.size()}, {"instruction_BOs", by_entry_.size()}, {"physical_data_BOs", bo_bytes.size()},
            {"physical_data_bytes", physical_bytes}, {"API_ledger", ledger_.json()},
            {"archive_download", archive_download_.json()}};
  }
};

}  // namespace r296
