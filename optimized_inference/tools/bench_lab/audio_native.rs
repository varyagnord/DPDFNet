//! Test-only adapter to the real HushMic DSP. Not part of libdpdfnet.
use hushmic_denoiser::{Denoiser, Engine, Inference, HOP};
use std::{ffi::{c_char,c_void,CStr},panic::{catch_unwind,AssertUnwindSafe},ptr};
#[repr(C)] pub struct Observation {scheduled_ns:u64,start_ns:u64,finish_ns:u64,body_ns:u64,aperf:u64,mperf:u64}
extern "C" {
 fn audio_measure(callback:extern "C" fn(*mut c_void,u64)->i32,context:*mut c_void,warmup:u64,calls:u64,period:u64,paced:i32,counters:i32,out:*mut Observation)->i32;
}
struct Context {denoiser:Denoiser,index:usize,output:[f32;HOP]}
#[no_mangle] pub unsafe extern "C" fn audio_native_create(library:*const c_char,model:*const c_char)->*mut c_void {
 catch_unwind(AssertUnwindSafe(|| {
  if library.is_null()||model.is_null(){return ptr::null_mut();}
  let library=CStr::from_ptr(library).to_str().unwrap();let model=CStr::from_ptr(model).to_str().unwrap();
  std::env::set_var("DPDF_QA_LIBRARY",library);
  let Ok(denoiser)=Denoiser::from_file_with(model,Inference::NativeInt8) else{return ptr::null_mut();};
  if denoiser.engine()!=Engine::NativeInt8 || denoiser.fallback_reason().is_some(){return ptr::null_mut();}
  Box::into_raw(Box::new(Context{denoiser,index:0,output:[0.;HOP]})) as *mut c_void
 })).unwrap_or(ptr::null_mut())
}
#[no_mangle] pub unsafe extern "C" fn audio_native_destroy(p:*mut c_void){if !p.is_null(){drop(Box::from_raw(p as *mut Context));}}
#[no_mangle] pub unsafe extern "C" fn audio_native_reset(p:*mut c_void)->i32 {
 catch_unwind(AssertUnwindSafe(||{if p.is_null(){return -1;}let c=&mut *(p as *mut Context);c.denoiser.reset();c.index=0;c.output.fill(0.);0})).unwrap_or(-1)
}
#[no_mangle] pub unsafe extern "C" fn audio_native_step(p:*mut c_void,input:*const f32,output:*mut f32)->i32 {
 catch_unwind(AssertUnwindSafe(|| {
  if p.is_null()||input.is_null()||output.is_null(){return -1;}
  let c=&mut *(p as *mut Context);let input=&*(input as *const [f32;HOP]);
  if c.denoiser.process_hop(input,&mut c.output).is_err(){return -1;}
  ptr::copy_nonoverlapping(c.output.as_ptr(),output,HOP);c.index+=1;0
 })).unwrap_or(-1)
}
struct Epoch {context:*mut Context,pcm:*const f32,frames:usize}
extern "C" fn callback(p:*mut c_void,_index:u64)->i32 {
 catch_unwind(AssertUnwindSafe(|| unsafe {
  let e=&mut *(p as *mut Epoch);let c=&mut *e.context;
  let input=&*(e.pcm.add((c.index%e.frames)*HOP) as *const [f32;HOP]);
  if c.denoiser.process_hop(input,&mut c.output).is_err(){return -1;}
  c.index+=1;0
 })).unwrap_or(-1)
}
#[no_mangle] pub unsafe extern "C" fn audio_native_measure(p:*mut c_void,pcm:*const f32,frames:u64,warm:u64,calls:u64,period:u64,paced:i32,counters:i32,out:*mut Observation)->i32 {
 if p.is_null()||pcm.is_null()||frames==0||frames>usize::MAX as u64/480{return 22;}
 let mut epoch=Epoch{context:p as *mut Context,pcm,frames:frames as usize};
 audio_measure(callback,&mut epoch as *mut Epoch as *mut c_void,warm,calls,period,paced,counters,out)
}
#[no_mangle] pub unsafe extern "C" fn audio_native_digest(p:*mut c_void)->u64 {
 if p.is_null(){return 0;}let c=&*(p as *mut Context);let mut h=1469598103934665603u64;
 for x in c.output{h=(h^x.to_bits() as u64).wrapping_mul(1099511628211);}
 (h^c.index as u64).wrapping_mul(1099511628211)
}
