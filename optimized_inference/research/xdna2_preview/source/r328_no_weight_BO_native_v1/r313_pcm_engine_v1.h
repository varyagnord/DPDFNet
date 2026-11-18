#pragma once
#include "r313_spectral_engine_v1.h"
#include "r101_cpu_DSP_bridge_v1.h"
#include <cfenv>
#include <xmmintrin.h>
namespace r103 {
using r101::require;
class PCMEngine {
 const pid_t pid_=getpid();const std::thread::id thread_=std::this_thread::get_id();
 r101::SpectralEngine engine_;r101::CPU_DSP dsp_;float*input_;const float*enhanced_;
 std::array<float,480>pcm_in_{},pcm_out_{};uint64_t hops_=0;uint32_t generation_=0;
 bool busy_=false,poisoned_=false,finished_=false;
 static void modes(){require((_mm_getcsr()&0xe040u)==0&&std::fegetround()==FE_TONEAREST,"R103 CPU controls must remain default nearest/noFTZ/noDAZ");}
 void ready()const{require(owned()&&!busy_&&!poisoned_&&!finished_,"R103 PCM owner/busy/poison/finished");}
public:
 PCMEngine(r101::Config config,r296::Backend&backend,const std::filesystem::path&DSP):engine_(std::move(config),backend),dsp_(DSP),input_(engine_.input()),enhanced_(engine_.enhanced()){modes();}
 bool owned()const noexcept{return pid_==getpid()&&thread_==std::this_thread::get_id();}
 bool poisoned()const noexcept{return poisoned_;}
 uint64_t hops()const noexcept{return hops_;}
 const float*output()const{ready();return pcm_out_.data();}
 void process(const float*pcm){
  ready();require(pcm&&hops_<1048576,"R103 PCM finite stream ceiling");r101::finite(pcm,480);modes();busy_=true;
  try{
   std::memcpy(pcm_in_.data(),pcm,1920);dsp_.analysis(pcm_in_.data(),input_);engine_.process(uint32_t(hops_),generation_);modes();dsp_.synthesis(enhanced_,pcm_out_.data());modes();++hops_;busy_=false;
  }catch(...){poisoned_=true;busy_=false;throw;}
 }
 void reset(){ready();require(generation_!=UINT32_MAX,"R103 generation ceiling");modes();try{engine_.reset();dsp_.reset();++generation_;}catch(...){poisoned_=true;throw;}}
 std::vector<float> snapshot_staging_;
 void snapshot(float*out,size_t n){
  ready();require(out&&n==94188&&hops_>0,"R103 snapshot extent/completed frame");size_t at=0;
  snapshot_staging_.resize(n);float* stage=snapshot_staging_.data();
  auto copy=[&](const float*p,size_t count){std::memcpy(stage+at,p,count*4);at+=count;};
  copy(pcm_in_.data(),480);copy(pcm_out_.data(),480);copy(input_,962);copy(enhanced_,962);copy(engine_.previous_state(),45172);copy(engine_.state(),45172);dsp_.snapshot(stage+at,stage+at+480);at+=960;require(at==n,"R103 CPU snapshot layout");
  try {
   std::span<float> full(stage,n);
   engine_.materialize(full.subspan(2884,r311::state_words),
                       full.subspan(2884+r311::state_words,r311::state_words));
  } catch (...) {poisoned_=true;throw;}
  std::memcpy(out,stage,n*sizeof(float));
 }
 void finish(){ready();finished_=true;}
 r101::Json counters()const{return r101::Json{{"hops",hops_},{"generation",generation_},{"poisoned",poisoned_},{"busy",busy_},{"finished",finished_},{"CPU_MXCSR_control",_mm_getcsr()&0xe040u},{"CPU_round",std::fegetround()},{"engine",engine_.counters()}};}
};
}
