#!/usr/bin/env python3
"""Render a completed immutable A/A audio pilot without changing verdicts."""
from pathlib import Path
import argparse,json

def main():
 p=argparse.ArgumentParser();p.add_argument('output');a=p.parse_args();out=Path(a.output).resolve();j=json.loads((out/'result.json').read_text())
 lines=['# Versioned audio measurement A/A pilot','', 'One unchanged runtime, model8, one fast core; four pairs per adapter/policy. These are diagnostic precision observations, not candidate speed gains or universal variance guarantees.','', '| Power / idle | Adapter | Paired log SD % | A/A point % | Mean ms | Minor faults |','|---|---|---:|---:|---:|---:|']
 for c in j['cells']:lines.append(f"| {c['profile']} | {c['adapter']} | {c['paired_log_sd']*100:.3f} | {c['aa_gain_percent']:+.3f} | {c['mean_ms']:.5f} | {c['minor_faults']} |")
 lines+=['','## Preregistered original-idle Boost comparison','']
 for kind,c in j['precision'].items():lines.append(f"- {kind}: observed paired SD reduction {c['observed_reduction_percent']:.1f}%; preferred in this pilot: {c['preferred_in_this_pilot']}; resolved practical drift: {c['practical_drift_detected']}.")
 lines+=['','Reduced variance is not itself adequate precision for a1% optimization or proof of no bias. The four power/idle cells ran in fixed order: cross-policy differences can include time/package effects. Do not pool them or turn off deep idle as a universal production recommendation.','', 'Native HushMic and NumPy are different DSP frontends. Their absolute runtimes cannot identify a neural-kernel speedup. Buffered NumPy preserves the independent reference numerical contract; native DSP has its own reference/reset checks.','', 'Warmup and acquisition share cadence; body duration, wakeup and deadline response are distinct. Per-process p99 on128 calls is the second-largest observation, not population p99 or WCET certification. Call/process SD and all raw/sidecar records remain retained.','', 'Every session must have a successful restore receipt; independent readback and numerical receipts are retained by the enclosing study. No production plugin, runtime defaults or PR publication follow automatically.','']
 (out/'RESULTS.md').write_text('\n'.join(lines))
if __name__=='__main__':main()
