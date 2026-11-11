"""Audio timing invariants and independent per-frame reference comparisons."""
import ctypes as ct,importlib.util,os,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'optimized_inference/tools/bench_lab'),str(ROOT/'optimized_inference/examples')]
import audio_protocol as worker
try:
 import numpy as np
 from dpdfnet import Model
 from audio_pipeline import AudioPipeline
 from audio_buffered import BufferedAudioPipeline
except ImportError:np=None
class ClockContracts(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.clock=ct.CDLL(os.environ.get('DPDF_AUDIO_CLOCK',str(ROOT/'.local/bench-lab/libaudio_clock.so')))
  cls.clock.audio_measure.argtypes=[worker.CALLBACK,ct.c_void_p,ct.c_uint64,ct.c_uint64,ct.c_uint64,ct.c_int,ct.c_int,ct.POINTER(worker.Observation)]
 def test_counter_preparation_is_thread_process_and_pinned_cpu_bound(self):
  import threading
  original=os.sched_getaffinity(0)
  @worker.CALLBACK
  def cb(ctx,index):return 0
  out=(worker.Observation*4)()
  self.clock.audio_counter_probe.argtypes=[];self.clock.audio_counter_probe.restype=ct.c_int
  try:
   os.sched_setaffinity(0,{min(original)})
   if not self.clock.audio_counter_probe():self.skipTest('Single-CPU user RDPRU preparation unavailable')
   self.assertEqual(self.clock.audio_measure(cb,None,2,4,1000000,0,1,out),0)
   self.assertTrue(all(r.mperf>0 and r.aperf>0 for r in out))
   result=[]
   thread=threading.Thread(target=lambda:result.append(self.clock.audio_measure(cb,None,0,4,1000000,0,1,(worker.Observation*4)())))
   thread.start();thread.join(5);self.assertFalse(thread.is_alive());self.assertNotEqual(result,[0])
   # Use a fresh single-threaded interpreter, without NumPy/BLAS imports.
   import subprocess
   code='''import ctypes as c,os,sys
lib=c.CDLL(sys.argv[1]);callback=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_uint64)(lambda p,i:0)
lib.audio_measure.argtypes=[type(callback),c.c_void_p,c.c_uint64,c.c_uint64,c.c_uint64,c.c_int,c.c_int,c.c_void_p]
os.sched_setaffinity(0,{min(os.sched_getaffinity(0))});assert lib.audio_counter_probe()==1
out=c.create_string_buffer(192);pid=os.fork()
if not pid:os._exit(0 if lib.audio_measure(callback,None,0,4,1000000,0,1,out)!=0 else 1)
assert os.waitpid(pid,0)[1]==0
'''
   subprocess.run([sys.executable,'-S','-c',code,self.clock._name],check=True,timeout=10)
   if len(original)>1:
    os.sched_setaffinity(0,original)
    self.assertNotEqual(self.clock.audio_measure(cb,None,0,4,1000000,0,1,out),0)
   self.assertEqual(self.clock.audio_measure(cb,None,0,4,1000000,0,0,out),0)
  finally:os.sched_setaffinity(0,original)
 def test_native_builder_refuses_an_unbridged_engine_before_building(self):
  from unittest.mock import patch
  import build_audio_native
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);crate=root/'source/crates/hushmic-denoiser';crate.mkdir(parents=True);(crate/'Cargo.toml').write_text('[package]')
   clock=root/'clock';clock.mkdir();(clock/'libaudio_clock.so').write_bytes(b'fake')
   out=root/'output'
   with patch.object(sys,'argv',['builder','--hushmic-root',str(root/'source'),'--output',str(out),'--clock-dir',str(clock)]):
    with self.assertRaisesRegex(ValueError,'bridge'):build_audio_native.main()
   self.assertFalse(out.exists())
 def test_clock_writes_only_the_declared_output_records(self):
  class Guard(ct.Structure):_fields_=[('head',ct.c_uint64),('data',worker.Observation*4),('tail',ct.c_uint64)]
  g=Guard();g.head=0x12345678;g.tail=0xabcdef01
  @worker.CALLBACK
  def cb(ctx,index):return 0
  out=ct.cast(ct.byref(g,Guard.data.offset),ct.POINTER(worker.Observation))
  self.assertEqual(self.clock.audio_measure(cb,None,2,4,1000000,0,0,out),0)
  self.assertEqual((g.head,g.tail),(0x12345678,0xabcdef01))
 def test_paced_warmup_and_monotonic_response_are_recorded(self):
  indices=[]
  @worker.CALLBACK
  def cb(ctx,index):indices.append(index);return 0
  out=(worker.Observation*4)();self.assertEqual(self.clock.audio_measure(cb,None,2,4,1000000,1,0,out),0)
  self.assertEqual(indices,list(range(6)))
  for r in out:self.assertLessEqual(r.scheduled_ns,r.start_ns);self.assertLessEqual(r.start_ns,r.finish_ns);self.assertGreater(r.body_ns,0)
 def test_failure_and_invalid_configuration_are_not_successful_measurements(self):
  @worker.CALLBACK
  def cb(ctx,index):return -1
  out=(worker.Observation*4)();self.assertNotEqual(self.clock.audio_measure(cb,None,1,4,1000000,1,0,out),0)
  self.assertNotEqual(self.clock.audio_measure(cb,None,1,4,1,1,0,out),0)
 def test_warmup_only_has_no_output_and_exact_callback_count(self):
  calls=[]
  @worker.CALLBACK
  def cb(ctx,index):calls.append(index);return 0
  self.assertEqual(self.clock.audio_measure(cb,None,3,0,1000000,0,0,None),0);self.assertEqual(calls,[0,1,2])
 def test_timing_receipt_detects_changed_observations(self):
  import json,hashlib,array
  with tempfile.TemporaryDirectory() as d:
   raw=Path(d)/'x.f64';raw.write_bytes(array.array('d',[1.,1.]).tobytes())
   rows=[dict(scheduled_ns=10,start_ns=20,finish_ns=1000020,body_ns=1000000,aperf=0,mperf=0)]*2
   side=Path(str(raw)+'.timing.json');side.write_text(json.dumps(dict(observations=rows)))
   result=dict(measurement_version=2,calls=2,period_ns=10000000,late=0,timing_sidecar_sha256=hashlib.sha256(side.read_bytes()).hexdigest(),wakeup=worker.describe([.00001]*2),response=worker.describe([1.00001]*2))
   worker.validate_receipt(result,raw);side.write_text('{}')
   with self.assertRaises(ValueError):worker.validate_receipt(result,raw)
 def test_short_p99_is_explicitly_an_order_statistic(self):
  self.assertEqual(worker.describe(list(range(64)))['p99_ms'],63)
class NumericalContracts(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.lib=Path(os.environ.get('DPDF_AUDIO_TEST_LIBRARY',str(ROOT/'optimized_inference/build/libdpdfnet.so')))
  if os.getenv('DPDF_AUDIO_SKIP_NUMERICS'):raise unittest.SkipTest('Sanitized runtime is covered by native C contracts; use release shared library for Python adapter equivalence')
  supported=np is not None and np.lib.NumpyVersion(np.__version__)>=np.lib.NumpyVersion('2.0.0') and cls.lib.is_file() and cls.lib.read_bytes()[:4]==b'\x7fELF'
  if not supported:
   if os.getenv('DPDF_AUDIO_REQUIRE_NUMERICS'):raise RuntimeError('NumPy2 and a shared accepted library are required')
   raise unittest.SkipTest('NumPy2/shared library required; static configurations retain clock contracts')
 def test_rounding_ftz_daz_and_empty_spectra_keep_reference_bits(self):
  import subprocess
  with tempfile.TemporaryDirectory() as d:
   c=Path(d)/'fp.c';so=Path(d)/'fp.so'
   c.write_text('#include <xmmintrin.h>\nunsigned get(void){return _mm_getcsr();} void set(unsigned x){_mm_setcsr(x);}')
   subprocess.run(['/usr/bin/gcc','-shared','-fPIC',str(c),'-o',str(so)],check=True)
   fp=ct.CDLL(str(so));fp.get.restype=ct.c_uint;fp.set.argtypes=[ct.c_uint];original=fp.get()
   patterns=[np.zeros(480*4,dtype=np.float32),np.full(480*4,.01,dtype=np.float32),np.full(480*4,2**-120,dtype=np.float32)]
   try:
    with np.errstate(all='ignore'):
     for mode in range(4):
      for denorm in range(4):
       fp.set((original&~0xe040)|(mode<<13)|(0x8000 if denorm&1 else 0)|(0x40 if denorm&2 else 0))
       for size in [2,8]:
        weights=ROOT/f'optimized_inference/models/dpdfnet{size}_48khz_hr/weights.f32'
        for audio in patterns:
         with Model(self.lib,weights,size) as old,Model(self.lib,weights,size) as new:
          a=AudioPipeline(old,audio);b=BufferedAudioPipeline(new,audio)
          for i in range(6):
           x=a.process(i).copy();y=b.process(i)
           self.assertEqual(x.tobytes(),y.tobytes());self.assertEqual(a.last_input.tobytes(),b.last_input.tobytes());self.assertEqual(old.state.tobytes(),new.state.tobytes())
   finally:fp.set(original)
 def test_buffers_are_reused_with_exact_spectra_pcm_and_states(self):
  rng=np.random.default_rng(41);audio=rng.standard_normal(480*24).astype(np.float32)
  for size in [2,8]:
   weights=ROOT/f'optimized_inference/models/dpdfnet{size}_48khz_hr/weights.f32'
   with Model(self.lib,weights,size) as old,Model(self.lib,weights,size) as new:
    a=AudioPipeline(old,audio);b=BufferedAudioPipeline(new,audio);identity=b.spectrum.ctypes.data
    for i in range(40):
     x=a.process(i).copy();y=b.process(i)
     self.assertEqual(x.tobytes(),y.tobytes());self.assertEqual(a.last_input.tobytes(),b.last_input.tobytes());self.assertEqual(old.state.tobytes(),new.state.tobytes());self.assertEqual(identity,b.spectrum.ctypes.data)
    new.close()
    with self.assertRaises(RuntimeError):b.process(0)
if __name__=='__main__':unittest.main()
