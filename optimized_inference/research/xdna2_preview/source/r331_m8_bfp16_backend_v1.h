#pragma once

#include "r265_dprnn_ort_v1.h"
#include "r331_m8_bfp16_joint_v1.h"
#include "r243_snapshot_layout_v1.h"
#include "host_frames.h"
#include <cerrno>
#include <fcntl.h>
#include <functional>

namespace r331_m8_bfp16 {

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
  std::array<bool,3> announced_{};
  std::array<std::uint64_t,3> completions_{};
  r20::Transfer copies_in_,copies_out_,padding_;
  std::uint64_t known_=0,logical_=0,frames_=0,attempted_=0,identity_barriers_=0,snapshots_=0;
  std::uint32_t frame_=0,epoch_=0;
  unsigned position_=0;
  bool in_frame_=false,finished_=false,poisoned_=false;
  std::array<char,12416> debug_{};

  void ready() const {
    require(joint_ && !finished_ && !poisoned_ && !r45_containment::pending_or_unknown,
            "Paired live backend unavailable");
  }

  void identify(unsigned graph) {
    if (!announced_[graph]) {
      announced_[graph]=true;
      if (first_) { first_(graph);++identity_barriers_; }
    }
  }

  void observe(unsigned kind,unsigned slot,const void* data,std::size_t bytes) {
    if (observer_) {
      observer_->record(kind,slot,frame_,epoch_,static_cast<std::uint32_t>(logical_),data,bytes);
    }
  }

  const float* dispatch(std::size_t selector,unsigned family) {
    ++attempted_;
    try {
      const auto* data=static_cast<const float*>(joint_->execute(selector,input_bytes[selector]));
      ++known_;
      ++completions_[family];
      return data;
    } catch (...) {
      poisoned_=true;
      throw;
    }
  }

  static void save(const path& filename,const std::vector<char>& data) {
    const int fd=::open(filename.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
    require(fd>=0,"Cannot create fresh resident-pair endpoint");
    try {
      std::size_t at=0;
      while (at<data.size()) {
        const auto count=::write(fd,data.data()+at,data.size()-at);
        if (count<0 && errno==EINTR) { continue; }
        require(count>0,"Cannot write resident-pair endpoint");
        at+=static_cast<std::size_t>(count);
      }
      require(::fsync(fd)==0,"Cannot persist resident-pair endpoint");
    } catch (...) {
      ::close(fd);
      throw;
    }
    ::close(fd);
  }

  using Snapshots=std::pair<std::vector<char>,std::vector<char>>;

  Snapshots snapshot() {
    require(!in_frame_,"Resident pair snapshot during frame");
    Snapshots result;
    for (unsigned branch=0;branch<2;++branch) {
      const auto raw=joint_->snapshot(branch);
      const std::size_t rows=branch?48:40;
      const auto compact=r243snapshot::compact_view(raw,rows,model_);
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
    require(!joint_,"Resident pair backend already opened");
    joint_=std::make_unique<Joint>(Prepared::load(registry_,model_));
    if (observer_) {
      const auto initial=snapshot();
      observe(6,UINT32_MAX,initial.first.data(),initial.first.size());
    }
  }

  void begin(std::uint32_t frame,std::uint32_t generation) override {
    ready();
    require(!in_frame_ && frame==frames_ && generation==epoch_ && frame<1048576,
            "Resident pair frame or generation differs");
    frame_=frame;
    position_=0;
    in_frame_=true;
  }

  void DPRNNDual(const DPRNNInputs& in,const DPRNNOutputs& out) override {
    ready();
    require(in_frame_ && position_==0,"Dual DPRNN callback out of order");
    for (std::size_t lane=0;lane<2;++lane) {
      require(in[lane] && out[lane],"Missing dual DPRNN tensor");
      r101::finite(in[lane],rows[lane]*64);
    }
    auto* frame=static_cast<char*>(joint_->begin(0));
    for (unsigned lane=0;lane<2;++lane) {
      r118layout::pack(frame+lane*SIZES[0],in[lane],rows[lane],copies_in_,padding_);
      observe(14,lane,in[lane],rows[lane]*64*sizeof(float));
    }
    const auto* joined=dispatch(0,0);
    const std::array<const float*,2> replies{joined,joined+SIZES[6]/sizeof(float)};
    for (const auto* reply:replies) {
      r101::finite(reply,3072);
      r118layout::guards(reinterpret_cast<const char*>(reply),12288,NN_GUARD);
    }
    for (std::size_t channel=0;channel<64;++channel) {
      for (std::size_t inactive=40;inactive<48;++inactive) {
        require(dpdf::paired_gru::word(replies[0]+channel*48+inactive)==0,"ERB inactive row changed");
      }
    }
    for (unsigned lane=0;lane<2;++lane) {
      r118layout::unpack(out[lane],replies[lane],rows[lane],copies_out_);
      ++position_;
      ++logical_;
      if (observer_) {
        const auto bytes=rows[lane]*64*sizeof(float);
        std::memcpy(debug_.data(),out[lane],bytes);
        r118layout::fill_guard(debug_.data()+bytes,128,GRU_GUARD);
        observe(4,lane,debug_.data(),bytes+128);
      }
      identify(lane);
    }
  }

  void GRU(unsigned cell,const float* x,const float* h,float* y) override {
    using namespace dpdf::paired_gru;
    ready();
    require(in_frame_ && cell==0 && position_==2,"Resident pair encoder order");
    r101::finite(x,hidden);
    r101::finite(h,hidden);
    auto* frame=static_cast<float*>(joint_->begin(1));
    std::memcpy(frame,x,hidden*4);
    std::memcpy(frame+hidden,h,hidden*4);
    copies_in_.add(hidden*4);
    copies_in_.add(hidden*4);
    const auto nonce=0x97000000u+static_cast<std::uint32_t>(logical_);
    store_metadata(frame+2*hidden,nonce);
    observe(11,cell,frame,input_bytes[1]);
    const auto* out=dispatch(1,2);
    require(valid_cell(out,nonce) && valid_guards(out+single_output_words),"Resident encoder reply invalid");
    std::memcpy(y,out+guards,hidden*4);
    copies_out_.add(hidden*4);
    ++logical_;
    ++position_;
    observe(1,cell,out,output_bytes[1]);
    identify(2);
  }


  void GRUDual(const DecoderInputs& in, const DecoderOutputs& out) override {
    using namespace dpdf::paired_gru;
    ready();
    require(in_frame_ && position_ == 3, "Fused decoder order");
    for (const auto* input : in) { r101::finite(input, hidden); }
    auto* frame = static_cast<float*>(joint_->begin(2));
    const auto nonce = 0x97000000u + static_cast<std::uint32_t>(logical_);
    pack_decoder(frame, in, nonce);
    for (std::size_t i = 0; i < in.size(); ++i) { copies_in_.add(hidden * sizeof(float)); }
    observe(43, 1, frame, input_bytes[2]);
    const auto* reply = dispatch(2, 2);
    require(unpack_decoder(reply, nonce, out), "Fused decoder guarded replies invalid");
    for (std::size_t i = 0; i < out.size(); ++i) { copies_out_.add(hidden * sizeof(float)); }
    logical_ += out.size();
    position_ += out.size();
    observe(44, 1, reply, output_bytes[2]);
  }

  void end() override {
    ready();
    require(in_frame_ && position_==7 && known_==3*(frames_+1) && logical_==7*(frames_+1),
            "Incomplete resident pair frame");
    in_frame_=false;
    ++frames_;
  }

  void reset() override {
    ready();
    require(!in_frame_ && epoch_<UINT32_MAX,"Resident pair reset during frame");
    if (observer_) { (void)snapshot(); }
    joint_->reset();
    ++epoch_;
    if (observer_) { (void)snapshot(); }
  }

  void finish(const path& output) {
    ready();
    require(!in_frame_,"Resident pair close during frame");
    const auto result=snapshot();
    save(output,result.first);
    save(output.string()+".joint-raw.bin",result.second);
    observe(3,UINT32_MAX,result.first.data(),result.first.size());
    joint_->close();
    finished_=true;
  }

  Json counters() const override {
    return {{"actual_NPU",true},{"contexts_created",joint_?1:0},{"live_contexts",joint_&&!finished_?1:0},
            {"logical_NN_graphs",2},{"physical_joint_graphs",1},{"commands_per_context_per_hop",Json::array({3})},
            {"attempted_commands",attempted_},{"confirmed_completed_commands",known_},
            {"known_by_dual_DPRNN_reserved_GRU",completions_},{"completed_logical_callbacks",logical_},
            {"frame",frame_},{"generation",epoch_},{"active_frame",in_frame_},{"finished",finished_},
            {"poisoned",poisoned_},{"whole_NN_snapshots",snapshots_},{"cold_identity_barriers",identity_barriers_},
            {"manual_payload_input_memcpy",copies_in_.json()},{"manual_payload_output_memcpy",copies_out_.json()},
            {"NN_input_padding_memset",padding_.json()},{"joint_IO_counters",joint_?joint_->counters():Json(nullptr)},
            {"warmed_operator_IPC_calls",0},{"recording_enabled",observer_!=nullptr},
            {"acceptance_or_completion_unknown",bool(r45_containment::pending_or_unknown)}};
  }
};

}  // namespace r331_m8_bfp16
