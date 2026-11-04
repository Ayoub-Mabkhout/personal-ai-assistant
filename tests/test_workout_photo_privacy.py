"""Encrypted progress photos: plaintext exists only while shared for a purpose. Synthetic bytes only."""
import hashlib
from pathlib import Path
import secrets
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from personal_assistant.relay.store import Conflict,Missing
from personal_assistant.workout.private_vault import PrivateVault
from personal_assistant.workout.reminder import TrainReminders
from personal_assistant.workout.store import Workouts
from personal_assistant.workout.web import mount_train
from test_workout_private_vault import AUTH,SALT,encrypted,wrapped


PNG=b'\x89PNG\r\n\x1a\n'


def op(kind,id,data,base=0,mutation=None,deleted=False):
    return dict(mutation_id=mutation or ('mutation_'+id+'_'+str(base)),kind=kind,id=id,base_revision=base,data=data,deleted=deleted)


def image(label):
    body=PNG+b'synthetic '+label.encode();return hashlib.sha256(body).hexdigest(),body


def vault_photo(**extra):
    return dict(captured_at='2026-01-01T07:00:00Z',vault=True,**extra)


class PhotoPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.workouts=Workouts(self.root/'workouts.sqlite3')
        PrivateVault(self.workouts)
        self.store=self.workouts.for_user('athlete')

    def seal(self,identifier):
        """Stand-in for the client's encrypted object; the server never sees the key."""
        with self.workouts.db() as db:
            db.execute("INSERT INTO train_vault_objects VALUES(?,?,?,?,?,?,?)",
                       ('athlete','photo',identifier,'key',1,'{}',0))

    def vault_row(self,identifier):
        with self.workouts.db() as db:
            return db.execute("SELECT 1 FROM train_vault_objects WHERE user_id='athlete' AND kind='photo' AND id=?",(identifier,)).fetchone()

    def blob_exists(self,digest):
        try:self.store.blob(digest);return True
        except Missing:return False

    def share(self,identifier,label='shared'):
        digest,body=image(label);self.store.put_blob(digest,'image/png',body)
        row=self.store.get('photo',identifier)
        self.store.mutate([op('photo',identifier,{**row['data'],'shared_blob_id':digest},row['revision'])])
        return digest

    def ask(self,identifier,photos):
        self.store.heartbeat();self.store.question(identifier,'Assess',photos,True)
        return self.store.claim()

    def test_vault_photo_needs_its_encrypted_object_and_no_plaintext_original(self):
        with self.assertRaisesRegex(ValueError,'Encrypt'):self.store.mutate([op('photo','p1',vault_photo())])
        digest,body=image('original');self.store.put_blob(digest,'image/png',body)
        self.seal('p1')
        with self.assertRaises(ValueError):self.store.mutate([op('photo','p1',vault_photo(blob_id=digest))])
        with self.assertRaises(ValueError):
            self.store.mutate([op('photo','p2',dict(captured_at='2026-01-01T07:00:00Z',blob_id=digest,shared_blob_id=digest))])
        with self.assertRaisesRegex(ValueError,'shared photo'):
            self.store.mutate([op('photo','p1',vault_photo(shared_blob_id='0'*64))])
        saved=self.store.mutate([op('photo','p1',vault_photo())])[0]
        self.assertTrue(saved['data']['vault']);self.assertIsNone(saved['data']['blob_id'])

    def test_vault_photos_are_unavailable_without_identity_tables(self):
        plain=Workouts(self.root/'plain.sqlite3').for_user('athlete')
        with self.assertRaisesRegex(ValueError,'Encrypt'):plain.mutate([op('photo','p1',vault_photo())])

    def test_coach_needs_a_share_and_finishing_deletes_the_shared_copy(self):
        self.seal('p1');self.store.mutate([op('photo','p1',vault_photo())])
        self.store.heartbeat()
        with self.assertRaisesRegex(ValueError,'Share the chosen photos'):self.store.question('q1','Assess',['p1'],True)
        digest=self.share('p1')
        job=self.ask('q1',['p1'])
        self.assertTrue(self.blob_exists(digest))
        self.store.finish(job['id'],job['token'],'Looks consistent.',[])
        self.assertFalse(self.blob_exists(digest))
        # Not left behind in free pages or the write-ahead log either.
        body=image('shared')[1]
        for path in self.root.glob('workouts.sqlite3*'):self.assertNotIn(body,path.read_bytes(),path.name)
        row=self.store.get('photo','p1')
        self.assertIsNone(row['data']['shared_blob_id']);self.assertTrue(row['data']['vault'])
        self.assertTrue(self.vault_row('p1'))
        # A retried finish is idempotent and leaves nothing to re-share.
        self.store.finish(job['id'],job['token'],'Looks consistent.',[])

    def test_failed_answer_also_ends_the_share_but_a_pending_question_keeps_it(self):
        self.seal('p1');self.store.mutate([op('photo','p1',vault_photo())])
        digest=self.share('p1');self.store.heartbeat()
        self.store.question('q1','Assess',['p1'],True);self.store.question('q2','Compare',['p1'],True)
        first=self.store.claim();self.store.finish(first['id'],first['token'],'Engine failed.',[],state='failed')
        self.assertTrue(self.blob_exists(digest))
        second=self.store.claim();self.store.finish(second['id'],second['token'],'Done.',[])
        self.assertFalse(self.blob_exists(digest))

    def test_reminder_share_survives_finish_and_unshared_vault_photo_is_refused(self):
        reminders=TrainReminders(self.workouts,None)
        self.seal('p1');self.store.mutate([op('photo','p1',vault_photo())])
        with self.assertRaisesRegex(ValueError,'Share this photo for reminders first'):
            reminders.settings('athlete',{'photo_ids':['p1']})
        with self.assertRaises(Missing):reminders.settings('athlete',{'photo_ids':['nobody']})
        digest=self.share('p1')
        self.assertEqual(reminders.settings('athlete',{'photo_ids':['p1']})['photo_ids'],['p1'])
        with self.workouts.db() as db:
            self.assertEqual(TrainReminders.photo(db,'athlete','p1'),'/train/api/photos/'+digest)
        job=self.ask('q1',['p1']);self.store.finish(job['id'],job['token'],'Done.',[])
        self.assertTrue(self.blob_exists(digest))
        self.assertEqual(self.store.get('photo','p1')['data']['shared_blob_id'],digest)
        # Unsharing (deselected from reminders) removes the plaintext copy.
        row=self.store.get('photo','p1')
        self.store.mutate([op('photo','p1',{**row['data'],'shared_blob_id':None},row['revision'])])
        self.assertFalse(self.blob_exists(digest))
        with self.workouts.db() as db:self.assertIsNone(TrainReminders.photo(db,'athlete','p1'))

    def test_migrating_a_plaintext_photo_deletes_its_original_unless_shared(self):
        reminders=TrainReminders(self.workouts,None)
        kept,kept_body=image('kept');gone,gone_body=image('gone')
        for digest,body in ((kept,kept_body),(gone,gone_body)):self.store.put_blob(digest,'image/png',body)
        legacy=self.store.mutate([op('photo','kept',dict(captured_at='2026-01-01T07:00:00Z',blob_id=kept)),
                                  op('photo','gone',dict(captured_at='2026-01-01T07:00:00Z',blob_id=gone,pose='side'))])
        reminders.settings('athlete',{'photo_ids':['kept']})
        self.seal('kept');self.seal('gone')
        self.store.mutate([op('photo','kept',vault_photo(shared_blob_id=kept),legacy[0]['revision']),
                           op('photo','gone',vault_photo(pose='side'),legacy[1]['revision'])])
        self.assertTrue(self.blob_exists(kept));self.assertFalse(self.blob_exists(gone))
        with self.workouts.db() as db:
            self.assertEqual(TrainReminders.photo(db,'athlete','kept'),'/train/api/photos/'+kept)

    def test_shared_blob_is_kept_while_another_photo_references_it(self):
        digest,body=image('same');self.store.put_blob(digest,'image/png',body)
        legacy=self.store.mutate([op('photo','legacy',dict(captured_at='2026-01-01T07:00:00Z',blob_id=digest))])[0]
        self.seal('p1');self.store.mutate([op('photo','p1',vault_photo(shared_blob_id=digest))])
        row=self.store.get('photo','p1')
        self.store.mutate([op('photo','p1',{**row['data'],'shared_blob_id':None},row['revision'])])
        self.assertTrue(self.blob_exists(digest))
        self.store.mutate([op('photo','legacy',{},legacy['revision'],deleted=True)])
        self.assertFalse(self.blob_exists(digest))

    def test_deleting_a_vault_photo_deletes_its_encrypted_object_and_share(self):
        self.seal('p1');self.store.mutate([op('photo','p1',vault_photo())])
        digest=self.share('p1');row=self.store.get('photo','p1')
        self.store.mutate([op('photo','p1',{},row['revision'],deleted=True)])
        self.assertIsNone(self.vault_row('p1'));self.assertFalse(self.blob_exists(digest))

    def test_legacy_plaintext_photos_behave_as_before(self):
        digest,body=image('legacy');self.store.put_blob(digest,'image/png',body)
        with self.assertRaisesRegex(ValueError,'Upload the photo first'):
            self.store.mutate([op('photo','p0',dict(captured_at='2026-01-01T07:00:00Z',blob_id='1'*64))])
        photo=self.store.mutate([op('photo','p1',dict(captured_at='2026-01-01T07:00:00Z',blob_id=digest))])[0]
        job=self.ask('q1',['p1']);self.store.finish(job['id'],job['token'],'Done.',[])
        self.assertTrue(self.blob_exists(digest))
        self.assertEqual(self.store.get('photo','p1')['revision'],photo['revision'])
        updated=self.store.mutate([op('photo','p1',{**photo['data'],'notes':'Morning'},photo['revision'])])[0]
        self.assertTrue(self.blob_exists(digest))
        self.store.mutate([op('photo','p1',{},updated['revision'],deleted=True)])
        self.assertFalse(self.blob_exists(digest))


class PhotoPrivacyWebTests(unittest.TestCase):
    """The browser flow end to end through the HTTP API: ciphertext in, plaintext only when shared."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.workouts=Workouts(self.root/'workouts.sqlite3')
        app=FastAPI()
        for error,status in ((Conflict,409),(Missing,404),(ValueError,422)):
            async def handle(request,exc,code=status):return JSONResponse({'detail':str(exc)},status_code=code)
            app.add_exception_handler(error,handle)
        mount_train(app,self.workouts,lambda:None,self.root/'no-assets',require_identity=True)
        self.client=TestClient(app,base_url='https://train.test');self.addCleanup(self.client.close)

    def test_encrypted_upload_share_and_unshare(self):
        response=self.client.post('/train/api/auth/register',json={'name':'Synthetic Athlete','auth_secret':AUTH,'client_salt':SALT})
        self.assertEqual(response.status_code,200,response.text);user=response.json()['id']
        record=wrapped(user)
        self.assertEqual(self.client.put('/train/api/vault/key-envelope',json={'base_revision':0,'record':record}).status_code,200)
        sealed=encrypted(user,record['keyId'],'photo','p1',size=256)
        self.assertEqual(self.client.put('/train/api/vault/records/photo/p1',json={'base_revision':0,'envelope':sealed}).status_code,200)
        sync=lambda ops:self.client.post('/train/api/sync',json={'operations':ops})
        created=sync([op('photo','p1',vault_photo())])
        self.assertEqual(created.status_code,200,created.text)
        with self.workouts.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM blobs').fetchone()[0],0)
        asked=self.client.post('/train/api/trainer/questions',json={'id':'question1','text':'Assess','photos':['p1'],'photo_approval':True})
        self.assertEqual(asked.status_code,422,asked.text)
        digest,body=image('share')
        self.assertEqual(self.client.put('/train/api/photos/'+digest,content=body,headers={'Content-Type':'image/png'}).status_code,200)
        revision=created.json()['results'][0]['revision']
        self.assertEqual(sync([op('photo','p1',vault_photo(shared_blob_id=digest),revision)]).status_code,200)
        asked=self.client.post('/train/api/trainer/questions',json={'id':'question1','text':'Assess','photos':['p1'],'photo_approval':True})
        self.assertEqual(asked.status_code,200,asked.text)
        self.assertEqual(self.client.get('/train/api/photos/'+digest).content,body)


if __name__=='__main__':
    unittest.main()
