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
        with self.assertRaises(Conflict): self.store.question('question_one','Hello')
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

    def test_automatic_brief_needs_owner_opt_in_and_deduplicates(self):
        from datetime import datetime,timezone
        self.now=datetime(2026,1,1,tzinfo=timezone.utc).timestamp()
        profile=self.store.mutate([op('athlete','self',{})])[0]
        self.store.mutate([op('sprint','sprint1',dict(name='Next sprint',phase='strength',start='2026-01-01',end='2026-01-14',
            scheduled=[{'date':'2026-01-03','template_id':'plan'}]))])
        self.store.heartbeat()
        self.assertFalse(self.store.prepare_brief()['queued'])
        self.store.mutate([op('athlete','self',{**profile['data'],'auto_coach_briefs':True},profile['revision'])])
        self.assertFalse(self.store.prepare_brief()['queued']) # wait for stable inputs
        self.now+=121;self.store.heartbeat()
        self.assertTrue(self.store.prepare_brief()['queued'])
        self.assertFalse(self.store.prepare_brief()['queued'])
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
