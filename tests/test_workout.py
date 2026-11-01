"""Workout invariants: source preservation, offline conflicts, consent and specialist fencing."""
import csv
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
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
