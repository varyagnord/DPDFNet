"""PMU planning/metric contracts; no privileged hardware writes."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/bench_lab'))

SPEC = importlib.util.spec_from_file_location('pmu', Path(__file__).resolve().parents[1]/'tools/bench_lab/pmu.py')
pmu = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pmu)


class PMUContracts(unittest.TestCase):
    def test_perf_timeout_reaps_privileged_process_group(self):
        process=Mock(pid=4321)
        process.wait.side_effect=[pmu.subprocess.TimeoutExpired('perf',60),0]
        with patch.object(pmu.subprocess,'Popen',return_value=process),patch.object(pmu.subprocess,'run') as signal:
            with self.assertRaises(pmu.subprocess.TimeoutExpired):pmu.run_perf(['perf'],None,None)
        self.assertEqual(signal.call_args.args[0],['sudo','-n','/bin/kill','-TERM','--','-4321'])
        self.assertEqual(process.wait.call_count,2)

    def test_perf_interruption_escalates_only_if_term_does_not_finish(self):
        process=Mock(pid=4322)
        process.wait.side_effect=[KeyboardInterrupt(),pmu.subprocess.TimeoutExpired('perf',5),0]
        with patch.object(pmu.subprocess,'Popen',return_value=process),patch.object(pmu.subprocess,'run') as signal:
            with self.assertRaises(KeyboardInterrupt):pmu.run_perf(['perf'],None,None)
        self.assertEqual(signal.call_count,2);self.assertIn('-KILL',signal.call_args.args[0])

    def test_trace_scope_clock_and_event_limits(self):
        c=dict(id='idle',kind='trace',events=['power:cpu_idle','sched:sched_switch'],scope='cpu',reason='wake latency')
        pmu.validate([c])
        self.assertIn('mono',pmu.event_args(c));self.assertIn('1',pmu.event_args(c))
        for changes in [dict(scope='task'),dict(period=10000),dict(events=['syscalls:sys_enter_openat'])]:
            with self.assertRaises(ValueError):pmu.validate([dict(c,**changes)])

    def test_trace_preserves_ns_and_rejects_partial_or_lost(self):
        s=' swapper 0/0 [003] 12.000000001: power:cpu_idle: state=3 cpu_id=3\n'
        r=pmu.parse_trace(s,3,['power:cpu_idle']);self.assertEqual(r[0]['ns'],12000000001)
        for bad in ['PERF_RECORD_LOST 2',s+'bad',s.replace('[003]','[004]')]:
            with self.assertRaises((ValueError,RuntimeError)):pmu.parse_trace(bad,3,['power:cpu_idle'])

    def test_trace_idle_irq_and_switch_chronology(self):
        def r(t,e,p):return dict(ns=t,event=e,payload=p)
        rows=[r(10,'power:cpu_idle','state=3'),r(20,'power:cpu_idle','state=4294967295'),
              r(32,'irq:irq_handler_entry','irq=5'),r(34,'sched:sched_switch','prev_pid=123 next_pid=0'),
              r(36,'irq:irq_handler_exit','irq=5')]
        out=pmu.trace_summary(rows,[dict(scheduled_ns=18,start_ns=30,finish_ns=40)],123)
        self.assertEqual(out['idle_states'],{3:1});self.assertEqual(out['calls'][0]['body_switch_outs'],1)
        self.assertEqual(out['calls'][0]['body_irq_overlap_us'],.004)
        self.assertEqual(out['calls'][0]['idle_exit_to_start_us'],.01)
        soft=pmu.trace_summary([r(31,'irq:softirq_entry','vec=1 [action=TIMER]'),r(35,'irq:softirq_exit','vec=1')],
                              [dict(scheduled_ns=18,start_ns=30,finish_ns=40)],123)
        self.assertEqual(soft['calls'][0]['body_softirq_overlap_us'],.004)

    def collector(self, **kw):
        return dict(id='core', kind='stat', events=['cycles:u', 'instructions:u'], reason='core efficiency', **kw)

    def test_groups_have_exact_event_counts_and_sampling_is_separate(self):
        c = self.collector()
        self.assertEqual(pmu.event_args(c), ['-j', '-e', '{cycles:u,instructions:u}'])
        sample = dict(id='ibs', kind='record', events=['ibs_op/cnt_ctl=1,swfilt=1/u'], reason='load latency', period=100000, memory=True)
        pmu.validate([c, sample])
        self.assertIn('--weight', pmu.event_args(sample))

    def test_rejects_unbounded_or_ambiguous_sampling(self):
        for kw in [dict(period=1), dict(period=100000, frequency=999), {}]:
            with self.assertRaises(ValueError):
                pmu.validate([dict(id='ibs', kind='record', events=['ibs_op//'], reason='loads', **kw)])

    def test_rejects_unknown_duplicate_and_invalid_sources(self):
        for cs in [[self.collector(), self.collector()], [self.collector(typo=True)],
                   [dict(id='../escape', kind='stat', events=['cycles:u'], reason='x')],
                   [dict(id='bad', kind='stat', events=['-o/file'], reason='x')],
                   [dict(id='bad', kind='stat', events=['cycles:u']*2, reason='x')]]:
            with self.assertRaises(ValueError):
                pmu.validate(cs)

    def test_shared_scope_requires_explicit_pmu(self):
        with self.assertRaises(ValueError):
            pmu.validate([self.collector(scope='shared-pmu')])
        pmu.validate([self.collector(scope='shared-pmu', pmu='amd_l3')])

    def test_rejects_multiplexed_missing_or_unsupported_metrics(self):
        def line(value='10', running=100):
            return json.dumps({'counter-value':value, 'pcnt-running':running, 'event-runtime':123456})
        self.assertEqual(len(pmu.parse_counters(line(), 1)), 1)
        for data, n in [(line(running=99),1), (line('nan'),1), (line('-1'),1), (line(),2)]:
            with self.assertRaises(RuntimeError):
                pmu.parse_counters(data,n)
        with self.assertRaises(ValueError):
            pmu.parse_counters(line('<not supported>'),1)
        with self.assertRaises(RuntimeError):
            pmu.parse_counters(json.dumps({'counter-value':0,'pcnt-running':100,'event-runtime':0}),1)

    def test_workload_errors_are_not_optional_hardware_skips(self):
        self.assertIsNone(pmu.unavailable_reason('Segmentation fault in worker'))
        self.assertIsNone(pmu.unavailable_reason('Worker failed: Invalid argument'))
        self.assertIsNotNone(pmu.unavailable_reason('event syntax error: unknown-pmu'))
        self.assertIsNotNone(pmu.unavailable_reason('No permission to enable event'))

    def test_profile_bounds_validated_before_preparation(self):
        m=dict(profile_collectors=[self.collector()], profile_conditions=['continuous'],
               conditions=[dict(id='continuous',calls=64,batch_size=1)])
        pmu.validate_manifest(m)
        for change in [dict(profile_conditions=['typo']),dict(profile_arms=['typo']),
                       dict(profile_repetitions=10),dict(profile_calls={'continuous':1000000})]:
            with self.assertRaises(ValueError):
                pmu.validate_manifest(dict(m,**change))

    def test_cpumask_uses_actual_pmu_representatives(self):
        self.assertEqual(pmu.cpulist('0,4-7,12'),{0,4,5,6,7,12})

    def test_empty_filtered_samples_differ_from_loss(self):
        self.assertEqual(pmu.sample_count(''),0)
        self.assertEqual(pmu.sample_count('one\n\ntwo\n'),2)
        with self.assertRaises(RuntimeError):
            pmu.sample_count('PERF_RECORD_LOST 100')

    def test_load_weight_summary_does_not_treat_zero_as_zero_latency(self):
        text='''100000 123 456 |OP LOAD|LVL L1 hit|SNP N/A|TLB L1 hit|LCK N/A|BLK N/A 0 abc load_one (/lib.so)
100000 123 456 |OP LOAD|LVL L3 hit|SNP N/A|TLB L1 hit|LCK N/A|BLK N/A 100 abd load_two (/lib.so)
100000 123 456 |OP LOAD|LVL L3 hit|SNP N/A|TLB L1 hit|LCK N/A|BLK N/A 120 abe load_three (/lib.so)
100000 0 456 |OP N/A|LVL N/A|SNP N/A|TLB N/A|LCK N/A|BLK N/A 0 abf math (/lib.so)
'''
        r=pmu.memory_summary(text)
        self.assertEqual(r['observed_load_samples'],3)
        self.assertEqual(r['unparsed_load_samples'],0)
        self.assertEqual(r['nonzero_reported_load_weights']['n'],2)
        self.assertEqual(r['nonzero_reported_load_weights']['mean'],110)
        self.assertEqual(r['sources'],{'L1 hit':1,'L3 hit':2})
        self.assertEqual(pmu.memory_summary('bad |OP LOAD| layout')['unparsed_load_samples'],1)

    def test_counter_sd_keeps_models_and_attribution_cells_separate(self):
        rows=[]
        for model,value in [(2,100),(2,120),(8,900)]:
            rows.append(dict(status='collected',collector=dict(id='core',kind='stat'),isa='native',model=model,
                             arm='candidate',mode='continuous',calls=10,counters=[{'event':'cycles:u','counter-value':value}]))
        r=pmu.counter_summary(rows)
        self.assertEqual(len(r),2)
        self.assertEqual(r[0]['mean_per_call'],11)
        self.assertAlmostEqual(r[0]['sample_sd_per_call'],2**.5)
        self.assertIsNone(r[1]['sample_sd_per_call'])


if __name__ == '__main__':
    unittest.main()
