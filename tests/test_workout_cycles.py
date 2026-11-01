from datetime import date
from pathlib import Path
import tempfile
import unittest
from personal_assistant.workout.models import validate
from personal_assistant.workout.store import Workouts
from personal_assistant.workout.analytics import overview,e1rm,weight_trend
from personal_assistant.workout.programs import extend


def op(kind,id,data,revision=0,deleted=False):
    return dict(mutation_id=f'op_{kind}_{id}_{revision}',kind=kind,id=id,base_revision=revision,data=data,deleted=deleted)


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Workouts(Path(self.tmp.name)/'workout.sqlite3')
    def tearDown(self): self.tmp.cleanup()

    def test_four_month_cycle_advances_only_completed_sessions_and_can_extend(self):
        sprint=self.store.mutate([op('sprint','s1',dict(name='Build',phase='rebuild',start='2026-11-01',cycle=['a','b','c'],target_sessions=6,status='active'))])[0]
        self.assertEqual(sprint['data']['end'],'2027-03-01')
        self.assertEqual(overview(self.store,date(2026,11,1))['next_workout']['template_id'],'a')
        self.store.mutate([op('workout','rest',dict(name='Rest',started_at='2026-11-01',sprint_id='s1',status='rest')),
                           op('workout','done',dict(name='A',started_at='2026-11-01',sprint_id='s1',status='completed',template_id='a'))])
        summary=overview(self.store,date(2026,11,1))
        self.assertEqual(summary['next_workout']['template_id'],'b')
        self.assertEqual(summary['sprints'][0]['completed_sessions'],1)
        extended=extend(self.store,'s1',date(2027,4,1),sprint['revision'],'extend_sprint_1')
        self.assertEqual(extended['data']['cycle'],['a','b','c'])
        self.assertEqual(extend(self.store,'s1',date(2027,4,1),sprint['revision'],'extend_sprint_1'),extended)
        self.assertEqual(len(extended['data']['extensions']),1)

    def test_waist_not_required_and_missing_rir_assumes_zero_without_rewriting(self):
        self.store.mutate([op('athlete','self',dict(height_cm=180,goal_weight_min_kg=70,goal_weight_max_kg=80)),
            op('measurement','weight',dict(measured_at='2026-11-01T08:00:00Z',value=75,unit='kg',kind='bodyweight'))])
        result=overview(self.store,date(2026,11,1))
        self.assertEqual(result['body_rank']['status'],'within_goal')
        self.assertNotIn('waist_cm',result['body_metrics'])
        item=dict(id='s',exercise_id='e',kind='working',completed=True,weight_kg=50,reps=5,rir=None)
        self.assertIsNotNone(e1rm(item,True));self.assertIsNone(item['rir'])

    def test_warmup_running_cannot_set_capability_or_benchmark(self):
        self.store.mutate([op('exercise','run',dict(name='Running',mode='cardio',movement='run')),
            op('exercise','bench',dict(name='Bench Press (Barbell)',equipment='barbell'))])
        sets=[dict(id='warm',exercise_id='run',kind='warmup',distance_m=2414.016,seconds=400),
              dict(id='work',exercise_id='run',kind='working',distance_m=2414.016,seconds=700),
              dict(id='lift',exercise_id='bench',kind='working',weight_kg=60,reps=5)]
        self.store.mutate([op('workout','session',dict(name='Mixed',started_at='2026-11-01',status='completed',sets=sets))])
        result=overview(self.store,date(2026,11,1))
        self.assertEqual(result['running']['best_working']['seconds'],700)
        self.assertEqual(result['running']['benchmark_1_5mi']['observed']['seconds'],700)
        self.assertAlmostEqual(result['running']['benchmark_1_5mi']['projected']['seconds'],700)
        self.assertEqual(result['workout_metrics'][0]['total_volume'],300)
        self.assertEqual(result['exercise_stats'][1 if result['exercise_stats'][0]['exercise_id']=='run' else 0]['e1rm_series'][0]['value'],70)

    def test_weight_history_explicitly_marks_unmeasured_gap(self):
        points=[dict(kind='bodyweight',measured_at='2026-09-01T08:00:00Z',value=70),dict(kind='bodyweight',measured_at='2026-11-01T08:00:00Z',value=73)]
        result=weight_trend(points,date(2026,11,1))
        self.assertEqual(result['gaps'][0]['style'],'dashed')
        self.assertEqual(result['gaps'][0]['gap_days'],61)
        self.assertEqual(len(result['daily']),2)


if __name__=='__main__': unittest.main()
