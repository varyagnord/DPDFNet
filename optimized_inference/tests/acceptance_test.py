"""Meaningful policy boundaries; no changes to legacy qualification results."""
import sys
from pathlib import Path
import unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'tools/bench_lab'),str(Path(__file__).resolve().parents[1]/'tools')]
import acceptance as a
P=dict(version=2,roles={'continuous':'throughput','audio10':'audio'},model_roles={'2':'guard'},minimum_gain_percent=.3,mean_loss_margin_percent=2.,tail_loss_margin_percent=5.,aa_drift_percent=.3,family_comparisons=14)
class Contracts(unittest.TestCase):
 def verdict(self,role='throughput',gain=1.,ci=(.1,1.9),aa_gain=0.,aa_ci=(-3.,3.),tail=(-1.,2.),clean=True):return a.decision(P,role,gain,ci,aa_gain,aa_ci,tail,clean)
 def test_noisy_aa_is_not_a_superiority_veto(self):self.assertTrue(self.verdict()['passed'])
 def test_resolved_practical_aa_drift_invalidates(self):self.assertFalse(self.verdict(aa_gain=.4,aa_ci=(.1,.7))['passed'])
 def test_tiny_resolved_aa_difference_is_not_practical_drift(self):self.assertTrue(self.verdict(aa_gain=.05,aa_ci=(.01,.09))['passed'])
 def test_throughput_needs_both_size_and_resolved_direction(self):
  self.assertFalse(self.verdict(gain=.2)['passed']);self.assertFalse(self.verdict(ci=(-.1,2.))['passed'])
 def test_audio_accepts_small_unresolved_gain_with_noninferiority(self):self.assertTrue(self.verdict(role='audio',gain=0.,ci=(-1.,1.))['passed'])
 def test_audio_rejects_unbounded_mean_or_tail_cost(self):
  self.assertFalse(self.verdict(role='audio',ci=(-2.01,3.))['passed']);self.assertFalse(self.verdict(role='audio',tail=(-5.01,3.))['passed'])
 def test_deadline_fault_guard_cannot_be_relaxed(self):self.assertFalse(self.verdict(clean=False)['passed'])
 def test_policy_cannot_invent_a_role_or_silently_default_thresholds(self):
  a.validate(P,[dict(id='continuous'),dict(id='audio10')])
  for p in [dict(P,roles={'continuous':'magic'}),dict(P,mean_loss_margin_percent=float('nan')),dict(P,model_roles={'2':'throughput'}),{k:v for k,v in P.items() if k!='aa_drift_percent'}]:
   with self.assertRaises(ValueError):a.validate(p,[dict(id='continuous'),dict(id='audio10')])
 def test_interval_preserves_family_adjustment(self):
  self.assertEqual(a.interval([0.]*4,14),[0.,0.]);self.assertLess(a.interval([-.01,.01,0.,0.],14)[0],a.interval([-.01,.01,0.,0.],1)[0])
 def test_model_guard_and_tail_endpoints_are_applied_to_fresh_process_pairs(self):
  rows=[]
  for block in range(4):
   for label in ['A','B']:
    rows.append(dict(isa='candidate',model=2,mode='continuous',block=block,label=label,result=dict(mean_ms=1.,p99_ms=1.01 if label=='B' else 1.)))
  c=dict(isa='candidate',model=2,mode='continuous',gain_percent=0.,arms={k:dict(late=0,over_10ms=0,major_faults=0) for k in ['A','B']})
  controls=dict(conditions=[dict(isa='candidate',model=2,mode='continuous',gain_percent=0.,interval_percent=[-10.,10.])])
  a.evaluate(P,rows,controls,[c]);self.assertEqual(c['workload_acceptance']['role'],'guard');self.assertTrue(c['workload_acceptance']['passed'])
  rows[1]['result']['p99_ms']=float('nan')
  with self.assertRaises(ValueError):a.evaluate(P,rows,controls,[c])
 def test_mean_and_tail_family_is_checked_before_preparation(self):
  conditions=[dict(id='continuous'),dict(id='audio10')]
  # M2 two guards (4 endpoints), M8 throughput + audio (3 endpoints).
  with self.assertRaisesRegex(ValueError,'mean/tail'):
   a.validate(dict(P,family_comparisons=6),conditions,[2,8],1)
  a.validate(dict(P,family_comparisons=7),conditions,[2,8],1)
  with self.assertRaisesRegex(ValueError,'mean/tail'):
   a.validate(dict(P,family_comparisons=7),conditions,[2,8],2)
if __name__=='__main__':unittest.main()
