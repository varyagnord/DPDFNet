#!/usr/bin/python3
"""Offline diagnostic report; raw timestamps/traces are never speed evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import pmu
import audio_protocol


def report(path):
    out=Path(path).resolve();plan=json.loads((out/'plan.json').read_text());cells=[]
    for job in plan['jobs']:
        folder=Path(job['output']);restore=json.loads((folder/'restore.json').read_text())
        if not restore['restored']:raise ValueError('Diagnostic restoration failed')
        for line in (folder/'profiles/hardware.jsonl').read_text().splitlines():
            r=json.loads(line)
            if r['status']!='collected':raise ValueError('Incomplete diagnostic collector')
            stem=folder/'profiles'/f"{r['index']:03d}-{r['collector']['id']}"
            raw=folder/'profiles/samples'/f"{r['index']:03d}.f64";w=r['worker']
            audio_protocol.validate_receipt(w,raw)
            observations=json.loads(Path(str(raw)+'.timing.json').read_text())['observations']
            telemetry=json.loads(stem.with_suffix('.telemetry.json').read_text())
            if not telemetry['sampler_stopped'] or telemetry['error']:raise ValueError('Telemetry incomplete')
            ratios=[a['aperf']/a['mperf'] for a in observations if a['mperf']>0]
            if len(ratios)!=len(observations):raise ValueError('Missing diagnostic clock deltas')
            cell=dict(cell=job['name'],collector=r['collector']['id'],mean_ms=w['mean_ms'],sample_sd_ms=w['sample_sd_ms'],
                      wake_mean_us=w['wakeup']['mean_ms']*1000,minor_faults=w['minor_faults'],major_faults=w['major_faults'],late=w['late'],
                      aperf_mperf=dict(min=min(ratios),max=max(ratios),mean=statistics.mean(ratios),sample_sd=statistics.stdev(ratios)),
                      counters_per_call=r.get('counter_values_per_call'),sensor_availability=telemetry['samples'][0]['availability'],
                      host_ac=telemetry['samples'][0].get('host_ac',[]),cpu_busy_percent=telemetry['cpu_busy_percent'],sensors={})
            for key,v in telemetry['samples'][0]['values'].items():
                if v['unit'] in ['millidegree_C_or_driver_mV','microwatt','percent','count']:
                    values=[x['values'][key]['value'] for x in telemetry['samples'] if key in x['values']]
                    cell['sensors'][key]=dict(min=min(values),max=max(values),unit=v['unit'])
            if r['collector']['kind']=='trace':
                if pmu.sha(stem.with_suffix('.data'))!=r['data_sha256']:raise ValueError('Raw trace hash mismatch')
                traces=pmu.parse_trace(stem.with_suffix('.samples.txt').read_text(),w['cpu'],r['collector']['events'])
                t=pmu.trace_summary(traces,observations,w['pid'])
                cell['trace']=dict(event_counts=t['event_counts'],idle_states=t['idle_states'],
                    body_switch_outs=sum(c['body_switch_outs'] for c in t['calls']),
                    body_hardirq_overlap_us=sum(c['body_irq_overlap_us'] for c in t['calls']),
                    body_softirq_overlap_us=sum(c['body_softirq_overlap_us'] for c in t['calls']))
            cells.append(cell)
    if len(cells)!=plan['profile_jobs']:raise ValueError('Diagnostic job count mismatch')
    probes=[c for c in cells if c['collector']=='probe-syscalls']
    no_fork=bool(probes) and all(all(v==0 for v in c['counters_per_call'].values()) for c in probes)
    if probes and not no_fork:raise ValueError('Fork/clone observed inside warmed diagnostic window')
    summary=dict(profile_jobs=len(cells),cells=cells,warmed_probe_syscalls_zero=no_fork if probes else None,
                 restoration_verified=True,not_speed_evidence=True,analysis_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    pmu.write_json(out/'summary.json',summary)
    lines=['# Audio noise diagnostics','','Baseline only. Diagnostic instrumentation perturbs latency; these are not speed comparisons.',
           'Fixed cross-policy order; no causal power/temperature conclusion. APERF/MPERF is a dimensionless diagnostic ratio.',
           'Missing sensors do not exclude throttling; amdgpu power has an unspecified shared domain. Peripheral batteries are not host AC.',
           'Device IRQ events do not cover all local APIC/NMI/firmware interruptions. Cross-CPU wakeups may be absent.','',
           '| Cell | Pass | Body mean / sample SD, ms | Wake mean, us | Minor faults | APERF/MPERF range |',
           '|---|---|---:|---:|---:|---:|']
    for c in cells:lines.append(f"| {c['cell']} | {c['collector']} | {c['mean_ms']:.4f} / {c['sample_sd_ms']:.4f} | {c['wake_mean_us']:.1f} | {c['minor_faults']} | {c['aperf_mperf']['min']:.3f}..{c['aperf_mperf']['max']:.3f} |")
    lines+=['',f"Warmed fork/clone/clone3 guards: {no_fork if probes else 'not collected in this historical cohort'}. All session restoration receipts verified.",
            'See summary.json for CPU background activity, sensors, trace counts and callback overlaps. No optional sample extension.','']
    (out/'REPORT.md').write_text('\n'.join(lines))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output');args=p.parse_args();report(args.output)
