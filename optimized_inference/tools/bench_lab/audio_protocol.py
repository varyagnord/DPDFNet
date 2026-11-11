"""Standard-library ABI and receipt validation for versioned audio measurements."""
import ctypes as ct
import hashlib,json,statistics
from pathlib import Path
class Observation(ct.Structure):
    _fields_=[(k,ct.c_uint64) for k in ['scheduled_ns','start_ns','finish_ns','body_ns','aperf','mperf']]
CALLBACK=ct.CFUNCTYPE(ct.c_int,ct.c_void_p,ct.c_uint64)
def describe(values):
    ordered=sorted(values);n=len(ordered)
    return dict(n=n,mean_ms=statistics.mean(ordered),sample_sd_ms=statistics.stdev(ordered) if n>1 else None,
                p95_ms=ordered[int(n*.95)],p99_ms=ordered[int(n*.99)],max_ms=ordered[-1])
def validate_receipt(result,raw):
    if result.get('measurement_version')!=2:return
    sidecar=Path(str(raw)+'.timing.json');data=sidecar.read_bytes()
    if hashlib.sha256(data).hexdigest()!=result['timing_sidecar_sha256']:raise ValueError('Audio sidecar hash mismatch')
    rows=json.loads(data)['observations']
    if len(rows)!=result['calls']:raise ValueError('Audio sidecar count mismatch')
    for r in rows:
        if not r['scheduled_ns']<=r['start_ns']<=r['finish_ns'] or r['body_ns']<=0:raise ValueError('Invalid audio timestamps')
    for name,values in [('wakeup',[(r['start_ns']-r['scheduled_ns'])/1e6 for r in rows]),('response',[(r['finish_ns']-r['scheduled_ns'])/1e6 for r in rows])]:
        expected=describe(values)
        if any(expected[k]!=result[name][k] for k in expected):raise ValueError('Audio timing summary mismatch')
    import array
    a=array.array('d');a.frombytes(Path(raw).read_bytes())
    if list(a)!=[r['body_ns']/1e6 for r in rows]:raise ValueError('Audio raw body mismatch')
    if result['late']!=sum(r['finish_ns']>r['scheduled_ns']+result['period_ns'] for r in rows):raise ValueError('Audio deadline mismatch')
