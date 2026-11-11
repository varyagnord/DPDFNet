"""Bounded, manifest-defined profiling through the existing lab lifecycle.

No global configuration changes. Perf alone runs privileged; the common
controller enters the prepared partition and drops workload privileges.
"""
import hashlib
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import subprocess
import statistics
import telemetry
import audio_protocol

PERF = '/usr/bin/perf'
TRACE_EVENTS = {'power:cpu_idle', 'sched:sched_wakeup', 'sched:sched_switch',
                'irq:irq_handler_entry', 'irq:irq_handler_exit', 'irq:softirq_entry',
                'irq:softirq_exit'}

def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(collectors):
    if not isinstance(collectors, list) or not 1 <= len(collectors) <= 32:
        raise ValueError('Use 1..32 explicit profiling collectors')
    ids = set()
    allowed = {'id', 'kind', 'events', 'required', 'reason', 'period',
               'frequency', 'branches', 'memory', 'scope', 'pmu'}
    for c in collectors:
        if not isinstance(c, dict) or set(c) - allowed:
            raise ValueError('Unknown profiling collector fields')
        name = c.get('id', '')
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}', name) or name in ids:
            raise ValueError('Invalid/duplicate profiling collector ID')
        ids.add(name)
        if c.get('kind') not in ('stat', 'record', 'trace') or not c.get('reason'):
            raise ValueError('Collector needs kind and applicability reason')
        events = c.get('events')
        if not isinstance(events, list) or not 1 <= len(events) <= 6:
            raise ValueError('Use 1..6 explicit events per collector')
        if any(not isinstance(e, str) or not re.fullmatch(r'[a-zA-Z0-9_][a-zA-Z0-9_./,:=+-]*', e) for e in events):
            raise ValueError('Invalid perf event expression')
        if len(events) != len(set(events)):
            raise ValueError('Duplicate events')
        if c['kind'] == 'record' and len(events) != 1:
            raise ValueError('Separate sampling sources into independent passes')
        if c['kind'] == 'trace':
            if not set(events) <= TRACE_EVENTS or c.get('scope') != 'cpu':
                raise ValueError('Trace needs whitelisted tracepoints and explicit cpu scope')
            if any(k in c for k in ('period','frequency','branches','memory','pmu')):
                raise ValueError('Trace records every event with fixed MONOTONIC clock')
        if 'required' in c and not isinstance(c['required'], bool):
            raise ValueError('required must be boolean')
        if c.get('scope', 'task') not in ('task', 'shared-pmu', 'cpu'):
            raise ValueError('Invalid PMU scope')
        if c.get('scope') == 'cpu' and c['kind'] != 'trace':
            raise ValueError('CPU scope is reserved for bounded tracing')
        if c.get('scope') == 'shared-pmu' and not re.fullmatch(r'[a-zA-Z0-9_]+', c.get('pmu', '')):
            raise ValueError('Shared PMU needs a sysfs device name')
        if c['kind'] == 'stat' and any(k in c for k in ('period', 'frequency', 'memory', 'branches')):
            raise ValueError('Sampling fields on stat collector')
        if c['kind'] == 'record':
            if ('period' in c) == ('frequency' in c):
                raise ValueError('Select exactly one bounded sampling period/frequency')
            key = 'period' if 'period' in c else 'frequency'
            lo, hi = (10000, 10000000) if key == 'period' else (19, 2000)
            if type(c[key]) is not int or not lo <= c[key] <= hi:
                raise ValueError('Unbounded sampling rate')
            if c.get('branches') not in (None, 'any,u'):
                raise ValueError('Unsupported branch filter')
            if 'memory' in c and not isinstance(c['memory'], bool):
                raise ValueError('memory must be boolean')
    return collectors


def inventory(root=Path('/sys/bus/event_source/devices')):
    sources = {}
    for p in sorted(root.iterdir()):
        entry = {}
        for group in ('caps', 'format', 'events'):
            entry[group] = {f.name: f.read_text().strip() for f in sorted((p/group).glob('*')) if f.is_file()}
        for name in ('type', 'cpumask'):
            if (p/name).is_file():
                entry[name] = (p/name).read_text().strip()
        sources[p.name] = entry
    cpuinfo = Path('/proc/cpuinfo').read_text()
    info = {k: re.findall(r'^' + re.escape(k) + r'\s*:\s*(.*)$', cpuinfo, re.M)
            for k in ('model name', 'cpu family', 'model', 'stepping', 'microcode', 'flags')}
    return {'kernel': platform.release(), 'cpuinfo': info, 'pmus': sources,
            'perf_version': subprocess.check_output([PERF, 'version'], text=True).strip(),
            'perf_event_paranoid': Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip(),
            'advertisement_only': True}


def validate_manifest(m):
    validate(m['profile_collectors'])
    arms = m.get('profile_arms', ['baseline', 'candidate'])
    if not arms or len(set(arms)) != len(arms) or not set(arms) <= {'baseline', 'candidate'}:
        raise ValueError('Invalid profile arms')
    reps = m.get('profile_repetitions', 2)
    if type(reps) is not int or not 1 <= reps <= 3:
        raise ValueError('Use 1..3 fixed profiling repetitions')
    selected = m.get('profile_conditions', [])
    specs = [c for c in m.get('conditions', []) if c['id'] in selected]
    if not specs or len(set(selected)) != len(selected) or set(selected) != {c['id'] for c in specs}:
        raise ValueError('Explicit valid profile_conditions required')
    for c in specs:
        n = m.get('profile_calls', {}).get(c['id'], c['calls'])
        b = c.get('batch_size', 1)
        if type(n) is not int or not 16 <= n <= 65536 or n % b or n//b < 2:
            raise ValueError('Invalid bounded profiling call count')
        if any(x['kind']=='trace' for x in m['profile_collectors']):
            if c['worker_mode'] != 'paced' or n*c.get('period_ns',10000000)>30000000000:
                raise ValueError('CPU trace requires paced windows of at most30 seconds')
    jobs = len(m.get('models', [2])) * len(m.get('variants', {'default': {}})) * len(arms) * len(specs)
    jobs *= sum(reps if c['kind'] == 'stat' else 1 for c in m['profile_collectors'])
    if jobs > 512:
        raise ValueError('Split profiling plans into sessions of at most 512 jobs')


def cpulist(value):
    result = set()
    for part in value.split(','):
        bounds = [int(n) for n in part.split('-')]
        if len(bounds) not in (1, 2):
            raise ValueError('Invalid PMU CPU list')
        result.update(range(bounds[0], bounds[-1]+1))
    return result


def parse_counters(text, expected):
    counters = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
    if len(counters) != expected:
        raise RuntimeError('Unexpected PMU counter count')
    for c in counters:
        value = float(c['counter-value'])
        running = float(c['pcnt-running'])
        runtime = float(c['event-runtime'])
        if not math.isfinite(value) or value < 0 or not math.isfinite(running) or running < 99.9 or not math.isfinite(runtime) or runtime <= 0:
            raise RuntimeError('Unsupported, invalid or multiplexed PMU counter')
    return counters


def unavailable_reason(log):
    # Do not turn arbitrary workload failures/timeouts into optional PMU skips.
    if not any(s in log for s in ('event syntax error', 'perf_event_open', 'No permission to enable',
                                  'Error:\n', 'perf_event_mlock')):
        return None
    markers = ('event syntax error', 'not supported', 'not counted', 'Permission denied',
               'No permission', 'Operation not permitted', 'Invalid argument',
               'does not support', 'failed to mmap', 'No such device')
    return next((s for s in markers if s.lower() in log.lower()), None)


def sample_count(text):
    if 'PERF_RECORD_LOST' in text:
        raise RuntimeError('Lost hardware samples')
    return sum(bool(line.strip()) for line in text.splitlines())


def memory_summary(text):
    levels = Counter()
    weights = []
    periods = Counter()
    unparsed = 0
    loads = 0
    for line in text.splitlines():
        if '|OP LOAD|' not in line:
            continue
        loads += 1
        level = re.search(r'\|LVL ([^|]+)', line)
        tail = re.search(r'\|BLK\s+.*?\s+(\d+)\s+[0-9a-f]+\s+[^()]+\s+\([^()]*\)\s*$', line)
        period = re.match(r'\s*(\d+)\s', line)
        if not (level and tail and period):
            unparsed += 1
            continue
        levels[level[1].strip()] += 1
        periods[int(period[1])] += 1
        if int(tail[1]) > 0:
            weights.append(int(tail[1]))
    return dict(observed_load_samples=loads, unparsed_load_samples=unparsed, sources=dict(levels),
                reported_periods=dict(periods), nonzero_reported_load_weights=dict(n=len(weights),
                    mean=statistics.mean(weights) if weights else None,
                    sample_sd=statistics.stdev(weights) if len(weights)>1 else None,
                    min=min(weights) if weights else None,max=max(weights) if weights else None),
                interpretation='Descriptive sampled load weights only. Zero weight is not zero load latency; filtering can skew periods. Not an all-load latency estimate or a speed confidence interval.')


def counter_summary(rows):
    cells = defaultdict(list)
    for row in rows:
        if row['status'] != 'collected' or row['collector']['kind'] != 'stat':
            continue
        for c in row['counters']:
            key = (row['collector']['id'],row['isa'],row['model'],row['arm'],row['mode'],c['event'],c.get('unit') or '')
            cells[key].append(float(c['counter-value'])/row['calls'])
    result = []
    for key,values in sorted(cells.items()):
        result.append(dict(zip(('collector','isa','model','arm','mode','event','unit'),key),n=len(values),
                           mean_per_call=statistics.mean(values),sample_sd_per_call=statistics.stdev(values) if len(values)>1 else None))
    return result


def event_args(c):
    if c['kind'] == 'trace':
        args = ['--no-buildid-cache', '--clockid', 'mono', '-c', '1', '-m', '1024']
        for event in c['events']: args += ['-e', event]
        return args
    if c['kind'] == 'stat':
        events = c['events']
        return ['-j', '-e', '{' + ','.join(events) + '}' if len(events) > 1 else events[0]]
    args = ['--no-buildid-cache', '-e', c['events'][0]]
    args += ['-c', str(c['period'])] if 'period' in c else ['-F', str(c['frequency'])]
    if c.get('branches'):
        args += ['-j', c['branches']]
    if c.get('memory'):
        args += ['-d', '--weight']
    return args


def parse_trace(text, cpu, expected):
    """Retain trace payload and integer ns; reject silent partial parsing/loss."""
    if 'PERF_RECORD_LOST' in text: raise RuntimeError('Lost trace events')
    rows=[]
    for line in text.splitlines():
        if not line.strip() or line.startswith('#'): continue
        match=re.match(r'^\s*(.*?)\s+(\d+)(?:/(\d+))?\s+\[(\d+)\]\s+(\d+)\.(\d{9}):\s+([\w]+:[\w]+):\s*(.*)$',line)
        if not match: raise ValueError('Unparsed trace line: '+line[:200])
        comm,pid,tid,c,sec,nsec,event,payload=match.groups()
        if int(c)!=cpu or event not in expected: raise ValueError('Unexpected trace CPU/event')
        rows.append(dict(pid=int(pid),tid=int(tid or pid),cpu=int(c),ns=int(sec)*1000000000+int(nsec),event=event,payload=payload))
        if len(rows)>200000: raise RuntimeError('Trace budget exceeded')
    if any(a['ns']>b['ns'] for a,b in zip(rows,rows[1:])): raise ValueError('Unordered trace')
    return rows


def trace_summary(rows, observations, pid):
    idle=None;idle_spans=[];irqs={};irq_spans=[];softirqs={};softirq_spans=[];orphan_exits=0
    for r in rows:
        payload=r['payload'];event=r['event']
        if event=='power:cpu_idle':
            match=re.search(r'\bstate=(-?\d+)',payload)
            if not match: raise ValueError('Missing idle state')
            state=int(match[1])
            if state in (-1,4294967295):
                if idle: idle_spans.append(dict(start=idle[0],end=r['ns'],state=idle[1]));idle=None
                else: orphan_exits+=1
            else:
                if idle is not None: raise ValueError('Unclosed idle entry')
                idle=(r['ns'],state)
        if event.startswith('irq:irq_handler_'):
            match=re.search(r'\birq=(\d+)',payload)
            if not match: raise ValueError('Missing IRQ number')
            key=int(match[1])
            if event.endswith('_entry'):
                if key in irqs: raise ValueError('Nested same IRQ')
                irqs[key]=r['ns']
            elif key in irqs: irq_spans.append((irqs.pop(key),r['ns'],key))
            else: orphan_exits+=1
        if event.startswith('irq:softirq_'):
            match=re.search(r'\bvec=(\d+)',payload)
            if not match: raise ValueError('Missing softIRQ vector')
            key=int(match[1])
            if event.endswith('_entry'):
                if key in softirqs: raise ValueError('Nested same softIRQ')
                softirqs[key]=r['ns']
            elif key in softirqs:softirq_spans.append((softirqs.pop(key),r['ns'],key))
            else:orphan_exits+=1
    calls=[]
    for i,o in enumerate(observations):
        start,finish=o['start_ns'],o['finish_ns']
        # The last completed idle span before dispatch, only if in this period.
        prior=[s for s in idle_spans if o['scheduled_ns']-100000000<=s['end']<=start]
        last=prior[-1] if prior else None
        calls.append(dict(index=i,wakeup_us=(start-o['scheduled_ns'])/1000,
            last_idle_state=last['state'] if last else None,
            idle_exit_to_start_us=(start-last['end'])/1000 if last else None,
            body_irq_overlap_us=sum(max(0,min(finish,b)-max(start,a)) for a,b,_ in irq_spans)/1000,
            body_softirq_overlap_us=sum(max(0,min(finish,b)-max(start,a)) for a,b,_ in softirq_spans)/1000,
            body_switch_outs=sum(r['event']=='sched:sched_switch' and start<=r['ns']<=finish and
                                re.search(r'\bprev_pid='+str(pid)+r'\b',r['payload']) is not None for r in rows)))
    return dict(event_counts=dict(Counter(r['event'] for r in rows)),idle_states=dict(Counter(s['state'] for s in idle_spans)),
                calls=calls,boundary_orphan_exits=orphan_exits,unclosed_boundary_spans=len(irqs)+len(softirqs)+int(idle is not None),
                interpretation='Diagnostic MONOTONIC trace on worker CPU. Cross-CPU wakeups may be absent. Idle trace states describe kernel requests, not measured hardware residency. Device IRQ tracepoints do not cover all local APIC timers/NMIs/firmware interruptions. IRQ overlaps and association are not a causal proof; tracing overhead is excluded from speed claims.')


def run_perf(cmd, output, err):
    # A separate group permits root perf and its worker to be reaped on timeout
    # or interruption; killing only the sudo frontend can orphan a recording.
    process=subprocess.Popen(cmd,stdout=output,stderr=err,start_new_session=True)
    try:
        returncode=process.wait(timeout=60)
    except BaseException:
        subprocess.run(['sudo','-n','/bin/kill','-TERM','--','-'+str(process.pid)],capture_output=True,timeout=5)
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            subprocess.run(['sudo','-n','/bin/kill','-KILL','--','-'+str(process.pid)],capture_output=True,timeout=5)
            process.wait(timeout=5)
        raise
    return returncode


def collect(m, path, controller, worker_args, ready, frozen_hashes):
    validate_manifest(m)
    collectors = validate(m['profile_collectors'])
    out = Path(path).resolve()
    out.mkdir()
    (out/'samples').mkdir()
    write_json(out/'input-hashes.json', frozen_hashes)
    inv = inventory()
    write_json(out/'inventory.json', inv)
    with (out/'perf-list.json').open('w') as f:
        subprocess.run([PERF, 'list', '--json'], stdout=f, check=True)
    write_json(out/'ready.json', ready)
    arms = m.get('profile_arms', ['baseline', 'candidate'])
    repetitions = m.get('profile_repetitions', 2)
    if not arms or len(set(arms)) != len(arms) or not set(arms) <= {'baseline', 'candidate'}:
        raise ValueError('Invalid profile arms')
    if type(repetitions) is not int or not 1 <= repetitions <= 3:
        raise ValueError('Use 1..3 fixed profiling repetitions')
    selected = m.get('profile_conditions', [])
    specs = [c for c in m['conditions'] if c['id'] in selected]
    if not specs or set(selected) != {c['id'] for c in specs}:
        raise ValueError('Explicit valid profile_conditions required')
    jobs = []
    rng = random.Random(m['seed'] + 2000)
    for collector in collectors:
        for rep in range(repetitions if collector['kind'] == 'stat' else 1):
            cells = [(isa, model, arm, c) for isa in m['variants'] for model in m['models'] for arm in arms for c in specs]
            rng.shuffle(cells)
            for isa, model, arm, c in cells:
                calls = m.get('profile_calls', {}).get(c['id'], c['calls'])
                batch = c.get('batch_size', 1)
                if type(calls) is not int or not 16 <= calls <= 65536 or calls % batch or calls//batch < 2:
                    raise ValueError('Invalid bounded profiling call count')
                jobs.append(dict(index=len(jobs), isa=isa, model=model, arm=arm, mode=c['id'],
                                 input=c.get('inputs', m['inputs'])[0], collector=collector,
                                 repeat=rep, worker=c.get('worker', m['worker']), worker_mode=c['worker_mode'],
                                 batch_size=batch, period_ns=c.get('period_ns', 10000000), calls=calls))
    write_json(out/'plan.json', jobs)
    rows = []
    checksums = {}
    for j in jobs:
        c = j['collector']
        stem = out/f"{j['index']:03d}-{c['id']}"
        ctl, ack = stem.with_suffix('.ctl'), stem.with_suffix('.ack')
        data = stem.with_suffix('.data')
        raw = out/'samples'/f"{j['index']:03d}.f64"
        row = dict(j, timing_excluded_from_speed_inference=True, status='pending', attribution=c.get('scope', 'task'))
        cmd = ['sudo', '-n', 'env', 'LC_ALL=C', 'DPDF_PERF_CONTROL='+str(ctl), 'DPDF_PERF_ACK='+str(ack),
               PERF, 'record' if c['kind']=='trace' else c['kind'], '--delay=-1', '--control=fifo:'+str(ctl)+','+str(ack), *event_args(c)]
        if c['kind'] in ('record','trace'):
            cmd += ['-o', str(data)]
        if c['kind']=='trace':
            cmd += ['-a','-C',str(m.get('cpu',3))]
            row['attribution']='worker CPU, includes idle/kernel/other tasks; cross-CPU wakeups may be absent'
        if c.get('scope') == 'shared-pmu':
            p = inv['pmus'].get(c['pmu'])
            if p is None:
                row.update(status='unavailable', reason='PMU sysfs device absent')
            else:
                eligible = cpulist(p.get('cpumask', str(m.get('cpu', 3)))) & cpulist(Path('/sys/devices/system/cpu/online').read_text().strip())
                if not eligible:
                    row.update(status='unavailable', reason='No online representative CPU for PMU')
                else:
                    cpu = m.get('cpu', 3) if m.get('cpu', 3) in eligible else min(eligible)
                    cmd += ['-a', '-C', str(cpu)]
                    row['pmu_cpu'] = cpu
                    row['attribution'] = 'shared hierarchy; includes background activity; not process-exclusive'
        cmd += ['--', '/usr/bin/python3', str(controller), 'exec', '--', *worker_args(m, j, raw)]
        row['command'] = cmd
        if row['status'] == 'pending':
            for p in (ctl, ack):
                os.mkfifo(p, 0o600)
            try:
                with stem.with_suffix('.log').open('w') as err, stem.with_suffix('.worker.json').open('w') as output:
                    with telemetry.Monitor(stem.with_suffix('.telemetry.json')):
                        returncode = run_perf(cmd, output, err)
                log = stem.with_suffix('.log').read_text()
                row['returncode'] = returncode
                if returncode:
                    reason = unavailable_reason(log)
                    receipt = stem.with_suffix('.worker.json').read_text().strip()
                    if receipt and json.loads(receipt).get('calls') != j['calls']:
                        raise RuntimeError('Profiling workload/controller failed: '+receipt)
                    if c.get('required', False) or reason is None:
                        raise RuntimeError('Required PMU/workload failure: '+str(stem)+' '+log[-1500:])
                    row.update(status='unavailable', reason=reason)
                else:
                    # A successful perf process alone does not establish a valid worker.
                    worker = json.loads(stem.with_suffix('.worker.json').read_text())
                    audio_protocol.validate_receipt(worker,raw)
                    if worker['calls'] != j['calls'] or worker['model'] != j['model']:
                        raise RuntimeError('Profiling worker model/call-count mismatch')
                    key=(j['isa'],j['model'],j['mode'],j['calls'],j['input'],j['worker'])
                    checksum=worker.get('checksum')
                    if not isinstance(checksum,str) or len(checksum)!=16:
                        raise RuntimeError('Missing profiling worker checksum')
                    if key in checksums and checksums[key]!=checksum:
                        raise RuntimeError('Profiling baseline/candidate checksum mismatch')
                    checksums[key]=checksum
                    row['worker'] = worker
                    if c['kind'] == 'stat':
                        if '<not supported>' in log or '<not counted>' in log:
                            if c.get('required', False):
                                raise RuntimeError('Required PMU group unsupported/not counted: '+str(stem))
                            row.update(status='unavailable',reason='Perf reports unsupported/not-counted event; raw log retained')
                        else:
                            counters = parse_counters(log, len(c['events']))
                            row['counters'] = counters
                            row['counter_values_per_call'] = {x['event']: float(x['counter-value'])/j['calls'] for x in counters}
                    else:
                        subprocess.run(['sudo', '-n', 'chown', f'{os.getuid()}:{os.getgid()}', str(data)], check=True)
                        with stem.with_suffix('.samples.txt').open('w') as f:
                            fields='comm,pid,tid,cpu,time,event,trace' if c['kind']=='trace' else 'comm,pid,tid,time,event,ip,sym,dso'
                            subprocess.run([PERF, 'script', '--show-lost-events', '--ns', '-i', str(data), '-F',fields], stdout=f, check=True)
                        samples = stem.with_suffix('.samples.txt').read_text()
                        row['sample_lines'] = sample_count(samples)
                        if not row['sample_lines']:
                            row.update(status='empty', reason='No observed samples in fixed warmed window; not evidence of zero misses/latency')
                        row['data_sha256'] = sha(data)
                        if c['kind']=='trace':
                            traces=parse_trace(samples,m.get('cpu',3),c['events'])
                            if worker.get('measurement_version')!=2:raise ValueError('Trace needs versioned timestamp sidecars')
                            observations=json.loads(Path(str(raw)+'.timing.json').read_text())['observations']
                            row['trace_summary']=trace_summary(traces,observations,worker['pid'])
                        with stem.with_suffix('.report.txt').open('w') as f, stem.with_suffix('.report.log').open('w') as err:
                            if c['kind']=='trace':
                                f.write(json.dumps(row['trace_summary'],indent=2)+'\n')
                            elif row['sample_lines']:
                                subprocess.run([PERF, 'report', '--stdio', '--no-children', '--percent-limit', '0.2',
                                                '-i', str(data), '--sort', 'dso,symbol'], stdout=f, stderr=err, check=True)
                            else:
                                f.write(row['reason']+'\n')
                        if c.get('branches'):
                            with stem.with_suffix('.branches.txt').open('w') as f:
                                subprocess.run([PERF, 'script', '-i', str(data), '-F', 'brstack'], stdout=f, check=True)
                            stacks = stem.with_suffix('.branches.txt').read_text()
                            row['branch_stack_lines'] = sum('/' in line for line in stacks.splitlines())
                            if not row['branch_stack_lines']:
                                row.update(status='empty', reason='No branch-stack entries observed in fixed recording')
                        if c.get('memory'):
                            with stem.with_suffix('.memory-samples.txt').open('w') as f:
                                subprocess.run([PERF, 'script', '-i', str(data), '-F',
                                                'ip,sym,dso,addr,data_src,weight,period'], stdout=f, check=True)
                            row['memory_summary'] = memory_summary(stem.with_suffix('.memory-samples.txt').read_text())
                            with stem.with_suffix('.memory.txt').open('w') as f, stem.with_suffix('.memory.log').open('w') as err:
                                if row['sample_lines']:
                                    r = subprocess.run([PERF, 'report', '--stdio', '--mem-mode', '-i', str(data)], stdout=f, stderr=err)
                                    row['memory_report_returncode'] = r.returncode
                                else:
                                    f.write(row['reason']+'\n');row['memory_report_returncode'] = None
                            with stem.with_suffix('.raw.txt').open('w') as f:
                                subprocess.run([PERF, 'script', '-D', '-i', str(data)], stdout=f, check=True)
                    if row['status'] == 'pending':
                        row['status'] = 'collected'
            finally:
                ctl.unlink(missing_ok=True)
                ack.unlink(missing_ok=True)
        if row['status'] == 'unavailable' and c.get('required', False):
            write_json(stem.with_suffix('.failure.json'), row)
            raise RuntimeError('Required collector unavailable: '+str(row))
        rows.append(row)
        with (out/'hardware.jsonl').open('a') as f:
            f.write(json.dumps(row)+'\n')
        print('profile', len(rows), '/', len(jobs), c['id'], row['status'], flush=True)
    write_json(out/'result.json', {'jobs': len(rows), 'collected': sum(r['status']=='collected' for r in rows),
                                  'unavailable': [r for r in rows if r['status']=='unavailable'],
                                  'empty': [r for r in rows if r['status']=='empty'],
                                  'counter_summary': counter_summary(rows), 'timing_excluded': True})
    if any(sha(p) != digest for p, digest in frozen_hashes.items()):
        raise RuntimeError('Profiling input/tool changed during frozen collection')
    return rows
