// Private direct PCM research facade. The public CPU DSO is unchanged.
#include "r103_pcm_facade_v1.h"
#include "r265_pcm_engine_v1.h"
#include "r339_m2_df_bfp16_k64_backend_v1.h"
#include "r190_host_contract_v1.h"
#include <sys/stat.h>
namespace {
using namespace r101;
struct Manifest{Config config;Json DSP;bool record;std::string precision;};
Manifest manifest(const char*name,int model){
 require(model==2,"Inactive precision model");
 require(name&&name[0]=='/',"R103 absolute explicit manifest");auto path=fs::canonical(name);auto j=Json::parse(r33::read_file(path,4*1024*1024));auto root=fs::canonical(j.at("root").get<std::string>());
 require(root==path.parent_path()&&integer(j.at("version"),1)==1&&j.at("kind")=="dpdfnet-private-model2-five-data-arguments-pcm-v1"&&j.at("recording").is_boolean(),"R103 exact manifest contract");
 const auto precision=j.at("precision").get<std::string>();
 require(precision=="bf16"&&j.at("profile")=="dual-dprnn-m2-df-bfp16-k64",
         "Paired PCM precision differs");
 file(j.at("model_registry"),root);file(j.at("DSP_runtime"),root);require(fs::canonical(j.at("model_registry").at("path").get<std::string>())==root/"R190_MODEL_REGISTRY_V1.json"&&fs::canonical(j.at("DSP_runtime").at("path").get<std::string>())==root/"R101_CPU_DSP_RUNTIME_V1.json","R103 exact qualified registries");
 auto c=r190::config(j.at("model_registry").at("path").get<std::string>(),model,false);auto d=Json::parse(r33::read_file(j.at("DSP_runtime").at("path").get<std::string>(),4*1024*1024));require(integer(d.at("version"),1)==1&&d.at("kind")=="r101-pinned-HushMic-CPU-DSP-v1"&&fs::canonical(d.at("root").get<std::string>())==root,"R103 CPU DSP contract");file(d.at("build_receipt"),root);file(d.at("library"),root);
 unsigned seen=0;require(j.at("models").size()==2,"R103 both original model identities");for(const auto&m:j.at("models")){auto id=integer(m.at("model"),8);require(id==2||id==8,"R103 original model id");unsigned bit=id==2?1:2;require(!(seen&bit),"R103 duplicate original model");seen|=bit;file(m.at("original_onnx"),root);}require(seen==3,"R103 both model identities");

 r265::set_graph(c,j.at("prior_graph"),j.at("graph_rewrite"));
 const auto native=Json::parse(file(j.at("candidate_binding"),root));
 require(native.at("version")==1&&native.at("kind")=="dpdfnet-private-model2-five-data-arguments-native-v1"&&
         native.at("precision")==precision&&native.at("runtime_default")==false,
         "Paired PCM and native precision binding differ");
 c.native_binding=j.at("candidate_binding");
 return Manifest{std::move(c),std::move(d),j.at("recording").get<bool>(),precision};
}
fs::path output_prefix(const fs::path&root){
 const char*value=getenv("DPDF_R103_OUTPUT_DIRECTORY");require(value&&value[0]=='/',"R103 fresh explicit output directory required");fs::path requested(value);struct stat st{};require(lstat(value,&st)==0&&S_ISDIR(st.st_mode)&&!S_ISLNK(st.st_mode)&&st.st_uid==getuid()&&(st.st_mode&0777)==0700,"R103 owned private nonsymlink output directory");auto actual=fs::canonical(requested);require(requested==actual&&actual!=root,"R103 canonical output directory");auto at=actual.begin();for(auto i=root.begin();i!=root.end();++i,++at)require(at!=actual.end()&&*i==*at,"R103 output outside research root");require(fs::is_empty(actual),"R103 output directory must be fresh empty");return actual/"worker";
}
class Recorder final:public r339_m2_df_bfp16_k64::Observer{
 int fd_=-1;
 void write_all(const void*p,size_t n){auto*b=static_cast<const char*>(p);while(n){auto k=::write(fd_,b,n);if(k<0&&errno==EINTR)continue;require(k>0,"R103 diagnostic write");b+=k;n-=size_t(k);}}
public:
 explicit Recorder(const fs::path&path){fd_=::open(path.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);require(fd_>=0,"R103 fresh diagnostic path");}
 ~Recorder(){if(fd_>=0)::close(fd_);}
 void record(uint32_t kind,uint32_t selector,uint32_t frame,uint32_t gen,uint32_t ordinal,const void*p,size_t n)override{
  require(n<=4*1024*1024,"R103 record bound");const uint32_t h[8]={0x10225044,1,kind,selector,frame,gen,ordinal,uint32_t(n)};write_all(h,sizeof(h));if(n)write_all(p,n);require(fsync(fd_)==0,"R103 record durability");
 }
};
struct Context {
 const pid_t pid=getpid();const std::thread::id thread=std::this_thread::get_id();
 std::unique_ptr<Recorder>recorder;std::unique_ptr<r339_m2_df_bfp16_k64::LiveBackend>backend;std::unique_ptr<r103::PCMEngine>engine;
 fs::path prefix;std::string precision;int model=0;uint64_t index=0;bool busy=false,finished=false,failed=false;r103_identity_hook hook=nullptr;void*hook_data=nullptr;
 ~Context(){if(r45_containment::pending_or_unknown){for(;;)::pause();}}
 bool owner()const noexcept{return pid==getpid()&&thread==std::this_thread::get_id();}
 bool enter()noexcept{if(!owner()||busy||finished||failed)return false;busy=true;return true;}
 Json counters(const char*status)const{
  Json j{{"version",1},{"kind","dpdfnet-private-model2-five-data-arguments-pcm-v1"},{"profile","dual-dprnn-m2-df-bfp16-k64"},{"precision",precision},{"status",status},{"pid",pid},{"model",model},{"index",index},{"busy",busy},{"finished",finished},{"failed",failed},{"recording",recorder!=nullptr},{"acceptance_or_completion_unknown",bool(r45_containment::pending_or_unknown)},{"native",backend?backend->counters():Json(nullptr)},{"PCM",engine?engine->counters():Json(nullptr)}};
#ifdef DPDF_R45_CONTAINMENT_QA
  j["QA_successful_starts"]=r45_containment::QA_successful_starts;j["QA_after_start_trigger"]=r45_containment::QA_throw_after_start;
#endif
  return j;
 }
 void persist(const char*status){
  const auto text=counters(status).dump(2)+"\n";const auto path=prefix.string()+".facade-receipt.json";int fd=::open(path.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);require(fd>=0,"R103 fresh facade receipt");size_t at=0;
  while(at<text.size()){auto k=::write(fd,text.data()+at,text.size()-at);if(k<0&&errno==EINTR)continue;if(k<=0){::close(fd);throw std::runtime_error("R103 receipt write");}at+=size_t(k);}const int result=fsync(fd);::close(fd);require(result==0,"R103 receipt durability");
 }
};
[[noreturn]]void quarantine(Context*c){
 if(c){c->failed=true;try{c->persist("quarantined_start_or_wait_unknown");}catch(...){}}
 static const char marker[]="R265_QUARANTINED_ENTIRE_FUSED_DECODER_OWNER_WITH_PERSISTENT_BUFFERS_HELD\n";
 (void)::write(STDERR_FILENO,marker,sizeof(marker)-1);for(;;)::pause();
}
struct Entry{Context*c;~Entry(){c->busy=false;}};
int failed(Context*c)noexcept{if(r45_containment::pending_or_unknown)quarantine(c);c->failed=c->failed||(c->engine&&c->engine->poisoned());return -1;}
struct Epoch{Context*c;const float*pcm;uint64_t frames;};
int callback(void*p,uint64_t)noexcept{
 auto&e=*static_cast<Epoch*>(p);try{e.c->engine->process(e.pcm+(e.c->index%e.frames)*480);++e.c->index;return 0;}catch(...){return failed(e.c);}
}
}
extern "C" uint32_t r103_abi_version_v1(void){return 1;}
extern "C" int r103_qa_config_only_v1(void){
#ifdef DPDF_R45_CONTAINMENT_QA
 try{r45_containment::configure_QA();return r45_containment::QA_throw_after_start==6?6:-1;}catch(...){return -1;}
#else
 return 0;
#endif
}
extern "C" int r103_config_only_v1(const char*p,int model){try{auto m=manifest(p,model);auto prepared=r339_m2_df_bfp16_k64::Prepared::load(m.config.native_binding.at("path").get<std::string>(),model);return prepared.model==model?0:-1;}catch(...){return -1;}}
extern "C" void*audio_native_create(const char*path,const char*original){
 std::unique_ptr<Context>c;
 try{
  require(original&&original[0]=='/',"R103 explicit original model path");auto modelpath=fs::canonical(original);auto name=modelpath.filename().string();int model=name=="dpdfnet2_48khz_hr.onnx"?2:name=="dpdfnet8_48khz_hr.onnx"?8:0;auto m=manifest(path,model);auto j=Json::parse(r33::read_file(path,4*1024*1024));bool matched=false;for(const auto&v:j.at("models"))if(v.at("model")==model){matched=fs::canonical(v.at("original_onnx").at("path").get<std::string>())==modelpath;}require(matched,"R103 original model path identity");
  c=std::make_unique<Context>();c->model=model;c->precision=m.precision;c->prefix=output_prefix(m.config.root);if(m.record)c->recorder=std::make_unique<Recorder>(c->prefix.string()+".records");auto*stable=c.get();
  auto identify=[stable](unsigned graph){if(stable->hook)require(stable->hook(stable->hook_data,graph)==0,"R103 cold identity hook");};
  c->backend=std::make_unique<r339_m2_df_bfp16_k64::LiveBackend>(m.config,c->recorder.get(),identify);c->engine=std::make_unique<r103::PCMEngine>(m.config,*c->backend,m.DSP.at("library").at("path").get<std::string>());
#ifdef DPDF_R45_CONTAINMENT_QA
  r45_containment::configure_QA();require(r45_containment::QA_throw_after_start==6,"R103 QA6 required");
#endif
  c->backend->open();return c.release();
 }catch(...){if(r45_containment::pending_or_unknown)quarantine(c.get());return nullptr;}
}
extern "C" int r103_set_identity_hook_v1(void*p,r103_identity_hook hook,void*data){auto*c=static_cast<Context*>(p);if(!c||!c->owner()||c->busy||c->finished||c->failed||c->engine->hops())return -1;c->hook=hook;c->hook_data=data;return 0;}
extern "C" int audio_native_step(void*p,const float*input,float*output){auto*c=static_cast<Context*>(p);if(!c||!input||!output||!c->enter())return -1;Entry e{c};try{c->engine->process(input);std::memcpy(output,c->engine->output(),1920);++c->index;return 0;}catch(...){return failed(c);}}
extern "C" int audio_native_reset(void*p){auto*c=static_cast<Context*>(p);if(!c||!c->enter())return -1;Entry e{c};try{c->engine->reset();c->index=0;return 0;}catch(...){return failed(c);}}
extern "C" int r103_cpu_snapshot_v1(void*p,float*out,size_t n){auto*c=static_cast<Context*>(p);if(!c||!c->enter())return -1;Entry e{c};try{c->engine->snapshot(out,n);return 0;}catch(...){return failed(c);}}
extern "C" size_t r103_counters_v1(void*p,char*out,size_t n){auto*c=static_cast<Context*>(p);if(!c||!c->owner()||c->busy)return 0;try{auto text=c->counters(c->finished?"closed":c->failed?"failed":"ready").dump();size_t size=text.size()+1;if(!out&&n==0)return size;if(!out||n<size)return 0;std::memcpy(out,text.c_str(),size);return size;}catch(...){return 0;}}
extern "C" int r103_finish_v1(void*p){auto*c=static_cast<Context*>(p);if(!c||!c->enter())return -1;Entry e{c};try{c->backend->finish(c->prefix.string()+".final-NN-banks.bin");c->engine->finish();c->finished=true;c->persist("closed");return 0;}catch(...){c->failed=true;return failed(c);}}
extern "C" int r103_destroy_v1(void*p){auto*c=static_cast<Context*>(p);if(!c)return 0;if(!c->owner()||c->busy)return -1;if(r45_containment::pending_or_unknown)quarantine(c);int code=0;if(!c->finished&&!c->failed)code=r103_finish_v1(c);delete c;return code;}
extern "C" void audio_native_destroy(void*p){(void)r103_destroy_v1(p);}
extern "C" int audio_native_service_pid(void*p){auto*c=static_cast<Context*>(p);return c&&c->owner()?c->pid:-1;}
extern "C" int audio_native_profile(void*p){auto*c=static_cast<Context*>(p);return c&&c->owner()?2:0;}
extern "C" uint64_t audio_native_digest(void*p){auto*c=static_cast<Context*>(p);if(!c||!c->owner()||c->busy||c->failed||c->finished)return 0;try{uint64_t h=1469598103934665603ULL;const float*out=c->engine->output();for(size_t i=0;i<480;++i){uint32_t bits;std::memcpy(&bits,out+i,4);h=(h^bits)*1099511628211ULL;}return (h^c->index)*1099511628211ULL;}catch(...){return 0;}}
extern "C" int audio_native_measure(void*p,const float*pcm,uint64_t frames,uint64_t warm,uint64_t calls,uint64_t period,int paced,int counters,audio_observation*out){
 auto*c=static_cast<Context*>(p);if(!c||!pcm||!frames||frames>1000000||!c->enter())return EINVAL;Entry entry{c};try{r101::finite(pcm,size_t(frames)*480);Epoch e{c,pcm,frames};return audio_measure(callback,&e,warm,calls,period,paced,counters,out);}catch(...){return failed(c);}
}
