#pragma once
#include "r258_bfp16_joint_v1.h"
#include "r331_native_contract_v1.h"
#include "r265_dprnn_ort_v1.h"

namespace r331_m8_bfp16 {


using r258_bfp16::SIZES;
using r258_bfp16::NN_TOTAL;
using r265::Json;
using r265::require;
using r265::path;
using r265::NN_GUARD;
using r265::GRU_GUARD;
using r265::weight_bytes;
using r265::input_bytes;
using r265::output_bytes;
using r265::Backend;
using r265::DPRNNInputs;
using r265::DPRNNOutputs;
using r265::DecoderInputs;
using r265::DecoderOutputs;
using r265::pack_decoder;
using r265::unpack_decoder;
using r265::rows;
inline constexpr std::size_t physical_bytes=2*NN_TOTAL-2*SIZES[5]+4*SIZES[0];
static_assert(physical_bytes==2975744);
struct Prepared : r331::Prepared<SIZES> {
  static Prepared load(const path& registry,int model) {
    return {r331::Prepared<SIZES>::load(registry,model,8,"m8-bfp16","034baffc0b2efe2b36689034f6e8009b3c11b334ce4a88f2e650e9a17a14a9c4")};
  }
};

class Joint {
  static constexpr std::size_t gru_in=6, gru_out=7, total_buffers=8;
  const pid_t pid_=getpid();
  const std::thread::id thread_=std::this_thread::get_id();
  struct Resources {
    explicit Resources(Prepared&& input) : prepared(std::move(input)) {}
    Prepared prepared;
    std::unique_ptr<xrt::device> device;
    std::unique_ptr<xrt::hw_context> context;
    std::unique_ptr<xrt::kernel> kernel;
    std::vector<xrt::bo> instructions,data;
    std::vector<xrt::run> runs;
    std::array<void*,total_buffers> maps{};
  };
  std::unique_ptr<Resources> owner_;
  r189::Ledger ledger_;
  bool pending_=false, poisoned_=false, closed_=false;
  int input_=-1, output_=-1;
  std::array<std::uint64_t,3> calls_{};
  std::uint64_t attempted_=0, known_=0;

  static std::size_t nn_index(std::size_t slot) {
    require(slot<7 && slot!=5,"DPRNN BO slot");
    return slot==6?5:slot;
  }

  static std::size_t input_index(std::size_t entry) { return entry==0?nn_index(0):gru_in; }
  static std::size_t output_index(std::size_t entry) { return entry==0?nn_index(6):gru_out; }
  static std::size_t lane_offset(std::size_t branch,std::size_t slot) { return branch*SIZES[slot]; }

  void owned() const {
    require(pid_==getpid() && thread_==std::this_thread::get_id(),"Resident pair ownership differs");
  }

  void ready() const {
    owned();
    require(owner_ && !closed_ && !pending_ && !poisoned_ && !r45_containment::pending_or_unknown,
            "Resident pair context unavailable");
  }

  void transfer(std::size_t index,xclBOSyncDirection direction,std::size_t n,r20::Transfer& counter,std::size_t offset=0) {
    owner_->data.at(index).sync(direction,n,offset);
    counter.add(n);
  }

  void allocate(std::span<const char> bytes,std::size_t slot,std::span<const char> second={}) {
    auto& owner=*owner_;
    const auto index=owner.data.size();
    const auto size=bytes.size()+second.size();
    owner.data.emplace_back(*owner.device,size,xrt::bo::flags::host_only,owner.kernel->group_id(int(slot+3)));
    owner.maps.at(index)=owner.data.back().map<void*>();
    std::memcpy(owner.maps[index],bytes.data(),bytes.size());
    ledger_.initial_staging.add(bytes.size());
    if (!second.empty()) {
      require(second.size()==bytes.size(),"Two DPRNN lanes have different capacity");
      auto* next=static_cast<char*>(owner.maps[index])+bytes.size();
      std::memcpy(next,second.data(),second.size());
      ledger_.initial_staging.add(second.size());
    }
    transfer(index,XCL_BO_SYNC_BO_TO_DEVICE,size,ledger_.initial_upload);
  }

public:
  explicit Joint(Prepared&& prepared) : owner_(std::make_unique<Resources>(std::move(prepared))) {
    require(!r45_containment::pending_or_unknown,"Cannot construct while acceptance is unknown");
    auto& o=*owner_;
    o.device=std::make_unique<xrt::device>(0);
    o.device->register_xclbin(*o.prepared.image);
    o.context=std::make_unique<xrt::hw_context>(*o.device,o.prepared.image->get_uuid());
    o.kernel=std::make_unique<xrt::kernel>(*o.context,"MLIR_AIE");
    o.instructions.reserve(3);
    o.data.reserve(total_buffers);
    o.runs.reserve(3);
    for (const auto& command:o.prepared.commands) {
      o.instructions.emplace_back(*o.device,command.size(),xrt::bo::flags::cacheable,o.kernel->group_id(1));
      auto& bo=o.instructions.back();
      std::memcpy(bo.map<void*>(),command.data(),command.size());
      ledger_.initial_staging.add(command.size());
      bo.sync(XCL_BO_SYNC_BO_TO_DEVICE,command.size(),0);
      ledger_.initial_upload.add(command.size());
    }
    for (std::size_t slot:{0u,1u,2u,3u,4u,6u}) {
      require(o.prepared.nn[0][slot].size()==SIZES[slot],"DPRNN lane extent");
      allocate(o.prepared.nn[0][slot],nn_index(slot),o.prepared.nn[1][slot]);
    }
    std::vector<char> guarded(2*SIZES[0]);
    for (std::size_t at=0;at<guarded.size();at+=4) {
      std::memcpy(guarded.data()+at,&GRU_GUARD,4);
    }
    allocate(guarded,0);
    allocate(guarded,5);
    require(o.data.size()==total_buffers,"Resident pair physical BO count");
    for (std::size_t selector=0;selector<3;++selector) {
      o.runs.emplace_back(*o.kernel);
      auto& run=o.runs.back();
      run.set_arg(0,std::uint64_t{3});
      run.set_arg(1,o.instructions[selector]);
      run.set_arg(2,static_cast<std::uint32_t>(o.prepared.commands[selector].size()));
      for (std::size_t slot=0;slot<6;++slot) {
        const auto index=selector==0?slot:slot==0?gru_in:slot==5?gru_out:slot;
        run.set_arg(int(slot+3),o.data.at(index));
      }
    }
  }

  Joint(const Joint&)=delete;
  Joint& operator=(const Joint&)=delete;
  ~Joint() {
    if (pid_!=getpid()) { owner_.release();return; }
    if (thread_!=std::this_thread::get_id() || pending_ || r45_containment::pending_or_unknown) {
      for (;;) { ::pause(); }
    }
  }

  void* begin(std::size_t selector) {
    ready();
    require(selector<3 && input_<0,"Resident pair input lease");
    output_=-1;
    input_=static_cast<int>(selector);
    return owner_->maps[input_index(selector)];
  }

  const void* execute(std::size_t selector,std::size_t bytes) {
    ready();
    require(selector<3 && input_==static_cast<int>(selector) && bytes==input_bytes[selector],
            "Incomplete resident pair input");
    try {
      transfer(input_index(selector),XCL_BO_SYNC_BO_TO_DEVICE,bytes,ledger_.hot_input_upload);
      ++attempted_;
      pending_=true;
      r45_containment::pending_or_unknown=1;
      auto& run=owner_->runs[selector];
      run.start();
#ifdef DPDF_R45_CONTAINMENT_QA
      r45_containment::after_successful_start_for_QA();
#endif
      require(run.wait()==ERT_CMD_STATE_COMPLETED,"Resident pair completion unknown");
      r45_containment::pending_or_unknown=0;
      pending_=false;
      ++known_;
      ++calls_[selector];
      input_=-1;
      transfer(output_index(selector),XCL_BO_SYNC_BO_FROM_DEVICE,output_bytes[selector],ledger_.hot_output_download);
      output_=static_cast<int>(selector);
      return owner_->maps[output_index(selector)];
    } catch (...) {
      poisoned_=true;
      throw;
    }
  }

  std::vector<char> snapshot(std::size_t branch) {
    ready();
    require(input_<0 && branch<2,"Resident pair snapshot during lease");
    std::vector<char> full;
    full.reserve(NN_TOTAL);
    for (std::size_t slot=0;slot<7;++slot) {
      const char* data = owner_->prepared.nn[branch][slot].data();
      if (slot != 5) {
        const auto index = nn_index(slot);
        const auto offset = lane_offset(branch,slot);
        transfer(index,XCL_BO_SYNC_BO_FROM_DEVICE,SIZES[slot],ledger_.cold_download,offset);
        data = static_cast<const char*>(owner_->maps[index])+offset;
      }
      if (slot>=2 && slot<5) {
        const auto& expected=owner_->prepared.nn[branch][slot];
        require(expected.size()==SIZES[slot]&&std::memcmp(data,expected.data(),SIZES[slot])==0,
                "Mixed NN immutable bank differs");
      }
      full.insert(full.end(),data,data+SIZES[slot]);
      ledger_.cold_staging.add(SIZES[slot]);
    }
    return full;
  }

  void reset() {
    ready();
    require(input_<0,"Resident pair reset during lease");
    try {
      const auto index=nn_index(1);
      auto* mapped=static_cast<char*>(owner_->maps[index]);
      for (std::size_t branch=0;branch<2;++branch) {
        const auto& initial=owner_->prepared.nn[branch][1];
        std::memcpy(mapped+lane_offset(branch,1),initial.data(),initial.size());
        ledger_.reset_staging.add(initial.size());
      }
      transfer(index,XCL_BO_SYNC_BO_TO_DEVICE,2*SIZES[1],ledger_.reset_upload);
      output_=-1;
    } catch (...) {
      poisoned_=true;
      throw;
    }
  }

  void close() {
    ready();
    require(input_<0,"Resident pair close during lease");
    owner_->runs.clear();
    owner_->data.clear();
    owner_->instructions.clear();
    owner_->kernel.reset();
    owner_->context.reset();
    owner_.reset();
    closed_=true;
    output_=-1;
  }

  Json counters() const {
    owned();
    return {{"attempts",attempted_},{"known",known_},{"known_by_selector",calls_},
            {"closed",closed_},{"pending_or_unknown",pending_},{"poisoned",poisoned_},
            {"input_lease",input_},{"last_output",output_},{"contexts",closed_?0:1},
            {"precreated_runs",3},{"instruction_BOs",3},{"physical_data_BOs",total_buffers},
            {"physical_data_bytes",physical_bytes},{"API_ledger",ledger_.json()}};
  }
};

}  // namespace r331_m8_bfp16
