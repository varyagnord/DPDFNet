"""Versioned, preregistered workload-specific decisions; legacy reports stay intact."""
import math
import statistics
from compare_benchmarks import student_t_quantile

FIELDS = {'version', 'roles', 'minimum_gain_percent', 'mean_loss_margin_percent',
          'tail_loss_margin_percent', 'aa_drift_percent', 'family_comparisons', 'model_roles'}


def validate(policy, conditions, models=(2, 8), variants=1):
    if set(policy) != FIELDS or policy['version'] != 2:
        raise ValueError('Acceptance policy v2 needs explicit fields')
    if set(policy['roles']) != {c['id'] for c in conditions} or not set(policy['roles'].values()) <= {'throughput', 'audio', 'guard'}:
        raise ValueError('Declare one acceptance role per condition')
    if not isinstance(policy['model_roles'], dict) or not set(policy['model_roles']) <= {'2','8'} or not set(policy['model_roles'].values()) <= {'guard'}:
        raise ValueError('Model overrides can only add noninferiority guards')
    for name, hi in [('minimum_gain_percent', 5), ('mean_loss_margin_percent', 5),
                     ('tail_loss_margin_percent', 10), ('aa_drift_percent', 5)]:
        x = policy[name]
        if type(x) not in (int, float) or not math.isfinite(x) or not 0 < x <= hi:
            raise ValueError('Invalid practical threshold: ' + name)
    if type(policy['family_comparisons']) is not int or policy['family_comparisons'] < 1:
        raise ValueError('Declare the full v2 endpoint family')
    endpoints = variants * sum(1 if policy['model_roles'].get(str(model), policy['roles'][c['id']]) == 'throughput' else 2
                               for model in models for c in conditions)
    if policy['family_comparisons'] < endpoints:
        raise ValueError('V2 family cannot omit registered mean/tail endpoints')


def interval(logs, family):
    center = statistics.mean(logs)
    half = student_t_quantile(1-.05/(2*family), len(logs)-1)*statistics.stdev(logs)/math.sqrt(len(logs))
    return [100*(1-math.exp(center+half)), 100*(1-math.exp(center-half))]


def decision(policy, role, mean_gain, mean_ci, aa_gain, aa_ci, tail_ci, clean):
    # A wide A/A interval does not prove bias, equivalence or no bias. An
    # independently resolved practical order drift invalidates this cell.
    drift = (aa_ci[0] > 0 or aa_ci[1] < 0) and abs(aa_gain) >= policy['aa_drift_percent']
    ni = mean_ci[0] > -policy['mean_loss_margin_percent']
    tail_ni = tail_ci[0] > -policy['tail_loss_margin_percent']
    useful = mean_gain >= policy['minimum_gain_percent'] and mean_ci[0] > 0
    passed = clean and not drift and (useful if role == 'throughput' else ni and tail_ni)
    return dict(version=2, role=role, aa_practical_drift_detected=drift,
                aa_precision_is_diagnostic=True, mean_noninferiority=ni,
                process_p99_noninferiority=tail_ni, useful_mean_gain=useful,
                deadline_fault_guard=clean, passed=passed,
                interpretation='throughput superiority' if role == 'throughput' else 'mean and per-process p99 noninferiority; not population p99 or WCET')


def evaluate(policy, rows, controls, conditions):
    control = {(r['isa'],r['model'],r['mode']):r for r in controls['conditions']}
    for c in conditions:
        key = c['isa'],c['model'],c['mode']
        cell = [r for r in rows if (r['isa'],r['model'],r['mode']) == key]
        logs = {'mean_ms':[], 'p99_ms':[]}
        for block in sorted({r['block'] for r in cell}):
            pair = {r['label']:r['result'] for r in cell if r['block']==block}
            for field in logs:
                a,b = pair['A'][field],pair['B'][field]
                if not math.isfinite(a) or not math.isfinite(b) or min(a,b)<=0:
                    raise ValueError('Invalid paired endpoint')
                logs[field].append(math.log(b/a))
        mean_ci = interval(logs['mean_ms'],policy['family_comparisons'])
        tail_ci = interval(logs['p99_ms'],policy['family_comparisons'])
        aa = control[key]
        role = policy['roles'][c['mode']]
        if str(c['model']) in policy['model_roles']:role=policy['model_roles'][str(c['model'])]
        clean = all(not a['late'] and not a['over_10ms'] and not a['major_faults'] for a in c['arms'].values())
        verdict = decision(policy,role,c['gain_percent'],mean_ci,aa['gain_percent'],aa['interval_percent'],tail_ci,clean)
        verdict.update(mean_interval_percent=mean_ci,process_p99_interval_percent=tail_ci,
                       family_comparisons=policy['family_comparisons'])
        c['workload_acceptance'] = verdict
