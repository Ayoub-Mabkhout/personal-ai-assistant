"""Workout invariants: source preservation, offline conflicts, consent and specialist fencing."""
import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from personal_assistant.relay.api import create_app
from personal_assistant.relay.store import Conflict, Missing
from personal_assistant.workout.store import Workouts
from personal_assistant.workout.imports import HEADERS, reconcile
from personal_assistant.workout.analytics import e1rm, rank, overview, weight_trend


def op(kind,id,data,base=0,mutation=None,deleted=False):
    return dict(mutation_id=mutation or ('mutation_'+id+'_'+str(base)),kind=kind,id=id,base_revision=base,data=data,deleted=deleted)


def strong_csv(rows):
    target=io.StringIO(newline='')
    writer=csv.writer(target,delimiter=';',quoting=csv.QUOTE_ALL)
    writer.writerow(HEADERS)
    for changes in rows:
        row=dict(zip(HEADERS,['9','2024-06-01 18:30:00','Synthetic day','3600','Bench Press (Barbell)','1','60','5','','','','','']))
        row.update(changes);writer.writerow([row[k] for k in HEADERS])
    return target.getvalue().encode('utf-8-sig')


class WorkoutTests(unittest.TestCase):
    def test_coach_contract_is_refreshed_and_memory_is_scoped(self):
        from personal_assistant.workout.specialist import build_prompt
        from personal_assistant.workout.memory import save, search
        with tempfile.TemporaryDirectory() as directory:
            config={'workout_runtime_dir':directory}
            job={'id':'sample','photos':[],'context':{},'question':'Remember my goal'}
            state={}
            first=build_prompt(config,state,job,'gpt-6.1-terra','session')
            self.assertIn('action_guide',first)
            state.update(session='sample',session_contract=first['contract_signature'])
            self.assertNotIn('data_schemas',build_prompt(config,state,job,'gpt-6.1-terra','session'))
            state['session_contract']='obsolete'
            self.assertIn('data_schemas',build_prompt(config,state,job,'gpt-6.1-terra','session'))
            save(config,'goal','Goal','Run a mile','Mile goal')
            self.assertTrue(search(config,None,'mile')['matches'])
            self.assertEqual(search(config,'a'*32,'mile')['matches'],[])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.now=1000.
        self.store=Workouts(Path(self.tmp.name)/'workout.sqlite3',clock=lambda:self.now)

    def tearDown(self): self.tmp.cleanup()

    def test_coach_read_tool_rejects_paths_outside_workout_entities(self):
        from personal_assistant.workout.tools import serve
        messages=[]
        for index,args in enumerate(({'view':'entity','kind':'../../banking','id':'summary'},
                                     {'view':'entity','kind':'workout','id':'../../banking/summary'})):
            messages.append(json.dumps({'jsonrpc':'2.0','id':index,'method':'tools/call',
                                        'params':{'name':'workout_read','arguments':args}}))
        output=io.StringIO()
        with patch('personal_assistant.workout.tools.OwnerClient') as client:
            serve({},io.StringIO('\n'.join(messages)+'\n'),output)
            client.return_value.call.assert_not_called()
        self.assertTrue(all(json.loads(line)['result']['isError'] for line in output.getvalue().splitlines()))

    def test_sync_retries_conflicts_and_atomic_batches(self):
        operation=op('exercise','bench',{'name':'Bench'})
        first=self.store.mutate([operation])[0]
        self.assertEqual(first,self.store.mutate([operation])[0])
        self.assertEqual(self.store.changes()['cursor'],1)
        with self.assertRaises(Conflict): self.store.mutate([{**operation,'data':{'name':'Different'}}])
        with self.assertRaises(Conflict): self.store.mutate([op('exercise','new',{'name':'New'}),op('exercise','bench',{'name':'Stale'})])
        with self.assertRaises(Missing): self.store.get('exercise','new')
        self.store.mutate([op('exercise','bench',{},first['revision'],deleted=True)])
        self.assertEqual(self.store.list()['items'],[])
        self.assertTrue(self.store.changes(after=1)['items'][0]['deleted'])
        self.assertEqual(self.store.mutate([operation])[0],first) # old retry cannot revive a deletion

    def test_import_retains_special_types_multiline_and_dumbbell_source(self):
        raw=strong_csv([{'Set Order':'W'},{'Set Order':'D'},{'Set Order':'F'},
            {'Set Order':'Note','Weight (kg)':'','Reps':'','Notes':'line 1\nline 2'},
            {'Exercise Name':'Bicep Curl (Dumbbell)','Weight (kg)':'12.00000000002','Set Order':'7'}])
        preview=reconcile(self.store,raw,timezone='Europe/Berlin')
        self.assertEqual(preview['workouts'],1);self.assertFalse(preview['committed'])
        self.assertEqual(self.store.changes()['cursor'],0)
        imported=reconcile(self.store,raw,timezone='Europe/Berlin',commit=True)
        self.assertEqual(imported['set_types'],dict(warmup=1,drop=1,failure=1,note=1,working=1))
        workout=self.store.list('workout')['items'][0]['data']
        self.assertEqual(workout['sets'][3]['notes'],'line 1\nline 2')
        self.assertFalse(workout['sets'][3]['completed'])
        self.assertEqual(workout['sets'][4]['weight_kg'],12)
        dumbbell=next(e['data'] for e in self.store.list('exercise')['items'] if 'Dumbbell' in e['data']['name'])
        self.assertEqual(dumbbell['load_convention'],'per_hand')
        before=self.store.changes()['cursor']
        self.assertTrue(reconcile(self.store,raw,commit=True)['already_imported'])
        self.assertEqual(before,self.store.changes()['cursor'])
        with self.store.db() as db: self.assertEqual(db.execute('SELECT raw FROM imports').fetchone()['raw'],raw.decode('utf-8-sig'))
        self.assertEqual(self.store.original_import(imported['sha256']),raw)

    def test_overlapping_exports_preserve_owner_corrections_and_flag_conflicts(self):
        raw=strong_csv([{}]);reconcile(self.store,raw,commit=True)
        workout=self.store.list('workout')['items'][0]
        self.store.mutate([op('workout',workout['id'],{**workout['data'],'notes':'Owner correction'},workout['revision'])])
        changed=strong_csv([{'Weight (kg)':'62'}])
        report=reconcile(self.store,changed,commit=True)
        self.assertEqual(report['new'],0);self.assertEqual(len(report['conflicts']),1)
        self.assertEqual(self.store.get('workout',workout['id'])['data']['notes'],'Owner correction')

    def test_weight_import_units_and_missing_day_statistics(self):
        raw=b'measured_at,value,unit\n2026-01-01T07:00:00+01:00,154.323584,lb\n2026-01-03T07:00:00+01:00,71,kg\n2026-01-05T07:00:00+01:00,72,kg\n'
        reconcile(self.store,raw,format='bodyweight',commit=True)
        values=[r['data'] for r in self.store.list('measurement')['items']]
        trend=weight_trend(values,date(2026,1,5))
        self.assertEqual(trend['latest']['count_7d'],3)
        self.assertAlmostEqual(trend['latest']['average_7d'],71)
        self.assertIsNone(trend['latest']['average_14d'])
        self.assertIsNone(trend['daily'][0]['average_7d'])

    def test_easy_sets_and_old_records_cannot_establish_current_rank(self):
        raw=strong_csv([{'RPE':'9'}]);reconcile(self.store,raw,commit=True)
        result=overview(self.store,date(2026,1,1))
        self.assertEqual(len(result['personal_records']),1)
        self.assertEqual(result['ranks'],[])
        self.assertIsNone(result['personal_records'][0]['recent_best'])
        item=dict(completed=True,kind='working',weight_kg=70,reps=5,rir=5)
        self.assertIsNotNone(e1rm(item));self.assertIsNone(e1rm(item,True))
        self.assertIsNone(e1rm({**item,'kind':'warmup'}))
        scores=[rank('Bench Press (Barbell)',x,70,'male')['score'] for x in (10,30,50,70,100,150)]
        self.assertEqual(scores,sorted(scores))
        self.assertEqual(rank('Unknown machine',100,70,'male')['status'],'unsupported_exercise')
        self.assertNotEqual(rank('Bench Press (Barbell)',100,None,'male')['status'],'ranked')

    def test_bodyweight_and_high_rep_records_do_not_need_a_max_estimate(self):
        raw=strong_csv([{'Exercise Name':'Pull Up','Weight (kg)':'0','Reps':'14'},
                       {'Exercise Name':'Lateral Raise (Dumbbell)','Weight (kg)':'8','Reps':'20'}])
        reconcile(self.store,raw,commit=True)
        result=overview(self.store,date(2024,6,2))
        self.assertEqual(result['personal_records'],[]) # no defensible low-rep e1RM
        records={r['name']:r for r in result['exercise_records']}
        self.assertEqual(records['Pull Up']['historical']['best_reps']['reps'],14)
        self.assertNotIn('best_volume',records['Pull Up']['historical'])
        self.assertEqual(records['Lateral Raise (Dumbbell)']['historical']['best_volume']['kg_repetitions'],160)
        self.assertEqual(records['Lateral Raise (Dumbbell)']['load_convention'],'per_hand')

    def test_single_specialist_leases_and_persistent_conversation(self):
        self.assertFalse(self.store.status()['available'])
        self.assertEqual(self.store.question('question_one','Hello')['state'],'queued')
        self.store.heartbeat()
        self.store.question('question_one','Hello')
        self.store.question('question_two','Follow-up')
        first=self.store.claim();self.assertIsNone(self.store.claim())
        self.now+=121
        second=self.store.claim();self.assertEqual(first['id'],second['id'])
        with self.assertRaises(Conflict): self.store.finish(first['id'],first['token'],'Stale',[])
        self.store.finish(second['id'],second['token'],'Answer',[])
        self.store.finish(second['id'],second['token'],'Answer',[]) # lost HTTP response retry is safe
        self.assertEqual(self.store.claim()['id'],'question_two')
        history=self.store.conversation()
        self.assertEqual([x['question'] for x in history],['Hello','Follow-up'])
        self.assertNotIn('token',history[0])
        self.now+=91;self.assertFalse(self.store.status()['available'])

    def test_blocked_coach_reports_usage_limit_until_its_heartbeat_goes_stale(self):
        self.store.heartbeat('blocked','No coach engine has allowance')
        self.assertEqual(self.store.status()['state'],'blocked')
        self.assertFalse(self.store.status()['available'])
        self.store.heartbeat('busy')
        self.assertEqual((self.store.status()['available'],self.store.status()['state']),(True,'busy'))
        self.now+=91
        self.assertEqual(self.store.status()['state'],'unavailable')

    def test_trainer_proposals_require_approval_and_recheck_revision(self):
        self.store.heartbeat();self.store.question('question_one','Make a template')
        claim=self.store.claim()
        proposal=op('template','plan',{'name':'Plan'})
        self.store.finish(claim['id'],claim['token'],'Proposed only',[proposal])
        self.assertEqual(self.store.list('template')['items'],[])
        self.store.approve(claim['id']);self.store.approve(claim['id'])
        self.assertEqual(len(self.store.list('template')['items']),1)
        self.store.question('question_two','Revise')
        claim=self.store.claim();revision=self.store.get('template','plan')['revision']
        self.store.finish(claim['id'],claim['token'],'New proposal',[op('template','plan',{'name':'Changed'},revision)])
        self.store.mutate([op('template','plan',{'name':'Owner wins'},revision,'owner_change_1')])
        with self.assertRaises(Conflict): self.store.approve(claim['id'])
        self.assertEqual(self.store.get('template','plan')['data']['name'],'Owner wins')

    def test_photo_approval_is_scoped_and_delete_removes_original(self):
        body=b'\xff\xd8\xffsynthetic';digest=hashlib.sha256(body).hexdigest()
        self.store.put_blob(digest,'image/jpeg',body)
        photo=self.store.mutate([op('photo','photo1',dict(captured_at='2026-01-01T07:00:00Z',blob_id=digest))])[0]
        self.store.heartbeat()
        with self.assertRaises(ValueError): self.store.question('question_one','Assess',['photo1'])
        self.store.question('question_one','Assess',['photo1'],True)
        job=self.store.claim()
        assessment=dict(assessed_at='2026-01-01T08:00:00Z',photo_ids=['other'],low_percent=10,high_percent=15,
                        model='test-model',uncertainty='Broad visual range, not clinical.',source_question=job['id'])
        with self.assertRaises(ValueError): self.store.finish(job['id'],job['token'],'Assessment',[],assessment=assessment)
        assessment['photo_ids']=['photo1']
        self.store.finish(job['id'],job['token'],'Assessment',[],assessment=assessment)
        self.assertEqual(len(self.store.list('composition')['items']),1)
        self.store.mutate([op('photo','photo1',{},photo['revision'],deleted=True)])
        with self.assertRaises(Missing): self.store.blob(digest)

    def test_retroactive_set_correction_requires_owner_approval(self):
        data=dict(name='Active',started_at='2026-01-01T12:00:00Z',status='active',sets=[
            dict(id='done',exercise_id='bench',weight_kg=50,reps=5,completed=True),
            dict(id='next',exercise_id='bench',weight_kg=50,reps=5,completed=False)])
        workout=self.store.mutate([op('workout','current',data)])[0]
        self.store.heartbeat();self.store.question('question_one','Equipment occupied')
        claim=self.store.claim()
        changed={**workout['data'],'sets':[dict(s) for s in workout['data']['sets']]}
        changed['sets'][1]['exercise_id']='dumbbell_bench'
        proposal=op('workout','current',changed,workout['revision'])
        damaged={**changed,'sets':[dict(s) for s in changed['sets']]}
        damaged['sets'][0]['weight_kg']=100
        self.store.finish(claim['id'],claim['token'],'Correction and substitution proposed',[{**proposal,'data':damaged}])
        before=self.store.get('workout','current')['data']['sets']
        self.assertEqual(before[0]['weight_kg'],50)
        self.assertEqual(before[1]['exercise_id'],'bench')
        self.store.approve(claim['id'])
        after=self.store.get('workout','current')['data']['sets']
        self.assertEqual(after[0]['weight_kg'],100)
        self.assertEqual(after[1]['exercise_id'],'dumbbell_bench')

    def test_rest_is_not_missed_and_block_timing_survives_round_trip(self):
        sprint=self.store.mutate([op('sprint','sprint1',dict(name='Strength',phase='strength',start='2026-01-01',end='2026-01-14',
            scheduled=[{'date':'2026-01-01'},{'date':'2026-01-03'}]))])[0]
        data=dict(name='Rest and move',started_at='2026-01-01T12:00:00Z',status='rest',sprint_id='sprint1',
            session_changes=[dict(id='move1',at='2026-01-01T10:00:00Z',kind='rest',reason='Rest today, move the session.')],
            blocks=[dict(id='run',kind='run',started_at='2026-01-01T10:00:00Z',ended_at='2026-01-01T10:07:30Z',planned_seconds=450)])
        self.store.mutate([op('workout','rest_day',data),op('workout','done_day',dict(name='Done later',started_at='2026-01-15T12:00:00Z',status='completed',sprint_id='sprint1',source={'companion':{'scheduled_date':'2026-01-03'}}))])
        report=overview(self.store,date(2026,1,5))['sprints'][0]
        self.assertEqual(report['adherence'],1)
        self.assertEqual(report['recovery_adjusted_skips'],1)
        self.assertEqual(len(report['session_changes']),1)
        self.assertEqual(self.store.get('sprint','sprint1')['revision'],sprint['revision'])
        self.assertEqual(self.store.get('workout','rest_day')['data']['blocks'][0]['planned_seconds'],450)

    def test_cached_next_session_brief_does_not_trigger_a_model_and_is_stale_after_edit(self):
        self.store.heartbeat()
        self.assertEqual(self.store.next_session_brief()['status'],'missing')
        self.store.question('question_brief','Prepare next session',context={'purpose':'next_session_brief','session_id':'next1','revision':0})
        claim=self.store.claim();self.store.finish(claim['id'],claim['token'],'A cached brief.',[])
        self.assertEqual(self.store.next_session_brief()['status'],'cached')
        self.store.mutate([op('exercise','bench',{'name':'Bench'})])
        self.assertEqual(self.store.next_session_brief()['status'],'stale')
        self.now+=100
        self.assertEqual(self.store.next_session_brief()['text'],'A cached brief.')
        self.assertFalse(self.store.next_session_brief()['specialist_available'])

    def test_template_keeps_every_planned_set_and_warm_ups_do_not_count_as_hard_sets(self):
        plan=[dict(kind='warmup',reps=8,weight_kg=20),dict(kind='warmup',reps=5,weight_kg=40),dict(reps=5,weight_kg=60),dict(reps=5,weight_kg=60),dict(kind='drop',reps=10,weight_kg=40)]
        saved=self.store.mutate([op('template','push',dict(name='Push',exercises=[dict(exercise_id='bench',set_plan=plan,superset='a')]))])[0]['data']
        self.assertEqual(saved['exercises'][0]['sets'],3)
        self.assertEqual([s['kind'] for s in saved['exercises'][0]['set_plan']],['warmup','warmup','working','working','drop'])
        self.assertEqual(saved['exercises'][0]['superset'],'a')

    def test_coach_can_propose_a_new_exercise_with_its_own_pose(self):
        self.store.heartbeat()
        self.store.question('question_new','Add a landmine press')
        claim=self.store.claim()
        pose=dict(head=[24,10],limbs=[[24,14,24,30],[24,18,34,12]])
        self.store.finish(claim['id'],claim['token'],'Added.',[op('exercise','landmine',dict(name='Landmine Press',equipment='Barbell',movement='press',pose=pose))])
        self.store.approve('question_new')
        self.assertEqual(self.store.get('exercise','landmine')['data']['pose'],pose)

    def test_pose_points_must_stay_on_the_grid(self):
        for pose in (dict(head=[24,99],limbs=[[1,2,3,4]]),dict(head=[24,10],limbs=[[1,2,3]])):
            with self.assertRaises(ValueError): self.store.mutate([op('exercise','bad',dict(name='Bad',pose=pose))])

    def finished(self,identifier='done1',**changes):
        return op('workout',identifier,dict(dict(name='Push',started_at='2026-01-01T18:00:00+00:00',status='completed',source={'companion':{}}),**changes))

    def test_finished_workout_queues_a_brief_even_with_the_coach_offline(self):
        self.store.mutate([op('athlete','self',dict(auto_coach_briefs=True))])
        self.store.mutate([self.finished()])
        self.assertEqual(self.store.workout_briefs()['done1']['state'],'waiting')
        self.assertEqual(self.store.next_session_brief()['status'],'waiting')
        self.store.heartbeat()
        self.assertEqual(self.store.workout_briefs()['done1']['state'],'writing')
        claim=self.store.claim();self.assertEqual(claim['context']['workout_id'],'done1')
        self.store.finish(claim['id'],claim['token'],'Strong session. Add 5 lb to bench next time. Extra detail nobody asked for. More.',[])
        brief=self.store.workout_briefs()['done1']
        self.assertEqual((brief['state'],brief['text']),('ready','Strong session. Add 5 lb to bench next time.'))
        self.store.question('unrelated_chat','Explain this workout',context={'workout_id':'done1'})
        claim=self.store.claim();self.store.finish(claim['id'],claim['token'],'A longer unrelated discussion.',[])
        self.now+=100;self.assertFalse(self.store.status()['available'])
        self.assertEqual(self.store.workout_briefs()['done1']['text'],brief['text'])

    def test_briefs_remove_markdown_and_keep_two_short_sentences(self):
        from personal_assistant.workout.store import brief_text
        self.assertEqual(brief_text('**Strong session.**\n- Keep *one* set next time.\nThird sentence.'),
                         'Strong session. Keep one set next time.')
        self.assertNotIn('**',brief_text('**Next session: A**.\nKeep the load. More.'))

    def test_brief_waits_for_opt_in_and_never_runs_for_imports(self):
        self.store.mutate([op('athlete','self',{})])
        self.store.mutate([self.finished('off')])
        self.store.mutate([op('athlete','self',dict(auto_coach_briefs=True),self.store.get('athlete','self')['revision'])])
        self.store.mutate([self.finished('imported',source={'strong':{}})])
        self.assertEqual(self.store.workout_briefs(),{})

    def test_failed_brief_retries_later_and_deleting_the_workout_cancels_it(self):
        self.store.mutate([op('athlete','self',dict(auto_coach_briefs=True))])
        first=self.store.mutate([self.finished()])[0]
        self.store.heartbeat()
        claim=self.store.claim();self.store.finish(claim['id'],claim['token'],'Failed.',[],'failed')
        self.assertIsNone(self.store.claim())
        self.now+=1801;self.store.heartbeat()
        self.assertEqual(self.store.claim()['id'],'brief_workout_done1')
        self.now+=121;self.store.mutate([self.finished('done2')])
        self.store.mutate([op('workout','done2',{},self.store.get('workout','done2')['revision'],deleted=True)])
        self.assertNotIn('done2',self.store.workout_briefs())

    def lifted(self,identifier,day,weight,reps,rir=1,exercise='bench',source=None):
        sets=[dict(id=identifier+'s',exercise_id=exercise,weight_kg=weight,reps=reps,rir=rir)]
        return op('workout',identifier,dict(name='Push',started_at=day+'T18:00:00+00:00',status='completed',sets=sets,source={'companion':{}} if source is None else source))

    def wins(self,identifier):
        from personal_assistant.workout.wins import session_wins
        return session_wins(self.store.export()['entities'],target=identifier)

    def test_a_session_earns_a_record_only_against_earlier_sessions(self):
        self.store.mutate([op('exercise','bench',{'name':'Bench Press (Barbell)'}),self.lifted('old','2024-01-01',100,5,source={'strong':{}}),self.lifted('one','2026-01-01',60,5),self.lifted('two','2026-01-08',70,5),self.lifted('three','2026-01-15',65,5),self.lifted('top','2026-01-22',105,5)])
        self.assertEqual(self.wins('one'),[])
        record=[w for w in self.wins('two') if w['kind']=='record'][0]
        self.assertEqual((record['scope'],record['metric'],record['previous']),('recent','estimated_max',70.0))
        self.assertEqual([w for w in self.wins('three') if w['kind']=='record'],[])
        record=[w for w in self.wins('top') if w['kind']=='record'][0]
        self.assertEqual((record['scope'],record['metric']),('all_time','estimated_max'))

    def test_a_rank_step_needs_a_hard_set_and_counts_once(self):
        self.store.mutate([op('athlete','self',dict(sex='male')),op('exercise','bench',{'name':'Bench Press (Barbell)'}),
            op('measurement','w1',dict(measured_at='2026-01-01T08:00:00+00:00',kind='bodyweight',value=70,unit='kg')),
            self.lifted('easy','2026-01-02',60,6,rir=5),self.lifted('hard','2026-01-03',60,6,rir=1),self.lifted('same','2026-01-04',60,6,rir=1),self.lifted('up','2026-01-05',100,6,rir=1)])
        self.assertEqual([w for w in self.wins('easy') if w['kind']!='record'],[])
        first=[w for w in self.wins('hard') if w['kind']=='rank'][0]
        self.assertIsNone(first['previous_tier'])
        self.assertEqual({w['kind'] for w in self.wins('hard')}>={'rank','overall'},True)
        self.assertEqual([w for w in self.wins('same') if w['kind']=='rank'],[])
        step=[w for w in self.wins('up') if w['kind']=='rank'][0]
        self.assertEqual(step['previous_tier'],first['tier'])
        self.assertNotEqual(step['tier'],first['tier'])

    def test_the_brief_is_told_what_the_session_achieved(self):
        self.store.mutate([op('athlete','self',dict(auto_coach_briefs=True)),op('exercise','bench',{'name':'Bench Press (Barbell)'}),self.lifted('one','2026-01-01',60,5)])
        self.store.mutate([self.lifted('two','2026-01-08',70,5)])
        rows=self.store.conversation()
        text=[r['question'] for r in rows if r['id']=='brief_workout_two'][0]
        self.assertIn('Bench Press (Barbell)',text);self.assertIn('estimated max',text)

    def test_entered_rir_outranks_imported_rpe_for_a_hard_set(self):
        easy=dict(completed=True,kind='working',weight_kg=60,reps=5,rir=5,rpe=9)
        self.assertIsNone(e1rm(easy,True))
        self.assertIsNotNone(e1rm(dict(easy,rir=None),True))
        self.assertIsNotNone(e1rm(dict(easy,rir=2,rpe=4),True))

    def test_pull_ups_and_push_ups_rank_on_bodyweight_reps(self):
        from personal_assistant.workout.analytics import bodyweight_reps,rank_reps,rep_lift
        self.assertEqual((rep_lift('Pull Up'),rep_lift('Push-Ups'),rep_lift('Pull Up (Assisted)')),('pull up','push up',None))
        self.assertEqual(rank_reps('pull up',14,70,'male')['score'],600)
        self.assertEqual(rank_reps('push up',40,70,'male')['score'],600)
        plain=dict(completed=True,kind='working',reps=10,weight_kg=0)
        self.assertEqual(bodyweight_reps(plain,70),10)
        self.assertAlmostEqual(bodyweight_reps(dict(plain,weight_kg=7),70),(77*(1+10/30)/70-1)*30)
        self.assertIsNone(bodyweight_reps(dict(plain,rir=5),70))

    def test_a_weighted_pull_up_counts_toward_the_same_rank(self):
        self.store.mutate([op('athlete','self',dict(sex='male')),op('exercise','pull',{'name':'Pull Up','muscles':['back']}),
            op('measurement','w1',dict(measured_at='2026-01-01T08:00:00+00:00',kind='bodyweight',value=70,unit='kg'))])
        self.store.mutate([self.lifted('one','2026-01-02',0,8,exercise='pull'),self.lifted('two','2026-01-03',14,8,exercise='pull')])
        summary=overview(self.store,date(2026,1,4))
        lift=[r for r in summary['lift_ranks'] if r['exercise_name']=='Pull Up'][0]
        self.assertEqual(lift['status'],'ranked')
        self.assertGreater(lift['estimated_reps'],14)
        self.assertEqual(summary['rank_coverage']['supported_lifts'],6)
        self.assertEqual([w['kind'] for w in self.wins('one')],['rank','overall'])
        self.assertIn('rank',[w['kind'] for w in self.wins('two')])
        push=[r for r in summary['lift_ranks'] if r['exercise_name']=='Push Up'][0]
        self.assertEqual((push['status'],push['exercise_id']),('no_recent_set',None))

    def test_most_reps_is_a_record_for_bodyweight_work(self):
        self.store.mutate([op('exercise','pull',{'name':'Pull Up'}),self.lifted('one','2026-01-02',0,8,exercise='pull'),self.lifted('two','2026-01-03',0,10,exercise='pull')])
        record=[w for w in self.wins('two') if w['kind']=='record'][0]
        self.assertEqual((record['metric'],record['reps']),('most_reps',10))

    def sprint_rows(self):
        self.store.mutate([op('athlete','self',dict(auto_coach_briefs=True)),op('template','push',dict(name='Push')),
            op('sprint','one',dict(name='One',phase='strength',start='2026-01-01',end='2026-03-01',status='active',cycle=['push'],target_sessions=2))])

    def test_a_completed_sprint_queues_one_short_review(self):
        self.sprint_rows()
        current=self.store.get('sprint','one')
        self.store.mutate([op('sprint','one',dict(current['data'],status='completed'),current['revision'])])
        self.assertEqual(self.store.sprint_briefs()['one']['state'],'waiting')
        self.store.heartbeat();claim=self.store.claim();self.assertEqual(claim['id'],'brief_sprint_one')
        self.store.finish(claim['id'],claim['token'],'Bench climbed. Sleep held you back. Next, build squat volume. A fourth sentence.',[])
        self.assertEqual(self.store.sprint_briefs()['one']['text'],'Bench climbed. Sleep held you back. Next, build squat volume.')
        self.assertEqual(overview(self.store,date(2026,3,2))['sprint_history'][0]['brief']['state'],'ready')

    def test_a_sprint_past_its_deadline_gets_its_review_without_being_marked(self):
        from datetime import datetime,timezone
        self.sprint_rows();self.store.heartbeat()
        self.now=datetime(2026,3,5,tzinfo=timezone.utc).timestamp();self.store.heartbeat()
        self.store.prepare_brief('UTC')
        self.assertIn('one',self.store.sprint_briefs())

    def test_sprint_history_sums_what_the_sprint_came_to(self):
        self.sprint_rows()
        self.store.mutate([op('exercise','bench',{'name':'Bench Press (Barbell)'})])
        one=self.lifted('a','2026-01-02',60,5);one['data']['sprint_id']='one'
        two=self.lifted('b','2026-01-03',70,5);two['data']['sprint_id']='one'
        self.store.mutate([one,two])
        entry=overview(self.store,date(2026,1,4))['sprint_history'][0]
        self.assertEqual((entry['completed'],entry['target_sessions'],entry['records'],entry['ended']),(2,2,1,False))
        self.assertEqual(entry['volume_kg_reps'],650)

    def test_today_follows_the_owners_timezone_not_utc(self):
        from personal_assistant.workout.analytics import local_today
        rows=[dict(kind='workout',deleted=False,data=dict(started_at='2026-01-01T00:00:00+13:00',timezone='Pacific/Auckland'))]
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.assertEqual(local_today(rows),datetime.now(ZoneInfo('Pacific/Auckland')).date())

    def test_a_rank_stands_for_six_months(self):
        self.store.mutate([op('athlete','self',dict(sex='male')),op('exercise','bench',{'name':'Bench Press (Barbell)'}),
            op('measurement','w1',dict(measured_at='2026-01-01T08:00:00+00:00',kind='bodyweight',value=70,unit='kg')),self.lifted('hard','2026-01-02',60,6)])
        status=lambda day:overview(self.store,day)['lift_ranks'][0]['status']
        self.assertEqual(status(date(2026,6,30)),'ranked')
        self.assertEqual(status(date(2026,7,10)),'no_recent_set')
        self.assertEqual(overview(self.store,date(2026,1,3))['rank_coverage']['window_days'],183)

    def test_running_rank_uses_published_levels_at_any_distance(self):
        from personal_assistant.workout.analytics import run_levels,running_rank
        self.assertAlmostEqual(1609.344/run_levels(1609.344,'male')[2],363)
        self.assertAlmostEqual(5000/run_levels(5000,'male')[4],1050)
        run=dict(date='2026-01-05',distance_m=5000,seconds=1361)
        rank_=running_rank([run],date(2026,1,6),'male')
        self.assertEqual((rank_['score'],rank_['percentile'],rank_['tier']),(600,50,'Emerald 4'))
        self.assertEqual(rank_['next_tier'],'Emerald 3')
        self.assertLess(rank_['next_1_5mi_seconds'],720)

    def test_running_rank_ignores_short_hilly_and_old_runs(self):
        from personal_assistant.workout.analytics import running_rank
        base=dict(date='2026-01-05',distance_m=5000,seconds=1361)
        for run in (dict(base,distance_m=500,seconds=100),dict(base,incline_percent=4),dict(base,date='2025-01-05')):
            self.assertEqual(running_rank([run],date(2026,1,6),'male')['status'],'no_recent_run')
        self.assertEqual(running_rank([base],date(2026,1,6),'unspecified')['status'],'needs_profile')

    def test_a_running_rank_step_is_a_win_and_stays_out_of_the_overall_rank(self):
        self.store.mutate([op('athlete','self',dict(sex='male')),op('exercise','run',{'name':'Running','mode':'cardio','movement':'run'})])
        def jog(identifier,day,seconds):
            return op('workout',identifier,dict(name='Run',started_at=day+'T18:00:00+00:00',status='completed',source={'companion':{}},
                sets=[dict(id=identifier+'s',exercise_id='run',kind='working',distance_m=5000,seconds=seconds)]))
        self.store.mutate([jog('a','2026-01-02',1800),jog('b','2026-01-03',1500),jog('c','2026-01-04',1600)])
        self.assertEqual([w['kind'] for w in self.wins('a')],['rank'])
        self.assertIn('rank',[w['kind'] for w in self.wins('b')])
        self.assertNotIn('rank',[w['kind'] for w in self.wins('c')])
        summary=overview(self.store,date(2026,1,5))
        self.assertIsNone(summary['aggregate_score'])
        self.assertEqual(summary['running']['rank']['status'],'ranked')

    def test_percentile_follows_the_published_levels(self):
        from personal_assistant.workout.analytics import percentile
        self.assertEqual([percentile(s) for s in (0,200,400,600,800,1000)],[0,5,20,50,80,95])
        self.assertEqual(percentile(500),35)
        self.assertEqual(rank('Bench Press (Barbell)',70,70,'male')['percentile'],20)

    def test_ranks_climb_league_style_through_divisions(self):
        from personal_assistant.workout.analytics import TIERS
        names=dict(TIERS)
        self.assertEqual((names[0],names[150],names[200],names[300],names[375],names[400]),('Iron 4','Iron 1','Bronze 4','Silver 4','Silver 1','Gold 4'))
        self.assertEqual((names[775],names[800],names[900],names[950]),('Diamond 1','Master','Grandmaster','Challenger'))
        self.assertEqual(len(TIERS),31)
        result=rank('Bench Press (Barbell)',60,70,'male')
        self.assertRegex(result['tier'],r'^[A-Z][a-z]+ [1-4]$')
        floors=[floor for floor,_ in TIERS];self.assertEqual(floors,sorted(set(floors)))

    def test_automatic_brief_needs_owner_opt_in_and_deduplicates(self):
        from datetime import datetime,timezone
        self.now=datetime(2026,1,1,tzinfo=timezone.utc).timestamp()
        profile=self.store.mutate([op('athlete','self',{})])[0]
        self.store.mutate([op('sprint','sprint1',dict(name='Next sprint',phase='strength',start='2026-01-01',end='2026-01-14',
            scheduled=[{'date':'2026-01-03','template_id':'plan'}]))])
        self.assertFalse(self.store.prepare_brief()['queued'])
        self.store.mutate([op('athlete','self',{**profile['data'],'auto_coach_briefs':True},profile['revision'])])
        self.assertFalse(self.store.prepare_brief()['queued']) # wait for stable inputs
        self.now+=121
        self.assertTrue(self.store.prepare_brief()['queued'])
        self.assertEqual(self.store.next_session_brief()['status'],'waiting')
        self.assertFalse(self.store.prepare_brief()['queued'])
        self.store.heartbeat()
        claim=self.store.claim()
        self.assertEqual(claim['photos'],[])
        self.assertTrue(claim['context']['automatic'])
        self.store.finish(claim['id'],claim['token'],'A prepared session brief.',[])
        self.assertFalse(self.store.prepare_brief()['queued'])

    def test_personal_body_goal_does_not_reward_a_lower_waist_or_invent_muscularity(self):
        self.store.mutate([op('athlete','self',dict(height_cm=180,target_weight_min_kg=75,target_weight_max_kg=80,waist_height_ceiling=.5)),
            op('measurement','weight',dict(measured_at='2026-01-01T07:00:00Z',kind='bodyweight',value=76,unit='kg')),
            op('measurement','waist',dict(measured_at='2026-01-01T07:00:00Z',kind='waist',value=85,unit='cm'))])
        result=overview(self.store,date(2026,1,2))
        self.assertEqual(result['body_rank']['score'],100)
        self.assertEqual(result['body_rank']['scope'],'personal_nonclinical')
        waist=self.store.get('measurement','waist')
        self.store.mutate([op('measurement','waist',{**waist['data'],'value':80},waist['revision'])])
        self.assertEqual(overview(self.store,date(2026,1,2))['body_rank']['score'],100)
        weight=self.store.get('measurement','weight')
        self.store.mutate([op('measurement','weight',{**weight['data'],'value':70},weight['revision'])])
        self.assertEqual(overview(self.store,date(2026,1,2))['body_rank']['score'],0)
        self.assertEqual(overview(self.store,date(2026,3,1))['body_rank']['status'],'stale')


class WorkoutApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.app=create_app(root/'queue.sqlite3','s'*40,'w'*40,
            groceries={'path':root/'groceries.sqlite3','internal_token':'g'*40,'assets':root})
        self.client=TestClient(self.app)
        devices=self.app.state.mobile_events.devices
        phone=devices.exchange(devices.pairing()['code'],'Synthetic')
        self.headers={'Authorization':'Bearer '+phone['token']}
        self.owner={'Authorization':'Bearer '+'s'*40}
        self.prefix='/groceries/v1/mobile/workout'

    def tearDown(self): self.client.close();self.tmp.cleanup()

    def test_runner_assigns_photo_provenance_instead_of_trusting_model_id(self):
        from personal_assistant.workout.specialist import run_once
        store=self.app.state.workouts;app_client=self.client;headers=self.owner
        class Client:
            def call(self,path,payload=None,method=None):
                response=app_client.request(method or ('POST' if payload is not None else 'GET'),
                    path.removeprefix('/relay'),json=payload,headers=headers)
                response.raise_for_status();return response.json()
        raw=b'\xff\xd8\xffsynthetic';digest=hashlib.sha256(raw).hexdigest()
        store.put_blob(digest,'image/jpeg',raw)
        store.mutate([op('photo','front',dict(captured_at='2026-01-01T07:00:00Z',blob_id=digest))])
        store.heartbeat();store.question('photo_job','Estimate this photo',['front'],True)
        def invoke(*args):
            return dict(text='A rough visual range.',memory_summary='Approved baseline.',proposals=[],
                assessment_json=json.dumps(dict(low_percent=12,high_percent=17,photo_ids=['front'],
                    source_question='A model-authored description, not an identifier',model='untrusted',
                    assessed_at='2020-01-01T00:00:00Z',uncertainty='Lighting limits precision.')))
        with patch('personal_assistant.workout.specialist.download_photos',return_value=[]):
            self.assertTrue(run_once(Client(),{},Path('synthetic-config.json'),{},invoke))
        result=store.get('composition','photo_job')['data']
        self.assertEqual(result['source_question'],'photo_job')
        self.assertEqual(result['model'],'gpt-6-sol')
        self.assertNotEqual(result['assessed_at'],'2020-01-01T00:00:00Z')
        self.assertEqual(result['photo_ids'],['front'])

    def test_coach_sees_when_photos_were_taken_and_what_was_already_analysed(self):
        from personal_assistant.workout.specialist import run_once
        store=self.app.state.workouts;app_client=self.client;headers=self.owner
        class Client:
            def call(self,path,payload=None,method=None):
                response=app_client.request(method or ('POST' if payload is not None else 'GET'),
                    path.removeprefix('/relay'),json=payload,headers=headers)
                response.raise_for_status();return response.json()
        raw=b'\xff\xd8\xffsynthetic';digest=hashlib.sha256(raw).hexdigest()
        store.put_blob(digest,'image/jpeg',raw)
        store.mutate([op('photo','front',dict(captured_at='2026-01-01T07:00:00Z',blob_id=digest,sprint_id='one')),
                      op('composition','first',dict(assessed_at='2026-01-02T07:00:00Z',photo_ids=['front'],low_percent=12,high_percent=17,model='m',uncertainty='Rough.',source_question='q'))])
        store.heartbeat();store.question('photo_again','Compare again',['front'],True)
        seen={}
        def invoke(config,config_file,state,job,images,workspace):
            seen.update(job['photo_context'])
            return dict(text='The same image as before.',memory_summary='',proposals=[],assessment_json='')
        with patch('personal_assistant.workout.specialist.download_photos',return_value=[]):
            self.assertTrue(run_once(Client(),{},Path('synthetic-config.json'),{},invoke))
        self.assertEqual(seen['capture_days'],['2026-01-01'])
        self.assertEqual(seen['photos'][0]['sprint_id'],'one')
        self.assertEqual(seen['earlier_analyses'][0]['same_images_as_this_job'],['front'])
        self.assertEqual(seen['earlier_analyses'][0]['assessed_at'],'2026-01-02T07:00:00Z')

    def test_authentication_and_atomic_phone_sync(self):
        self.assertEqual(self.client.get(self.prefix+'/overview').status_code,401)
        result=self.client.post(self.prefix+'/sync',headers=self.headers,json={'operations':[op('exercise','bench',{'name':'Bench'})]})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.get(self.prefix+'/changes',headers=self.headers).json()['cursor'],1)
        self.assertEqual(self.client.put('/v1/workout/trainer/heartbeat',headers=self.headers,json={'state':'ready'}).status_code,401)
        self.assertEqual(self.client.post(self.prefix+'/sync',headers=self.headers,json={'operations':[op('exercise','bench',{'name':'Stale'},mutation='stale_mutation')]}).status_code,409)

    def test_streaming_import_and_auth_scoped_photo_access(self):
        raw=strong_csv([{}])
        response=self.client.post(self.prefix+'/imports/strong?commit=true',headers=self.headers,content=raw)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['workouts'],1)
        body=b'\x89PNG\r\n\x1a\nsynthetic';digest=hashlib.sha256(body).hexdigest()
        url=self.prefix+'/photos/'+digest
        self.assertEqual(self.client.put(url,headers={**self.headers,'Content-Type':'image/png'},content=body).status_code,200)
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get(url,headers=self.headers).content,body)
        self.assertEqual(self.client.put(url,headers={**self.headers,'Content-Type':'text/html'},content=body).status_code,422)

    def test_specialist_pipeline_with_fake_model_keeps_session_and_requires_approval(self):
        from personal_assistant.workout.specialist import run_once
        app_client=self.client;headers=self.owner
        class Client:
            def call(self,path,payload=None,method=None):
                response=app_client.request(method or ('POST' if payload is not None else 'GET'),
                    path.removeprefix('/relay'),json=payload,headers=headers)
                response.raise_for_status();return response.json()
        transport=Client();state={};calls=[]
        def invoke(config,config_file,current,job,images,workspace):
            calls.append((current.get('session'),job['question']))
            current['session']='synthetic-persistent-session'
            return dict(text='A proposed template, awaiting approval.',memory_summary='Owner chose a low-volume sprint.',
                assessment_json='',proposals=[dict(kind='template',id='plan',base_revision=0,
                    data_json=json.dumps({'name':'Proposed plan'}),reason='Matches selected sprint goal.')])
        self.app.state.workouts.heartbeat()
        self.app.state.workouts.question('question_one','Make a plan')
        self.assertTrue(run_once(transport,{},Path('synthetic-config.json'),state,invoke))
        self.assertEqual(self.app.state.workouts.list('template')['items'],[])
        self.assertEqual(state['memory'],'Owner chose a low-volume sprint.')
        self.app.state.workouts.question('question_two','Keep discussing')
        self.assertTrue(run_once(transport,{},Path('synthetic-config.json'),state,invoke))
        self.assertEqual(calls,[ (None,'Make a plan'),('synthetic-persistent-session','Keep discussing') ])
        turns=self.app.state.workouts.conversation()
        self.assertTrue(all(t['state']=='completed' for t in turns))
        self.app.state.workouts.approve('question_one')
        self.assertEqual(self.app.state.workouts.get('template','plan')['data']['name'],'Proposed plan')


if __name__=='__main__': unittest.main()
