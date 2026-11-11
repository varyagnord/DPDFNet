#!/usr/bin/env python3
"""Fixed baseline-only audio pilot; builds happen in just before isolation."""
import argparse,hashlib,json,math,os,shlex,statistics,subprocess,sys
from pathlib import Path
from study import config as validate_manifest
from pmu import inventory
R=Path(__file__).resolve().parents[3]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):Path(p).write_text(json.dumps(x,indent=2)+'\n')
def main():
 p=argparse.ArgumentParser();p.add_argument('config');p.add_argument('output');a=p.parse_args();cfg=json.loads(Path(a.config).read_text());out=Path(a.output).resolve()
 required={'library','inputs','native_plugin','native_provenance','onnx_dir','cpu','calls','blocks','warmup','seed','profile_collectors'}
 if set(cfg)!=required:raise ValueError('Explicit bounded pilot configuration required')
 if cfg['calls']!=128 or cfg['blocks']!=4 or cfg['warmup']!=128:raise ValueError('This registered short pilot uses128 calls/warmup and4 pairs')
 if len(cfg['inputs'])!=2 or len(set(cfg['inputs']))!=2:raise ValueError('Two independent input files required')
 for key in ['library','native_plugin','native_provenance']:
  cfg[key]=str(Path(cfg[key]).resolve());assert Path(cfg[key]).is_file(),key
 cfg['inputs']=[str(Path(x).resolve()) for x in cfg['inputs']];cfg['onnx_dir']=str(Path(cfg['onnx_dir']).resolve())
 clock=R/'.local/bench-lab/libaudio_clock.so';worker=R/'.local/bench-lab/worker';assert clock.is_file() and worker.is_file()
 provenance=json.loads(Path(cfg['native_provenance']).read_text())
 if provenance['binary_sha256']!=sha(cfg['native_plugin']) or provenance['clock_sha256']!=sha(clock) or provenance['template_sha256']!=sha(Path(__file__).with_name('audio_native.rs')):
  raise ValueError('Native adapter/clock provenance mismatch; rebuild and revalidate before timing')
 for file in cfg['inputs']:
  if not Path(file).is_file():raise FileNotFoundError(file)
 if out.exists():raise FileExistsError(out)
 out.mkdir(parents=True);write(out/'config.json',cfg);write(out/'inventory.json',inventory())
 tools=Path(__file__).resolve().parent;wrappers={}
 for kind in ['buffered','native']:
  for counters in [False,True]:
   name=kind+('-counters' if counters else '');path=out/(name+'.sh');args=['/usr/bin/python3',str(tools/'audio_worker_v2.py'),'--clock',str(clock),'--adapter',kind,'--warmup',str(cfg['warmup'])]
   if kind=='native':args+=['--native-plugin',cfg['native_plugin'],'--onnx-dir',cfg['onnx_dir']]
   if counters:args+=['--counters']
   path.write_text('#!/bin/sh\nexec '+shlex.join(args)+' "$@"\n');path.chmod(0o700);wrappers[name]=str(path)
 source_files=[x for x in tools.iterdir() if x.suffix in ['.py','.c','.h','.rs']]
 extra=[str(x) for x in source_files]+[str(clock),cfg['native_plugin'],cfg['native_provenance'],str(Path(cfg['onnx_dir'])/'dpdfnet8_48khz_hr.onnx')]+list(wrappers.values())+[str(out/'config.json')]
 extra.append(str(Path(cfg['onnx_dir'])/'dpdfnet8_48khz_hr.weights.f32'))
 frozen={x:sha(x) for x in extra};write(out/'frozen-inputs.json',frozen)
 base=dict(schema_version=1,cpu=cfg['cpu'],frequency_khz='auto',ttl_seconds=1800,worker=str(worker),inputs=cfg['inputs'],variants={'same':dict(baseline=cfg['library'],candidate=cfg['library'])},models=[8],weights={str(x):str(R/f'optimized_inference/models/dpdfnet{x}_48khz_hr/weights.f32') for x in [2,8]},calls=dict(batch=512,continuous=256,paced=128),batch_size=16,aa_blocks=4,compare_blocks=4,aa_noise_limit_percent=.5,minimum_useful_gain_percent=.3,layout_profile='randomized',continuous_diagnostics=False,hardware_profiles=False,family_comparisons=12,extra_files=extra)
 conditions=[]
 for kind,path in [('legacy',str(tools/'audio_worker.py')),('buffered',wrappers['buffered']),('native',wrappers['native'])]:conditions.append(dict(id=kind,worker_mode='paced',period_ns=10000000,batch_size=1,calls=128,worker=path))
 jobs=[]
 for i,(power,idle) in enumerate([('steady','original'),('steady','shallow'),('boost','original'),('boost','shallow')]):
  m=dict(base,seed=cfg['seed']+i,power_profile=power,idle_policy=idle,conditions=conditions);name=power+'-'+idle;manifest=out/(name+'.json');write(manifest,m);validate_manifest(manifest);jobs.append(dict(name=name,manifest=str(manifest),output=str(out/name),mode='aa-session'))
 m=dict(base,seed=cfg['seed']+20,power_profile='boost',idle_policy='original',profile_collectors=cfg['profile_collectors'],profile_arms=['baseline'],profile_repetitions=1,profile_conditions=['buffered','native'],profile_calls={'buffered':64,'native':64},conditions=[dict(c,worker=wrappers[c['id']+'-counters']) for c in conditions if c['id']!='legacy']);manifest=out/'profiles.json';write(manifest,m);validate_manifest(manifest);jobs.append(dict(name='profiles',manifest=str(manifest),output=str(out/'profiles'),mode='profile-session'))
 plan=dict(kind='baseline-only-method-pilot',not_candidate_acceptance=True,model=8,cpu=cfg['cpu'],calls=128,blocks=4,warmup=128,processes=96,profile_jobs=2*len(cfg['profile_collectors']),primary_precision_cell='boost-original',decision='Preferred if bitwise equivalence passes and observed paired-log SD falls >=30% vs legacy without practical resolved AA drift; report all cells, small-sample uncertainty and failures. Native scope differs from NumPy; no cross-adapter speed claim. No extensions.',jobs=jobs)
 write(out/'plan.json',plan);progress=[]
 for job in jobs:
  with (out/(job['name']+'.log')).open('x') as log:status=subprocess.run(['/usr/bin/python3',str(tools/'study.py'),job['mode'],job['manifest'],job['output']],stdout=log,stderr=subprocess.STDOUT)
  restore=Path(job['output'])/'restore.json';restored=json.loads(restore.read_text()) if restore.exists() else None
  progress.append(dict(name=job['name'],returncode=status.returncode,restore=restored));write(out/'progress.json',progress);print('FINISH',job['name'],status.returncode,flush=True)
  if status.returncode or not restored or not restored['restored']:raise RuntimeError('Pilot failed; preserve journals and restore before diagnosis')
  if any(sha(k)!=v for k,v in frozen.items()):raise RuntimeError('Pilot input changed')
 cells=[]
 for job in jobs[:-1]:
  report=json.loads((Path(job['output'])/'aa/result.json').read_text());rows=[json.loads(s) for s in (Path(job['output'])/'aa/runs.jsonl').read_text().splitlines()]
  for c in report['conditions']:
   cell=[r for r in rows if r['mode']==c['mode']];means=[r['result']['mean_ms'] for r in cell]
   cells.append(dict(profile=job['name'],adapter=c['mode'],paired_log_sd=c['paired_log_sd'],aa_gain_percent=c['gain_percent'],aa_interval_percent=c['interval_percent'],process_mean_cv_percent=100*statistics.stdev(means)/statistics.mean(means),mean_ms=statistics.mean(means),minor_faults=sum(r['result']['minor_faults'] for r in cell),major_faults=sum(r['result']['major_faults'] for r in cell),wake_mean_ms=statistics.mean(r['result']['wakeup']['mean_ms'] for r in cell) if c['mode']!='legacy' else None))
 original={c['adapter']:c for c in cells if c['profile']=='boost-original'};precision={}
 for kind in ['buffered','native']:
  c=original[kind];ratio=c['paired_log_sd']/original['legacy']['paired_log_sd'];drift=(c['aa_interval_percent'][0]>0 or c['aa_interval_percent'][1]<0) and abs(c['aa_gain_percent'])>=.3
  precision[kind]=dict(observed_sd_ratio=ratio,observed_reduction_percent=100*(1-ratio),practical_drift_detected=drift,preferred_in_this_pilot=ratio<=.7 and not drift)
 write(out/'result.json',dict(cells=cells,precision=precision,small_pilot_only=True,not_candidate_acceptance=True,no_optional_extension=True,restorations_verified=True))
 print(json.dumps(precision))
if __name__=='__main__':main()
