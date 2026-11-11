"""Synthetic sysfs and failure-path tests; never modify host policy."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/bench_lab'))
import telemetry


class Contracts(unittest.TestCase):
    def test_units_missing_and_private_fields(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name,value in {'sys/class/hwmon/hwmon0/name':'k10temp',
                               'sys/class/hwmon/hwmon0/temp1_input':'50000',
                               'sys/class/hwmon/hwmon0/temp1_label':'Tctl',
                               'sys/class/hwmon/hwmon0/power1_input':'broken',
                               'sys/class/power_supply/AC/online':'1',
                               'sys/class/power_supply/AC/type':'Mains',
                               'sys/class/power_supply/mouse/type':'Battery',
                               'sys/class/power_supply/mouse/scope':'Device',
                               'sys/class/power_supply/mouse/online':'1',
                               'sys/class/power_supply/AC/serial_number':'private',
                               'proc/stat':'cpu0 10 0 5 85 0 0 0 0 0 0\n'}.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
            r=telemetry.snapshot(root)
            self.assertTrue(r['availability']['temperature']);self.assertFalse(r['availability']['energy'])
            self.assertEqual(r['values']['/sys/class/hwmon/hwmon0/temp1_input']['value'],50000)
            self.assertIn('/sys/class/hwmon/hwmon0/power1_input',r['errors'])
            self.assertNotIn('private',json.dumps(r));self.assertEqual(r['cpu_ticks']['cpu0'][0],10)
            self.assertEqual(r['host_ac'],[dict(path='/sys/class/power_supply/AC',online='1')])

    def test_cpu_busy_and_resets(self):
        a={'cpu_ticks':{'cpu0':[10,0,0,90,0,0,0,0]}}
        b={'cpu_ticks':{'cpu0':[20,0,0,100,0,0,0,0]}}
        self.assertEqual(telemetry.cpu_busy(a,b),{'cpu0':50})
        self.assertEqual(telemetry.cpu_busy(b,a),{'cpu0':None})

    def test_sampler_stops_and_writes_on_workload_failure(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out.json';m=telemetry.Monitor(p,reader=lambda:dict(cpu_ticks={}))
            with self.assertRaisesRegex(RuntimeError,'workload'):
                with m:raise RuntimeError('workload')
            self.assertFalse(m.thread.is_alive());r=json.loads(p.read_text());self.assertTrue(r['sampler_stopped'])

    def test_sampler_failure_is_visible(self):
        def fail():raise OSError('sensor')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out.json'
            with self.assertRaisesRegex(RuntimeError,'Telemetry failed'):
                with telemetry.Monitor(p,reader=fail):pass
            self.assertIn('sensor',json.loads(p.read_text())['error'])

    def test_sampling_budget(self):
        for changes in [dict(interval=.001),dict(duration=600)]:
            with self.assertRaises(ValueError):telemetry.Monitor('/unused',**changes)


if __name__=='__main__':unittest.main()
