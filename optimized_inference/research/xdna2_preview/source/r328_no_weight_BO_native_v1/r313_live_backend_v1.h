#pragma once

#include "r313_joint_owner_v1.h"
#include "r126_joint_layout_v1.h"
#include "host_frames.h"
#include <cerrno>
#include <fcntl.h>
#include <functional>

namespace r296 {

class Observer {
public:
  virtual ~Observer()=default;
  virtual void record(std::uint32_t kind,std::uint32_t slot,std::uint32_t frame,
                      std::uint32_t generation,std::uint32_t ordinal,const void* data,std::size_t n)=0;
};

class LiveBackend final : public Backend {
  path registry_;
  int model_;
  Observer* observer_;
  std::function<void(unsigned)> first_;
  std::unique_ptr<Joint> joint_;
  bool announced_ = false;
  r20::Transfer copies_in_,copies_out_,padding_;
  std::uint64_t known_=0,logical_=0,frames_=0,attempted_=0,identity_barriers_=0,snapshots_=0;
  std::uint32_t frame_=0,epoch_=0,in_epoch_=0;
  unsigned position_=0;
  bool in_frame_=false,finished_=false,poisoned_=false,seed_required_=true;

  void ready() const {
    require(joint_ && !finished_ && !poisoned_ && !r45_containment::pending_or_unknown,
            "Single-command live backend unavailable");
  }

  void identify() {
    if (!announced_) {
      announced_ = true;
      if (first_) { first_(0); ++identity_barriers_; }
    }
  }

  void observe(unsigned kind,unsigned slot,const void* data,std::size_t bytes) {
    if (observer_) {
      observer_->record(kind,slot,frame_,epoch_,static_cast<std::uint32_t>(logical_),data,bytes);
    }
  }

  std::span<const float> dispatch() {
    attempted_ += joint_->commands_per_frame();
    try {
      const auto data = joint_->execute();
      known_ += joint_->commands_per_frame();
      return data;
    } catch (...) {
      poisoned_ = true;
      throw;
    }
  }

  static void save(const path& filename,const std::vector<char>& data) {
    const int fd=::open(filename.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
    require(fd>=0,"Cannot create fresh one-command endpoint");
    try {
      std::size_t at=0;
      while (at<data.size()) {
        const auto count=::write(fd,data.data()+at,data.size()-at);
        if (count<0 && errno==EINTR) { continue; }
        require(count>0,"Cannot write one-command endpoint");
        at+=static_cast<std::size_t>(count);
      }
      require(::fsync(fd)==0,"Cannot persist one-command endpoint");
    } catch (...) {
      ::close(fd);
      throw;
    }
    ::close(fd);
  }

  using Snapshots=std::pair<std::vector<char>,std::vector<char>>;

  Snapshots snapshot() {
    require(!in_frame_,"One-command snapshot during frame");
    Snapshots result;
    for (unsigned branch=0;branch<2;++branch) {
      const auto raw=joint_->snapshot(branch);
      const auto previous=r126layout::previous_maximum_view(raw);
      const std::size_t rows=branch?48:40;
      r118layout::validate_raw(previous,rows,model_);
      const auto compact=r118layout::legacy_view(previous,rows,model_);
      result.first.insert(result.first.end(),compact.begin(),compact.end());
      result.second.insert(result.second.end(),raw.begin(),raw.end());
      observe(18,branch,raw.data(),raw.size());
    }
    ++snapshots_;
    return result;
  }

public:
  LiveBackend(const r101::Config& c,Observer* observer,std::function<void(unsigned)> first={})
    : registry_(c.native_binding.at("path").get<std::string>()), model_(c.model),
      observer_(observer), first_(std::move(first)) {}

  void open() {
    require(!joint_,"One-command backend already opened");
    joint_=std::make_unique<Joint>(Prepared::load(registry_,model_));
    if (observer_) {
      const auto initial=snapshot();
      observe(6,UINT32_MAX,initial.first.data(),initial.first.size());
    }
  }

  void begin(std::uint32_t frame,std::uint32_t generation) override {
    ready();
    require(!in_frame_ && frame==frames_ && generation==epoch_ && frame<1048576,
            "One-command frame or generation differs");
    frame_=frame;
    position_=0;
    in_frame_=true;
  }

  void FullFrame(const r313::Inputs& input, const r313::Outputs& output) override {
    ready();
    require(in_frame_ && position_==0, "Full-frame callback out of order");
    auto packet = joint_->begin();
    const auto nonce = r313::nonce(frame_);
    require(r313::pack(packet, input, frame_, seed_required_, copies_in_), "Full-frame input invalid");
    for (std::size_t lane = 0; lane < r293::branch_rows.size(); ++lane) {
      observe(14, lane, input[lane], r293::branch_rows[lane] * 64 * sizeof(float));
    }
    const auto reply = dispatch();
    require(r313::unpack_hot(reply, nonce, output), "Full-frame reply invalid");
    for (std::size_t i = 0; i < r313::visible_cells.size(); ++i) copies_out_.add(r278::gru::hidden * sizeof(float));
    copies_out_.add(r278::side_words * sizeof(float));
    logical_ += 7;
    position_ = 7;
    if (observer_) {
      std::array<float, r293::public_reply_words> original{};
      require(r313::normalize_reply(reply, joint_->archive(frame_), nonce, original),
              "Cannot materialize recorded compact reply");
      observe(52, 0, original.data(), original.size() * sizeof(float));
    }
    identify();
  }

  void end() override {
    ready();
    require(in_frame_ && position_==7 && known_==joint_->commands_per_frame()*(frames_+1) && logical_==7*(frames_+1),
            "Incomplete resident pair frame");
    in_frame_=false;
    seed_required_=false;
    ++frames_;
    ++in_epoch_;
  }

  void reset() override {
    ready();
    require(!in_frame_ && epoch_<UINT32_MAX,"One-command reset during frame");
    if (observer_) { (void)snapshot(); }
    joint_->reset();
    seed_required_=true;
    ++epoch_;
    in_epoch_=0;
    if (observer_) { (void)snapshot(); }
  }

  void materialize(std::span<float> prior, std::span<float> current) override {
    ready();
    require(!in_frame_, "Cannot materialize state during a compact frame");
    const r311::Boundary boundary{static_cast<std::uint32_t>(frames_), in_epoch_, epoch_};
    const auto expected = r311::wanted(boundary);
    std::array<std::array<float, r311::archived_words>, 2> hidden{};
    std::array<r311::Archive, 2> banks{};
    std::array<const r311::Archive*, 2> present{};
    for (std::size_t slot = 0; slot < expected.size(); ++slot) {
      if (!expected[slot]) continue;
      const auto stamp = *expected[slot];
      require(r313::unpack_archive(joint_->archive(stamp.frame), r313::nonce(stamp.frame), hidden[slot]),
              "Malformed or stale compact GRU archive");
      banks[slot] = {stamp, hidden[slot]};
      present[slot] = &banks[slot];
    }
    require(r311::overlay(prior, current, boundary, present), "Compact state overlay differs");
  }

  void finish(const path& output) {
    ready();
    require(!in_frame_,"One-command close during frame");
    const auto result=snapshot();
    save(output,result.first);
    save(output.string()+".joint-raw.bin",result.second);
    observe(3,UINT32_MAX,result.first.data(),result.first.size());
    joint_->close();
    finished_=true;
  }

  Json counters() const override {
    return {{"actual_NPU",true},{"contexts_created",joint_?1:0},{"live_contexts",joint_&&!finished_?1:0},
            {"logical_NN_graphs",2},{"physical_joint_graphs",1},{"commands_per_context_per_hop",Json::array({joint_?joint_->commands_per_frame():0})},
            {"attempted_commands",attempted_},{"confirmed_completed_commands",known_},
            {"known_full_frame",known_},{"completed_logical_callbacks",logical_},
            {"frame",frame_},{"generation",epoch_},{"active_frame",in_frame_},{"finished",finished_},
            {"poisoned",poisoned_},{"whole_NN_snapshots",snapshots_},{"cold_identity_barriers",identity_barriers_},
            {"manual_payload_input_memcpy",copies_in_.json()},{"manual_payload_output_memcpy",copies_out_.json()},
            {"NN_input_padding_memset",padding_.json()},{"joint_IO_counters",joint_?joint_->counters():Json(nullptr)},
            {"warmed_operator_IPC_calls",0},{"recording_enabled",observer_!=nullptr},
            {"acceptance_or_completion_unknown",bool(r45_containment::pending_or_unknown)}};
  }
};

}  // namespace r296
