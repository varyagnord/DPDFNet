#pragma once
#include "r101_host_contract_v2.h"
#include "r313_full_frame_ort_v1.h"
#include "r313_native_contract_v1.h"
namespace r101 {
struct Channel {
 r296::Backend* backend;
 int model;
 unsigned mask=0;
 std::uint64_t full_frame_calls=0;
 void full_frame(const r313::Inputs& input,const r313::Outputs& output) {
  require(mask==0,"Duplicate full-frame callback");
  backend->FullFrame(input,output);
  mask=127;
  ++full_frame_calls;
 }
};
class SpectralEngine{
 const pid_t owner_pid_=getpid();const std::thread::id owner_thread_=std::this_thread::get_id();
 r296::Backend&backend_;Config config_;Channel channel_;r313::FullFrameOp<Channel> full_frame_;
 Ort::Env env_{ORT_LOGGING_LEVEL_WARNING,"r101-direct-owned-spectral"};Ort::CustomOpDomain ndomain_{"dpdf.resident.v1"};Ort::Session session_{nullptr};Ort::RunOptions options_;
 std::array<std::vector<float>,2>states_;std::array<float,962+32>input_{},enhanced_{};
 std::vector<std::string>names_;std::vector<const char*>output_names_;std::vector<size_t>sizes_;std::array<std::vector<std::vector<float>>,2>extras_;
 std::array<std::vector<Ort::Value>,2>inputs_,outputs_;int current_=0;bool busy_=false,poisoned_=false;uint64_t frames_=0,resets_=0;
 void owner()const{require(owner_pid_==getpid()&&owner_thread_==std::this_thread::get_id(),"R101 inherited or cross-thread engine");}
 void ready()const{owner();require(!busy_&&!poisoned_&&channel_.mask==0,"R101 busy/poisoned engine");}
 const float*output(size_t index,int bank)const{return index==0?enhanced_.data():index==1?states_[1-bank].data():extras_[bank][index].data();}
public:
 SpectralEngine(Config config,r296::Backend&backend):backend_(backend),config_(std::move(config)),channel_{&backend_,config_.model},full_frame_(&channel_){
  ndomain_.Add(&full_frame_);Ort::SessionOptions so;so.Add(ndomain_);so.SetExecutionMode(ORT_SEQUENTIAL);so.SetIntraOpNumThreads(1);so.SetInterOpNumThreads(1);so.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
  session_=Ort::Session(env_,config_.model_bytes.data(),config_.model_bytes.size(),so);const auto&descriptors=config_.selected.at(config_.diagnostic?"all_diagnostic_outputs":"primary_outputs");
  require(session_.GetInputCount()==2&&session_.GetOutputCount()==descriptors.size(),"R101 actual ORT IO count");Ort::AllocatorWithDefaultOptions allocator;
  const std::array<const char*,2>in_names={"spec","state_in"};const std::array<std::vector<int64_t>,2>in_shapes={std::vector<int64_t>{1,1,481,2},std::vector<int64_t>{45172}};
  for(size_t i=0;i<2;++i){auto name=session_.GetInputNameAllocated(i,allocator);auto type=session_.GetInputTypeInfo(i);auto info=type.GetTensorTypeAndShapeInfo();require(std::string(name.get())==in_names[i]&&info.GetElementType()==ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT&&info.GetShape()==in_shapes[i],"R101 actual ORT inputs");}
  for(size_t i=0;i<descriptors.size();++i){auto name=session_.GetOutputNameAllocated(i,allocator);auto type=session_.GetOutputTypeInfo(i);auto info=type.GetTensorTypeAndShapeInfo();auto wanted=descriptors[i].at("shape").get<std::vector<int64_t>>();require(std::string(name.get())==descriptors[i].at("name").get<std::string>()&&info.GetElementType()==ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT&&info.GetShape()==wanted,"R101 actual ORT output metadata");names_.push_back(descriptors[i].at("name"));sizes_.push_back(elements(descriptors[i]));}
  for(const auto&n:names_){output_names_.push_back(n.c_str());}
  for(auto&s:states_){s.resize(45172+32);std::memcpy(s.data(),config_.initial.data(),45172*4);fill_guard(s.data()+45172,32);}fill_guard(input_.data()+962,32);fill_guard(enhanced_.data()+962,32);
  auto memory=Ort::MemoryInfo::CreateCpu(OrtArenaAllocator,OrtMemTypeDefault);const int64_t spec_shape[4]={1,1,481,2},state_shape[1]={45172};
  for(int bank=0;bank<2;++bank){
   extras_[bank].resize(descriptors.size());inputs_[bank].reserve(2);outputs_[bank].reserve(descriptors.size());inputs_[bank].emplace_back(Ort::Value::CreateTensor<float>(memory,input_.data(),962,spec_shape,4));inputs_[bank].emplace_back(Ort::Value::CreateTensor<float>(memory,states_[bank].data(),45172,state_shape,1));
   for(size_t i=0;i<descriptors.size();++i){auto dims=descriptors[i].at("shape").get<std::vector<int64_t>>();float*p=i==0?enhanced_.data():i==1?states_[1-bank].data():nullptr;if(i>1){extras_[bank][i].resize(sizes_[i]+32);p=extras_[bank][i].data();fill_guard(p+sizes_[i],32);}outputs_[bank].emplace_back(Ort::Value::CreateTensor<float>(memory,p,sizes_[i],dims.data(),dims.size()));}
  }
 }
 float*input(){ready();return input_.data();}
 const float*enhanced()const{ready();return enhanced_.data();}
 const float*state()const{ready();return states_[current_].data();}
 const float*previous_state()const{ready();require(frames_>0,"R102 previous state requires completed frame");return states_[1-current_].data();}
 void materialize(std::span<float> prior,std::span<float> current){ready();backend_.materialize(prior,current);}
 const Config&configuration()const{return config_;}
 void process(uint32_t frame,uint32_t generation){
  ready();busy_=true;
  try{
   finite(input_.data(),962);guards(input_.data(),962);guards(states_[current_].data(),45172);backend_.begin(frame,generation);
   static const char*inputs[]={"spec","state_in"};session_.Run(options_,inputs,inputs_[current_].data(),2,output_names_.data(),outputs_[current_].data(),outputs_[current_].size());
   require(channel_.mask==127,"R101 missing actual NN/GRU callbacks");backend_.end();
   for(size_t i=0;i<sizes_.size();++i){finite(output(i,current_),sizes_[i]);guards(output(i,current_),sizes_[i]);}
   guards(input_.data(),962);guards(states_[current_].data(),45172);current_=1-current_;channel_.mask=0;++frames_;busy_=false;
  }catch(...){poisoned_=true;busy_=false;throw;}
 }
 void reset(){ready();try{backend_.reset();for(auto&s:states_)std::memcpy(s.data(),config_.initial.data(),45172*4);current_=0;++resets_;}catch(...){poisoned_=true;throw;}}
 std::vector<std::pair<std::string,std::pair<const float*,size_t>>> diagnostic_arrays()const{
  ready();std::vector<std::pair<std::string,std::pair<const float*,size_t>>>out;for(size_t i=0;i<names_.size();++i)out.push_back({names_[i],{output(i,1-current_),sizes_[i]}});return out;
 }
 Json counters()const{return Json{{"frames",frames_},{"resets",resets_},{"full_frame_callbacks",channel_.full_frame_calls},{"primary_outputs",names_.size()},{"poisoned",poisoned_},{"busy",busy_},{"backend",backend_.counters()}};}
};
}
