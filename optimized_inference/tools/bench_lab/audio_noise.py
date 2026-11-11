#!/usr/bin/python3
"""Baseline-only idle/IRQ/package diagnostics through the standard lifecycle."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
from audio_pilot import sha, write, R
from study import config as validate_manifest
from audio_noise_report import report


def manifests(cfg, out):
    required={'library','inputs','native_plugin','native_provenance','onnx_dir','cpus','seed'}
    if set(cfg)!=required:raise ValueError('Explicit diagnostic configuration required')
    if not isinstance(cfg['cpus'],list) or not 1<=len(cfg['cpus'])<=2 or len(set(cfg['cpus']))!=len(cfg['cpus']) or any(type(x)!=int or x<0 for x in cfg['cpus']):
        raise ValueError('Use1..2 unique CPU IDs')
    if len(cfg['inputs'])!=2 or len(set(cfg['inputs']))!=2:raise ValueError('Two distinct PCM fixtures required')
    tools=Path(__file__).resolve().parent
    clock=R/'.local/bench-lab/libaudio_clock.so';worker=R/'.local/bench-lab/worker'
    provenance=json.loads(Path(cfg['native_provenance']).read_text())
    if provenance['binary_sha256']!=sha(cfg['native_plugin']) or provenance['clock_sha256']!=sha(clock) or provenance['template_sha256']!=sha(tools/'audio_native.rs'):
        raise ValueError('Native adapter provenance mismatch')
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    write(out/'config.json',cfg)
    wrapper=out/'native-counters.sh'
    wrapper.write_text('#!/bin/sh\nexec '+shlex.join(['/usr/bin/python3',str(tools/'audio_worker_v2.py'),
        '--clock',str(clock),'--adapter','native','--warmup','128','--counters',
        '--native-plugin',cfg['native_plugin'],'--onnx-dir',cfg['onnx_dir']])+' "$@"\n')
    wrapper.chmod(0o700)
    extra=[str(x) for x in tools.iterdir() if x.suffix in ['.py','.c','.h','.rs']]
    extra += [str(clock),cfg['native_plugin'],cfg['native_provenance'],str(wrapper),str(out/'config.json')]
    for model in [2,8]:
        for suffix in ['onnx','weights.f32']:extra.append(str(Path(cfg['onnx_dir'])/f'dpdfnet{model}_48khz_hr.{suffix}'))
    collectors=[dict(id='idle-sched-irq',kind='trace',scope='cpu',required=True,
                    events=['power:cpu_idle','sched:sched_wakeup','sched:sched_switch','irq:irq_handler_entry','irq:irq_handler_exit'],
                    reason='Correlate requested idle state and scheduler/IRQ events with MONOTONIC callback boundaries'),
                dict(id='softirq',kind='trace',scope='cpu',required=True,
                    events=['irq:softirq_entry','irq:softirq_exit'],reason='Separate softirq interruption diagnostic'),
                dict(id='clocks',kind='stat',required=True,events=['cycles','instructions','ref-cycles'],
                    reason='Unfiltered task clocks, with per-callback APERF/MPERF and package telemetry; diagnostic only'),
                dict(id='probe-syscalls',kind='stat',required=True,
                    events=['syscalls:sys_enter_fork','syscalls:sys_enter_clone','syscalls:sys_enter_clone3'],
                    reason='Verify permission preparation never forks/clones inside the warmed window')]
    base=dict(schema_version=1,frequency_khz='auto',ttl_seconds=600,worker=str(worker),inputs=cfg['inputs'],
              variants={'same':dict(baseline=cfg['library'],candidate=cfg['library'])},models=[8],
              weights={str(x):str(R/f'optimized_inference/models/dpdfnet{x}_48khz_hr/weights.f32') for x in [2,8]},
              calls=dict(batch=512,continuous=256,paced=128),batch_size=16,aa_blocks=4,compare_blocks=4,
              aa_noise_limit_percent=.5,minimum_useful_gain_percent=.3,layout_profile='randomized',
              continuous_diagnostics=False,hardware_profiles=True,family_comparisons=4,extra_files=extra,
              conditions=[dict(id='native',worker=str(wrapper),worker_mode='paced',calls=128,batch_size=1,period_ns=10000000)],
              profile_collectors=collectors,profile_conditions=['native'],profile_arms=['baseline'],profile_repetitions=1)
    jobs=[]
    for cpu in cfg['cpus']:
        for power,idle in [('boost','original'),('steady','shallow')]:
            name=f'cpu{cpu}-{power}-{idle}';manifest=out/(name+'.json')
            m=dict(base,cpu=cpu,power_profile=power,idle_policy=idle,seed=cfg['seed']+len(jobs))
            write(manifest,m);validate_manifest(manifest)
            jobs.append(dict(name=name,manifest=str(manifest),output=str(out/name)))
    write(out/'plan.json',dict(kind='baseline-only-noise-diagnostics',profile_jobs=len(collectors)*len(jobs),
          measured_calls=128,paced_warmup=128,no_candidate_or_speed_inference=True,
          policy_order_fixed=True,telemetry_interval_seconds=.2,window_clock='MONOTONIC',jobs=jobs))
    frozen={p:sha(p) for p in extra};write(out/'frozen-inputs.json',frozen)
    return jobs,frozen


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('config');p.add_argument('output');a=p.parse_args()
    out=Path(a.output).resolve();jobs,frozen=manifests(json.loads(Path(a.config).read_text()),out);progress=[]
    for job in jobs:
        with (out/(job['name']+'.log')).open('x') as log:
            rc=subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('study.py')),'profile-session',job['manifest'],job['output']],stdout=log,stderr=subprocess.STDOUT).returncode
        restore=Path(job['output'])/'restore.json';receipt=json.loads(restore.read_text()) if restore.exists() else None
        progress.append(dict(name=job['name'],returncode=rc,restore=receipt));write(out/'progress.json',progress)
        print('FINISH',job['name'],rc,flush=True)
        if rc or not receipt or not receipt['restored']:raise RuntimeError('Diagnostic failed; retain journals and investigate')
        if any(sha(k)!=v for k,v in frozen.items()):raise RuntimeError('Frozen diagnostic source changed')
    summary=report(out)
    write(out/'result.json',dict(completed=True,profile_jobs=summary['profile_jobs'],restorations_verified=True,not_speed_evidence=True,
                               warmed_probe_syscalls_zero=summary['warmed_probe_syscalls_zero']))
    print((out/'REPORT.md').read_text(),flush=True)


if __name__=='__main__':main()
