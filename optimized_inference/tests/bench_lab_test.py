"""Behavioral contracts for root control logic; no privileged writes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('lab', Path(__file__).resolve().parents[1] / 'tools/bench_lab/controller.py')
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


class LabContracts(unittest.TestCase):
    def test_later_dynamic_irq_policy_is_not_a_static_restoration_exception(self):
        entry=dict(path='/proc/irq/53/smp_affinity_list',before='1',requested='4-7')
        state=dict(online_before='0-7')
        self.assertTrue(lab.restored_irq_change(entry,'6',state,'active'))
        for actual,service in [('4-7','active'),('8','active'),('','active'),('6','inactive')]:
            self.assertFalse(lab.restored_irq_change(entry,actual,state,service))
        self.assertFalse(lab.restored_irq_change(dict(entry,path='/sys/power/setting'),'6',state,'active'))

    def test_audit_refuses_an_active_or_failed_session(self):
        for state in [dict(phase='ready'),dict(phase='restored',restoration=dict(restored=False))]:
            with self.assertRaises(RuntimeError):lab.audit_restored(state)

    def test_idle_policy_is_independent_of_frequency_and_keeps_legacy_defaults(self):
        for power in ['steady','boost']:
            self.assertFalse(lab.idle_restricted(power,'original'))
            self.assertTrue(lab.idle_restricted(power,'shallow'))
        self.assertTrue(lab.idle_restricted('steady','auto'))
        self.assertFalse(lab.idle_restricted('boost','auto'))
        with self.assertRaises(RuntimeError):lab.idle_restricted('boost','typo')

    def test_cpu_masks_across_32bit_boundary(self):
        self.assertEqual(lab.cpus('0-3,12-15'), {0,1,2,3,12,13,14,15})
        self.assertEqual(lab.cpumask({0,32,63}), '80000001,00000001')
        with self.assertRaises(ValueError):
            lab.cpus('1;reboot')

    def test_discovers_cache_domain_not_fixed_cpu_numbers(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'online').write_text('0-7')
            for path, value in {'cpu3/cache/index3/level':'3', 'cpu3/cache/index3/type':'Unified',
                                'cpu3/cache/index3/shared_cpu_list':'2-3,6-7',
                                'cpu3/topology/thread_siblings_list':'3,7'}.items():
                p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
            with patch.object(lab,'CPU',root):
                online,reserved,siblings,house=lab.topology(3)
            self.assertEqual(reserved,{2,3,6,7})
            self.assertEqual(siblings,{3,7})
            self.assertEqual(house,{0,1,4,5})

    def test_journal_is_durable_before_write(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'setting';p.write_text('old')
            state={'journal':[]};saved=[]
            original=lab.write
            def observed(path,value):
                self.assertTrue(saved)
                self.assertEqual(saved[-1][0]['before'],'old')
                original(path,value)
            with patch.object(lab,'save',lambda s:saved.append([x.copy() for x in s['journal']])),patch.object(lab,'write',observed):
                lab.change(state,p,'new')
            self.assertEqual(state['journal'][0]['applied'],'new')

    def test_optional_unwritable_irq_is_retained_as_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'irq';p.write_text('0-3');state={'journal':[]}
            with patch.object(lab,'save'),patch.object(lab,'write',side_effect=PermissionError('managed IRQ')):
                lab.change(state,p,'4-7',optional=True)
            self.assertIn('error',state['journal'][0])
            self.assertEqual(p.read_text(),'0-3')

    def test_frequency_bound_order_handles_both_directions(self):
        for initial,target in [((100,200),(300,300)),((300,400),(100,100)),((100,400),(200,200))]:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)
                for name,value in zip(['scaling_min_freq','scaling_max_freq'],initial):(p/name).write_text(str(value))
                original=lab.write
                def checked(path,value):
                    low=int(lab.read(p/'scaling_min_freq'));high=int(lab.read(p/'scaling_max_freq'))
                    self.assertTrue(int(value)<=high if Path(path).name=='scaling_min_freq' else int(value)>=low)
                    original(path,value)
                with patch.object(lab,'write',checked):lab.set_limits(p,*target)
                self.assertEqual((int(lab.read(p/'scaling_min_freq')),int(lab.read(p/'scaling_max_freq'))),target)

    def test_zombie_is_not_a_runnable_foreign_thread(self):
        with patch.object(Path,'glob',return_value=[Path('/proc/42')]),patch.object(lab,'identity',return_value=dict(state='Z',flags=0)),patch.object(lab.os,'sched_getaffinity',side_effect=AssertionError('zombie must not count')):
            self.assertEqual(lab.foreign_threads({'reserved':[0,1]}),[])

    def test_frequency_limits_wait_for_requested_readback(self):
        seen = []
        def readback(path):
            if str(path).endswith('scaling_max_freq'):
                return '200'
            seen.append(1)
            return '100' if len(seen) < 3 else '200'
        with patch.object(lab,'read',side_effect=readback),patch.object(lab,'write'),patch.object(lab.time,'sleep') as sleep:
            lab.set_limits(Path('/policy'),200,200)
        self.assertGreaterEqual(len(seen),5)
        self.assertGreaterEqual(sleep.call_count,3)

    def test_frequency_limits_reject_persistent_mismatch(self):
        with patch.object(lab,'read',return_value='100'),patch.object(lab,'write'),patch.object(lab.time,'monotonic',side_effect=[0,0,3]),patch.object(lab.time,'sleep'):
            with self.assertRaisesRegex(RuntimeError,'requested.*200.*observed.*100'):
                lab.set_limits(Path('/policy'),200,200)

    def test_frequency_limits_expired_before_first_readback(self):
        with patch.object(lab,'read',return_value='100'),patch.object(lab,'write'),patch.object(lab.time,'monotonic',side_effect=[0,3]):
            with self.assertRaisesRegex(RuntimeError,'requested.*200.*observed None'):
                lab.set_limits(Path('/policy'),200,200)

    def test_changed_probe_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'probe';p.write_text('changed')
            with patch.object(lab,'verify'),patch.object(lab.subprocess,'check_output',side_effect=AssertionError('must not execute')):
                with self.assertRaises(RuntimeError):lab.calibrate({'probe':str(p),'probe_sha256':'old'})

    def test_boost_validation_is_not_fixed_frequency_validation(self):
        r=[{'effective_khz':v} for v in [2000000,4000000,5000000]]
        s=dict(power_profile='boost',worker_power=dict(scaling_min_freq='600000',scaling_max_freq='5300000'))
        self.assertTrue(lab.frequency_qualified(r,s))
        self.assertFalse(lab.frequency_qualified(r,dict(power_profile='steady',frequency_khz=2000000)))
        self.assertFalse(lab.frequency_qualified([{'effective_khz':9000000}],s))

    def test_completed_restore_is_idempotent(self):
        result={'restored':True,'errors':[]}
        with patch.object(lab,'write',side_effect=AssertionError('unexpected mutation')):
            self.assertEqual(lab.restore({'phase':'restored','restoration':result}),result)


class StudyContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('study',Path(__file__).resolve().parents[1]/'tools/bench_lab/study.py')
        cls.study=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.study)

    def test_process_environment_receipt_survives_worker_failure(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'samples').mkdir()
            snapshots=[dict(cpu_ticks={'cpu0':[0,0,0,10,0,0,0,0]}),dict(cpu_ticks={'cpu0':[10,0,0,20,0,0,0,0]})]
            with patch.object(self.study.telemetry,'snapshot',side_effect=snapshots),patch.object(self.study,'worker_args',return_value=[]),patch.object(self.study,'control',side_effect=RuntimeError('worker failed')):
                with self.assertRaisesRegex(RuntimeError,'worker failed'):self.study.measurement(dict(record_process_environment=True),dict(index=0),out)
            receipt=json.loads((out/'samples/0000.f64.environment.json').read_text())
            self.assertEqual(receipt['cpu_busy_percent'],{'cpu0':50})

    def test_process_environment_keeps_legacy_measurement_path_opt_in(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(self.study.telemetry,'snapshot',side_effect=AssertionError('legacy path must not sample')),patch.object(self.study,'worker_args',return_value=[]),patch.object(self.study,'control',side_effect=RuntimeError('worker failed')):
                with self.assertRaisesRegex(RuntimeError,'worker failed'):self.study.measurement({},dict(index=0),Path(d))

    def test_process_environment_is_hash_bound_to_successful_receipt(self):
        import array
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'samples').mkdir();(out/'samples/0000.f64').write_bytes(array.array('d',[1.,2.]).tobytes())
            result=dict(observations=2,mean_ms=1.5,sample_sd_ms=2**-.5,uid=1000,no_new_privs=1,hardware_feedback_available=True,calls=2,model=2,checksum='0000000000000001')
            job=dict(index=0,model=2,worker_mode='paced',calls=2)
            with patch.object(self.study.telemetry,'snapshot',return_value=dict(cpu_ticks={})),patch.object(self.study,'worker_args',return_value=[]),patch.object(self.study,'control',return_value=result):
                row=self.study.measurement(dict(record_process_environment=True),job,out)
            self.assertEqual(row['environment_sha256'],self.study.sha(out/row['environment']))

    def test_aa_only_session_restores_when_collection_fails(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'session';calls=[]
            def control(*args):
                calls.append(args)
                if args[0]=='prepare':return {'session_id':'test'}
                if args[0]=='restore':return {'restored':True}
                raise AssertionError(args)
            with patch.object(self.study.sys,'argv',['study','aa-session','manifest',str(out)]),patch.object(self.study,'config',return_value={'worker':'/probe'}),patch.object(self.study,'control',side_effect=control),patch.object(self.study,'timing',side_effect=RuntimeError('deliberate collection failure')):
                with self.assertRaisesRegex(RuntimeError,'deliberate'):self.study.main()
            self.assertEqual(calls[-1],('restore','--session','test'))
            self.assertTrue(json.loads((out/'restore.json').read_text())['restored'])

    def test_completed_aa_recovery_keeps_raw_data_and_does_not_run_comparison(self):
        import array,json
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);raw=out/'one.f64';raw.write_bytes(array.array('d',[1.,2.]).tobytes())
            m={'acceptance_policy':{'version':2}};job={'index':0}
            result=dict(observations=2,mean_ms=1.5,sample_sd_ms=2**-.5)
            row=dict(job,result=result,samples=raw.name,samples_sha256=self.study.sha(raw))
            (out/'plan.json').write_text(json.dumps(dict(manifest=m,hashes={})))
            (out/'runs.jsonl').write_text(json.dumps(row)+'\n')
            with patch.object(self.study,'binary_manifest',return_value={}),patch.object(self.study,'schedule',return_value=[job]),patch.object(self.study,'summarize',return_value={'kind':'aa'}),patch.object(self.study.acceptance,'evaluate',side_effect=AssertionError('AA is not a comparison')):
                recovered=self.study.recover_aa(m,out)
            self.assertTrue(recovered['recovered_from_complete_raw_journal']);self.assertEqual(raw.read_bytes(),array.array('d',[1.,2.]).tobytes())

    def test_controller_failure_preserves_reason_and_rollback_verdict(self):
        detail='{"error":"Frequency policy changed: scaling_min_freq","phase":"restored","restoration":{"restored":true}}'
        failure=self.study.subprocess.CalledProcessError(1,['controller','prepare'],output=detail)
        with patch.object(self.study.subprocess,'check_output',side_effect=failure):
            with self.assertRaises(RuntimeError) as captured:
                self.study.control('prepare')
        self.assertIn('Frequency policy changed: scaling_min_freq',str(captured.exception))
        self.assertIn('"restored":true',str(captured.exception))

    def test_order_balances_within_each_input(self):
        from collections import defaultdict,Counter
        m=dict(seed=123,aa_blocks=4,compare_blocks=8,variants={'native':{},'avx2':{}},models=[2,8],inputs=['x','y'])
        for kind in ['aa','compare']:
            jobs=self.study.schedule(m,kind);orders=defaultdict(Counter)
            for j in jobs[::2]:orders[j['isa'],j['model'],j['mode'],j['input']][j['label']]+=1
            for v in orders.values():self.assertEqual(v['A'],v['B'])
            if kind=='aa':self.assertTrue(all(j['arm']=='baseline' for j in jobs))

    def test_custom_condition_order_and_cadence(self):
        m=dict(seed=9,aa_blocks=8,compare_blocks=8,models=[2,8],variants={'native':{'baseline':'/a','candidate':'/b'}},inputs=['x','y'],worker='/worker',weights={'2':'/w2','8':'/w8'},
               conditions=[dict(id='batch64',worker_mode='batch',batch_size=64,calls=512),dict(id='paced20',worker_mode='paced',batch_size=1,calls=64,period_ns=20000000)])
        jobs=self.study.schedule(m,'aa')
        self.assertEqual(len(jobs),64)
        j=next(j for j in jobs if j['mode']=='paced20')
        args=self.study.worker_args(m,j,Path('/raw'))
        self.assertEqual(args[-3:],["paced:20000000","1","/raw"])
        self.assertEqual(len(set((j['mode'],j['model']) for j in jobs)),4)

    def test_summary_handles_explicit_family_and_conditions(self):
        import array
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);rows=[]
            for block in range(4):
                for label in ['A','B']:
                    name=f'{block}-{label}.f64';(root/name).write_bytes(array.array('d',[1.,1.]).tobytes())
                    rows.append(dict(block=block,isa='native',model=2,mode='batch16',label=label,samples=name,
                        result=dict(mean_ms=1.,calls=2,checksum='0000000000000001',observation_unit='batch_mean',reference_delta=2,delivered_delta=2,late=0,over_10ms=0,minor_faults=0,major_faults=0)))
            m=dict(models=[2],variants={'native':{}},family_comparisons=48,conditions=[dict(id='batch16')])
            result=self.study.summarize(m,rows,'aa',root)
            self.assertEqual(result['family_comparisons'],48)
            self.assertEqual(result['conditions'][0]['gain_percent'],0.)
            self.assertTrue(result['conditions'][0]['sensitivity_qualified'])

    def test_callback_uses_registered_worker_and_pcm_inputs(self):
        m=dict(seed=3,aa_blocks=4,compare_blocks=4,models=[2],variants={'native':{'baseline':'/a','candidate':'/b'}},inputs=['spectra-x','spectra-y'],worker='/nn',weights={'2':'/w2'},
               conditions=[dict(id='audio10',worker_mode='paced',worker='/audio',inputs=['pcm-x','pcm-y'],period_ns=10000000,batch_size=1,calls=32)])
        jobs=self.study.schedule(m,'aa');self.assertEqual(set(j['input'] for j in jobs),{'pcm-x','pcm-y'})
        self.assertEqual(self.study.worker_args(m,jobs[0],Path('/raw'))[0],'/audio')

    def test_no_effect_not_a_speedup(self):
        r=self.study.effect([0.]*4,.05/8)
        self.assertEqual(r['gain_percent'],0)
        self.assertEqual(r['interval_percent'],[0,0])

    def test_summary_rejects_numerical_mismatch_before_speed_inference(self):
        m=dict(models=[2],variants={'native':{}},conditions=[dict(id='continuous')])
        rows=[dict(isa='native',model=2,mode='continuous',block=0,label=label,
                   result=dict(checksum=checksum,mean_ms=1.))
              for label,checksum in [('A','0000000000000001'),('B','0000000000000002')]]
        with self.assertRaisesRegex(RuntimeError,'numerical checksum mismatch'):
            self.study.summarize(m,rows,'compare',Path('/not-read'))

    def test_retains_slow_observations_in_sd_and_tail(self):
        r=self.study.describe([1.]*99+[20.])
        self.assertEqual(r['n'],100);self.assertEqual(r['p99'],20.)
        self.assertGreater(r['sd'],1.)

    def test_comparison_requires_identical_binary_control(self):
        with patch.object(self.study,'binary_manifest',return_value={'binary':'new'}):
            with self.assertRaises(ValueError):
                self.study.timing({},'compare','never-created',dict(kind='aa',hashes={'binary':'old'}))


if __name__=='__main__':
    unittest.main()
