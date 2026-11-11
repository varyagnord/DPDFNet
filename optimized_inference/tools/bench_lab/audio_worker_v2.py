#!/usr/bin/python3
"""Versioned audio worker: C cadence/timing, reusable buffers, separate wakeups."""
import os
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse,array,ctypes as ct,gc,hashlib,json,resource,statistics as stats,sys,time
from pathlib import Path
import numpy as np
from audio_worker import libc,feedback,perf_command,digest
from audio_pipeline import AudioPipeline
from audio_buffered import BufferedAudioPipeline
from dpdfnet import Model
from audio_protocol import Observation,CALLBACK,describe

class NativePipeline:
    def __init__(self,plugin,onnx_dir,library,model_id):
        self.lib=ct.CDLL(str(Path(plugin).resolve()))
        self.lib.audio_native_create.argtypes=[ct.c_char_p,ct.c_char_p];self.lib.audio_native_create.restype=ct.c_void_p
        self.lib.audio_native_step.argtypes=[ct.c_void_p,ct.POINTER(ct.c_float),ct.POINTER(ct.c_float)];self.lib.audio_native_step.restype=ct.c_int
        self.lib.audio_native_destroy.argtypes=[ct.c_void_p];self.lib.audio_native_destroy.restype=None
        model=Path(onnx_dir)/f'dpdfnet{model_id}_48khz_hr.onnx'
        self.handle=self.lib.audio_native_create(os.fsencode(Path(library).resolve()),os.fsencode(model.resolve()))
        if not self.handle:raise RuntimeError('Native DSP creation failed or native engine unavailable')
    def close(self):
        if self.handle:self.lib.audio_native_destroy(self.handle);self.handle=None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--clock',required=True);p.add_argument('--adapter',choices=['buffered','native'],default='buffered')
    p.add_argument('--warmup',type=int,default=128);p.add_argument('--warmup-mode',choices=['paced','continuous'],default='paced')
    p.add_argument('--counters',action='store_true');p.add_argument('--native-plugin');p.add_argument('--onnx-dir')
    p.add_argument('library');p.add_argument('model_id',type=int);p.add_argument('weights');p.add_argument('source')
    p.add_argument('calls',type=int);p.add_argument('mode');p.add_argument('batch',type=int);p.add_argument('output')
    a=p.parse_args()
    if not a.mode.startswith('paced:') or a.batch!=1 or not 16<=a.calls<=65536 or not 1<=a.warmup<=4096:p.error('Bounded individual paced audio required')
    period=int(a.mode.split(':')[1])
    if not 1000000<=period<=100000000:p.error('Invalid period')
    audio=np.fromfile(a.source,dtype='<f4')
    if not len(audio) or not np.isfinite(audio).all():p.error('Finite nonempty PCM required')
    clock=ct.CDLL(str(Path(a.clock).resolve()))
    clock.audio_measure.argtypes=[CALLBACK,ct.c_void_p,ct.c_uint64,ct.c_uint64,ct.c_uint64,ct.c_int,ct.c_int,ct.POINTER(Observation)]
    clock.audio_measure.restype=ct.c_int;clock.audio_counter_probe.restype=ct.c_int
    if a.counters and not clock.audio_counter_probe():raise RuntimeError('User-mode counters unavailable')
    if libc.prctl(29,1,0,0,0):raise OSError('Cannot set timerslack')
    ctl=ack=None
    if os.getenv('DPDF_PERF_CONTROL'):ctl=open(os.environ['DPDF_PERF_CONTROL'],'w');ack=open(os.environ['DPDF_PERF_ACK'],'rb',buffering=0)
    model=None;native=None;errors=[];index=0
    try:
        if a.adapter=='buffered':
            model=Model(a.library,a.weights,a.model_id);pipeline=BufferedAudioPipeline(model,audio)
            def process(i):pipeline.process(i)
        else:
            if not a.native_plugin or not a.onnx_dir:p.error('Native adapter requires plugin and model directory')
            native=NativePipeline(a.native_plugin,a.onnx_dir,a.library,a.model_id)
            # Precompute hop input and output buffers. The C-native worker below
            # will execute all DSP callbacks without a per-hop Python trampoline.
            frames=(len(audio)+479)//480+8;padded=np.pad(audio,(0,frames*480-len(audio)))
            inp=padded.ctypes.data_as(ct.POINTER(ct.c_float));out=np.empty(480,dtype=np.float32)
            native.lib.audio_native_measure.argtypes=[ct.c_void_p,ct.POINTER(ct.c_float),ct.c_uint64,ct.c_uint64,ct.c_uint64,ct.c_uint64,ct.c_int,ct.c_int,ct.POINTER(Observation)]
            native.lib.audio_native_measure.restype=ct.c_int
        records=(Observation*a.calls)()
        if a.adapter=='buffered':
            @CALLBACK
            def callback(opaque,ignored):
                nonlocal index
                try:process(index);index+=1;return 0
                except BaseException as e:errors.append(e);return -1
            def run(warm,calls,ptr,counters):return clock.audio_measure(callback,None,warm,calls,period,a.warmup_mode=='paced',counters,ptr)
        else:
            def run(warm,calls,ptr,counters):return native.lib.audio_native_measure(native.handle,inp,frames,warm,calls,period,a.warmup_mode=='paced',counters,ptr)
        gc.collect();gc.disable()
        rc=run(a.warmup,0,None,False)
        if rc or errors:raise RuntimeError(f'Warmup failed {rc}: {errors}')
        cpu=libc.sched_getcpu();ref0,del0=feedback(cpu);perf_command(ctl,ack,'enable')
        before=resource.getrusage(resource.RUSAGE_SELF);cpu0=time.thread_time_ns()
        rc=run(0,a.calls,records,a.counters)
        cpu1=time.thread_time_ns();after=resource.getrusage(resource.RUSAGE_SELF)
        perf_command(ctl,ack,'disable');ref1,del1=feedback(cpu)
        if rc or errors:raise RuntimeError(f'Measurement failed {rc}: {errors}')
        if libc.sched_getcpu()!=cpu:raise RuntimeError('Worker migrated')
        times=[r.body_ns/1e6 for r in records];wake=[(r.start_ns-r.scheduled_ns)/1e6 for r in records]
        response=[(r.finish_ns-r.scheduled_ns)/1e6 for r in records]
        Path(a.output).write_bytes(array.array('d',times).tobytes())
        details=[{name:int(getattr(r,name)) for name,_ in Observation._fields_} for r in records]
        sidecar=Path(a.output+'.timing.json');sidecar.write_text(json.dumps(dict(schema_version=2,clock='MONOTONIC schedule/start/finish; RAW body',observations=details))+'\n')
        if model:checksum=digest(model);address=hex(ct.cast(model.lib.dpdfnet_process,ct.c_void_p).value);state=hex(model.state.ctypes.data)
        else:
            native.lib.audio_native_digest.argtypes=[ct.c_void_p];native.lib.audio_native_digest.restype=ct.c_uint64
            checksum=f'{native.lib.audio_native_digest(native.handle):016x}';address=hex(ct.cast(native.lib.audio_native_step,ct.c_void_p).value);state=hex(native.handle)
        status=Path('/proc/self/status').read_text();nnp=int(next(x.split()[1] for x in status.splitlines() if x.startswith('NoNewPrivs:')))
        result=dict(cpu=cpu,pid=os.getpid(),uid=os.getuid(),no_new_privs=nnp,layout_randomization_disabled=bool(libc.personality(0xffffffff)&0x40000),api_address=address,state_address=state,
            reference_delta=ref1-ref0,delivered_delta=del1-del0,hardware_feedback_available=ref1>ref0 and del1>del0,
            schema_version=1,measurement_version=2,mode=a.mode,model=a.model_id,calls=a.calls,warmup=a.warmup,warmup_mode=a.warmup_mode,observations=a.calls,batch_size=1,observation_unit='call',
            **describe(times),cpu_ms_per_call=(cpu1-cpu0)/1e6/a.calls,over_10ms=sum(t>=10 for t in times),late=sum(r.finish_ns>r.scheduled_ns+period for r in records),
            voluntary_switches=after.ru_nvcsw-before.ru_nvcsw,involuntary_switches=after.ru_nivcsw-before.ru_nivcsw,minor_faults=after.ru_minflt-before.ru_minflt,major_faults=after.ru_majflt-before.ru_majflt,
            checksum=checksum,pipeline='buffered_numpy_fft_nn_ifft' if model else 'native_hushmic_dsp',numpy_version=np.__version__,period_ns=period,
            wakeup=describe(wake),response=describe(response),timing_sidecar_sha256=hashlib.sha256(sidecar.read_bytes()).hexdigest(),counter_diagnostics=a.counters,tail_upper_order_samples=a.calls-int(a.calls*.99))
        print(json.dumps(result))
    finally:
        if model:model.close()
        if native:native.close()
        if ctl:ctl.close();ack.close()
if __name__=='__main__':main()
