"""Read-only package diagnostics. Never frequency-normalize benchmark results.

Sampling belongs to diagnostic passes only; primary timing gets boundary
snapshots. Missing sensors are explicit, not evidence of absent throttling.
"""
from contextlib import AbstractContextManager
import json
from pathlib import Path
import threading
import time


def snapshot(root=Path('/')):
    values, errors = {}, {}
    root = Path(root)

    def read(p, unit='text'):
        key = '/' + str(p.relative_to(root))
        try:
            s = p.read_text().strip()
            values[key] = dict(value=s if unit == 'text' else int(s), unit=unit)
        except (OSError, ValueError) as exc:
            errors[key] = type(exc).__name__

    for hw in sorted((root/'sys/class/hwmon').glob('hwmon*')):
        read(hw/'name')
        for pattern, unit in [('temp*_input', 'millidegree_C_or_driver_mV'),
                              ('power*_input', 'microwatt'), ('power*_average', 'microwatt'),
                              ('power*_cap', 'microwatt'), ('fan*_input', 'rpm')]:
            for p in sorted(hw.glob(pattern)):
                read(p, unit)
                label = p.with_name(p.name.rsplit('_', 1)[0] + '_label')
                if label.exists(): read(label)
    for hw in sorted((root/'sys/class/power_supply').glob('*')):
        for key in ['type', 'scope', 'online', 'status', 'capacity', 'power_now']:
            p = hw/key
            if p.exists(): read(p, 'microwatt' if key == 'power_now' else 'text')
    gpu = set()
    for p in sorted((root/'sys/class/drm').glob('card*/device/gpu_busy_percent')):
        if p.resolve() not in gpu:
            read(p, 'percent'); gpu.add(p.resolve())
    for hw in sorted((root/'sys/devices/system/cpu/cpufreq').glob('policy*')):
        for key in ['scaling_governor', 'energy_performance_preference',
                    'scaling_min_freq', 'scaling_max_freq', 'scaling_cur_freq']:
            p = hw/key
            if p.exists(): read(p, 'kHz_policy_hint' if key.endswith('_freq') else 'text')
    for pattern, unit in [('sys/class/powercap/**/energy_uj', 'microjoule'),
                          ('sys/devices/system/cpu/cpu*/thermal_throttle/*_throttle_count', 'count')]:
        for p in sorted(root.glob(pattern)): read(p, unit)
    platform = root/'sys/firmware/acpi/platform_profile'
    if platform.exists(): read(platform)
    cpus = {}
    try:
        for line in (root/'proc/stat').read_text().splitlines():
            k, *v = line.split()
            if k.startswith('cpu') and k[3:].isdigit(): cpus[k] = list(map(int, v[:8]))
    except (OSError, ValueError) as exc:
        errors['/proc/stat'] = type(exc).__name__
    units = {v['unit'] for v in values.values()}
    host_ac=[]
    for key,v in values.items():
        if key.startswith('/sys/class/power_supply/') and key.endswith('/type') and v['value'] in ['Mains','USB','USB_C']:
            base=key.rsplit('/',1)[0]
            if values.get(base+'/scope',{}).get('value')!='Device' and base+'/online' in values:
                host_ac.append(dict(path=base,online=values[base+'/online']['value']))
    return dict(monotonic_ns=time.monotonic_ns(), values=values, cpu_ticks=cpus, errors=errors,host_ac=host_ac,
                availability=dict(temperature='millidegree_C_or_driver_mV' in units,
                                  power='microwatt' in units, energy='microjoule' in units,
                                  gpu='percent' in units, throttling='count' in units),
                limitations='Policy frequencies are hints, not callback clocks. Missing sensors do not exclude throttling. Shared package/system activity is not task-exclusive.')


def cpu_busy(before, after):
    result = {}
    for cpu in sorted(before['cpu_ticks'].keys() & after['cpu_ticks'].keys()):
        a, b = before['cpu_ticks'][cpu], after['cpu_ticks'][cpu]
        if len(a) != 8 or len(b) != 8: continue
        delta = [y-x for x, y in zip(a, b)]
        # iowait can decrease on Linux; a reset/negative delta is not utilization.
        if min(delta) < 0 or sum(delta) <= 0:
            result[cpu] = None
        else:
            result[cpu] = 100 * (sum(delta)-delta[3]-delta[4]) / sum(delta)
    return result


class Monitor(AbstractContextManager):
    """One bounded sampler, joined even on workload failure or interruption."""
    def __init__(self, path, interval=.2, duration=60, reader=snapshot):
        if not .2 <= interval <= 5 or not 1 <= duration <= 60:
            raise ValueError('Telemetry requires a bounded 0.2..5s interval /1..60s duration')
        self.path, self.interval, self.duration, self.reader = Path(path), interval, duration, reader
        self.stop = threading.Event(); self.thread = None; self.error = None; self.rows = []

    def _run(self):
        try:
            until = time.monotonic() + self.duration
            while True:
                self.rows.append(self.reader())
                if self.stop.wait(self.interval) or time.monotonic() >= until: break
        except BaseException as exc:
            self.error = exc

    def __enter__(self):
        self.thread = threading.Thread(target=self._run, name='dpdf-readonly-telemetry', daemon=False)
        self.thread.start()
        return self

    def __exit__(self, kind, exc, tb):
        self.stop.set(); self.thread.join()
        # A final boundary makes short failed passes auditable as well.
        if self.error is None:
            try: self.rows.append(self.reader())
            except BaseException as e: self.error = e
        value = dict(samples=self.rows, sampler_stopped=not self.thread.is_alive(),
                     diagnostic_only=True, error=repr(self.error) if self.error else None,
                     cpu_busy_percent=cpu_busy(self.rows[0], self.rows[-1]) if len(self.rows)>1 else {})
        self.path.write_text(json.dumps(value, indent=2)+'\n')
        if self.error is not None and exc is None: raise RuntimeError('Telemetry failed') from self.error
        return False
