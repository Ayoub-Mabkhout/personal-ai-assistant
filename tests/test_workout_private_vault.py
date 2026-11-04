"""Opt-in password routes and opaque vault isolation, with synthetic envelopes."""
from copy import deepcopy
import hashlib
from pathlib import Path
import secrets
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from personal_assistant.relay.store import Conflict,Missing
from personal_assistant.workout.identity import b64,CLIENT_KDF_VERSION,CLIENT_KDF_ITERATIONS
from personal_assistant.workout.private_vault import PrivateVault,MAX_CIPHER_BYTES,ciphertext
from personal_assistant.workout.store import Workouts
from personal_assistant.workout.web import Accounts,mount_train,COOKIE


AUTH=b64(b'a'*32);SALT=b64(b'c'*16)


def encrypted(user,key,kind,identifier,revision=1,*,size=48,nonce=None):
    return {'version':1,'userId':user,'keyId':key,'kind':kind,'objectId':identifier,
            'revision':revision,'nonceB64':b64(nonce or secrets.token_bytes(12)),
            'cipherB64':b64(secrets.token_bytes(size))}


def wrapped(user):
    key=b64(secrets.token_bytes(16))
    return {'version':1,'userId':user,'keyId':key,
        'password':{'parameters':{'version':CLIENT_KDF_VERSION,'kdf':'PBKDF2','hash':'SHA-256',
                                  'iterations':CLIENT_KDF_ITERATIONS,'salt':SALT},
                    'wrappedMaster':encrypted(user,key,'vault-password-key',key)},
        'recovery':{'salt':b64(secrets.token_bytes(16)),
                    'wrappedMaster':encrypted(user,key,'vault-recovery-key',key)}}


class WorkoutPrivateVaultTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.workouts=Workouts(self.root/'workouts.sqlite3')
        self.accounts=Accounts(self.workouts)
        self.app=self.make_app(True)

    def make_app(self,enabled):
        app=FastAPI()
        for error,status in ((Conflict,409),(Missing,404),(ValueError,422)):
            async def handle(request,exc,code=status):return JSONResponse({'detail':str(exc)},status_code=code)
            app.add_exception_handler(error,handle)
        def owner():pass
        mount_train(app,self.workouts,owner,self.root/'no-assets',require_identity=enabled)
        return app

    def client(self,app=None):
        client=TestClient(app or self.app,base_url='https://train.test');self.addCleanup(client.close)
        return client

    def invite(self,user_id=None):
        return self.accounts.invite(user_id)['invite']

    def enroll(self,name='Synthetic Athlete'):
        client=self.client();response=client.post('/train/api/auth/register',json={'name':name,'auth_secret':AUTH,'client_salt':SALT,'invite':self.invite()})
        self.assertEqual(response.status_code,200,response.text)
        return client,response.json()['id']

    def key(self,client,user):
        record=wrapped(user)
        response=client.put('/train/api/vault/key-envelope',json={'base_revision':0,'record':record})
        self.assertEqual(response.status_code,200,response.text)
        return record

    def test_auth_cookie_login_logout_and_no_name_only_join_when_enabled(self):
        client,user=self.enroll();me=client.get('/train/api/me')
        self.assertEqual(me.json()['id'],user);self.assertTrue(me.json()['migration_required'])
        self.assertEqual(client.post('/train/api/join',json={'name':'Other Name'}).status_code,403)
        logged=client.post('/train/api/auth/login',json={'name':'Synthetic Athlete','auth_secret':AUTH})
        self.assertEqual(logged.status_code,200)
        for flag in ('HttpOnly','Secure','SameSite=strict'):self.assertIn(flag,logged.headers['set-cookie'])
        self.assertIn('no-store',logged.headers['cache-control'])
        self.assertEqual(client.post('/train/api/auth/logout').status_code,200)
        self.assertEqual(client.get('/train/api/me').status_code,401)

    def test_registration_needs_a_single_use_invite(self):
        client=self.client();body={'name':'Open Door','auth_secret':AUTH,'client_salt':SALT}
        self.assertEqual(client.post('/train/api/auth/register',json=body).status_code,422)
        self.assertEqual(client.post('/train/api/auth/register',json={**body,'invite':'x'*43}).status_code,403)
        invite=self.invite()
        self.assertEqual(client.post('/train/api/auth/register',json={**body,'invite':invite}).status_code,200)
        again=self.client().post('/train/api/auth/register',json={**body,'name':'Second Try','invite':invite})
        self.assertEqual(again.status_code,403)

    def test_an_invite_for_an_existing_profile_sets_its_first_password(self):
        original,_=self.accounts.join('Returning Athlete')
        client=self.client();body={'auth_secret':AUTH,'client_salt':SALT}
        # The link is for that profile only: another name is refused and the invite is spent.
        self.assertEqual(client.post('/train/api/auth/register',json={**body,'name':'Someone Else','invite':self.invite(original['id'])}).status_code,409)
        response=client.post('/train/api/auth/register',json={**body,'name':'returning  athlete','invite':self.invite(original['id'])})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['id'],original['id'])
        self.assertEqual(client.get('/train/api/me').json()['id'],original['id'])
        # Once it has a password, a second link for it can't replace that password.
        self.assertEqual(self.client().post('/train/api/auth/register',json={**body,'name':'Returning Athlete','invite':self.invite(original['id'])}).status_code,409)

    def test_auth_rejects_raw_passwords_secret_keys_and_cross_site_calls(self):
        client=self.client()
        body={'name':'Synthetic Athlete','auth_secret':AUTH,'client_salt':SALT,'invite':self.invite()}
        self.assertEqual(client.post('/train/api/auth/register',json={**body,'password':'not allowed'}).status_code,422)
        self.assertEqual(client.post('/train/api/auth/register',json=body,headers={'Origin':'https://other.test'}).status_code,403)
        self.assertEqual(client.post('/train/api/auth/register',json=body,headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)
        params=client.get('/train/api/auth/parameters',params={'name':'Synthetic Athlete'})
        self.assertEqual(params.status_code,200);self.assertIn('no-store',params.headers['cache-control'])
        self.assertEqual(len(params.json()['salt']),22)

    def test_old_profile_requires_exact_cookie_to_claim_then_old_cookie_is_revoked(self):
        original,old_cookie=self.accounts.join('Legacy Athlete')
        wrong=self.client()
        body={'name':'Legacy Athlete','auth_secret':AUTH,'client_salt':SALT}
        self.assertEqual(wrong.post('/train/api/auth/register',json={**body,'invite':self.invite()}).status_code,409)
        self.assertEqual(wrong.post('/train/api/auth/claim',json=body).status_code,409)
        client=self.client();client.cookies.set(COOKIE,old_cookie,domain='train.test',path='/train/api')
        self.assertEqual(client.get('/train/api/overview').status_code,403)
        response=client.post('/train/api/auth/claim',json=body)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['id'],original['id'])
        self.assertEqual(client.get('/train/api/me').status_code,200)
        with self.workouts.db() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM train_sessions WHERE hash=?',(hashlib.sha256(old_cookie.encode()).hexdigest(),)).fetchone())

    def test_disabled_mode_keeps_legacy_join_and_does_not_expose_partial_auth(self):
        client=self.client(self.make_app(False))
        self.assertEqual(client.post('/train/api/join',json={'name':'Legacy Athlete'}).status_code,200)
        self.assertEqual(client.get('/train/api/me').status_code,200)
        self.assertEqual(client.get('/train/api/auth/parameters',params={'name':'Legacy Athlete'}).status_code,404)
        self.assertEqual(client.post('/train/api/auth/register',json={'name':'New Athlete','auth_secret':AUTH,'client_salt':SALT}).status_code,404)
        self.assertEqual(client.get('/train/api/vault/records').status_code,404)

    def test_key_envelope_scope_and_password_parameter_binding(self):
        client,user=self.enroll();record=self.key(client,user)
        response=client.get('/train/api/vault/key-envelope')
        self.assertIn('no-store',response.headers['cache-control'])
        fetched=response.json()
        self.assertEqual(fetched['record'],record);self.assertEqual(fetched['revision'],1)
        self.assertTrue(fetched['migration_required'])
        for mutate in (
            lambda value:value.update(masterKey='forbidden'),
            lambda value:value.update(userId='other-user'),
            lambda value:value['password']['parameters'].update(salt=b64(b'x'*16)),
            lambda value:value['password']['wrappedMaster'].update(kind='wrong-wrapper'),
        ):
            value=deepcopy(record);mutate(value)
            self.assertEqual(client.put('/train/api/vault/key-envelope',json={'base_revision':1,'record':value}).status_code,422)

    def test_records_are_opaque_revision_bound_and_cross_user_inaccessible(self):
        first,one=self.enroll('Athlete One');record=self.key(first,one)
        second,two=self.enroll('Athlete Two');self.key(second,two)
        value=encrypted(one,record['keyId'],'photo','same-id')
        path='/train/api/vault/records/photo/same-id';body={'base_revision':0,'envelope':value}
        self.assertEqual(first.put(path,json=body).status_code,200)
        self.assertEqual(first.put(path,json=body).status_code,200)  # identical lost-response retry
        self.assertEqual(first.get(path).json()['envelope'],value)
        self.assertEqual(second.get(path).status_code,404)
        self.assertEqual(second.get('/train/api/vault/records').json()['items'],[])
        self.assertEqual(second.put(path,json=body).status_code,422)
        self.assertEqual(first.get('/v1/train/users/'+one+'/workout/vault/records/photo/same-id').status_code,404)
        with self.workouts.db() as db:
            row=db.execute('SELECT envelope FROM train_vault_objects WHERE user_id=?',(one,)).fetchone()
            self.assertIn(value['cipherB64'],row['envelope']);self.assertNotIn('masterKey',row['envelope'])
        stale=encrypted(one,record['keyId'],'photo','same-id')
        self.assertEqual(first.put(path,json={'base_revision':0,'envelope':stale}).status_code,409)

    def test_metadata_tampering_nonce_reuse_and_bad_ciphertext_are_rejected(self):
        client,user=self.enroll();record=self.key(client,user);key=record['keyId']
        good=encrypted(user,key,'photo','one')
        self.assertEqual(client.put('/train/api/vault/records/photo/one',json={'base_revision':0,'envelope':good}).status_code,200)
        for field,bad in (('revision',2),('nonceB64','short'),('cipherB64',b64(b'short')),('keyId',b64(b'z'*16)),('objectId','other')):
            value=encrypted(user,key,'photo','two');value[field]=bad
            self.assertEqual(client.put('/train/api/vault/records/photo/two',json={'base_revision':0,'envelope':value}).status_code,422)
        reused=encrypted(user,key,'photo','two',nonce=__import__('base64').urlsafe_b64decode(good['nonceB64']))
        self.assertEqual(client.put('/train/api/vault/records/photo/two',json={'base_revision':0,'envelope':reused}).status_code,409)
        with self.assertRaises(ValueError):ciphertext('A'*((MAX_CIPHER_BYTES*8+5)//6+1),MAX_CIPHER_BYTES)

    def test_scoped_pagination_has_no_ciphertext_and_bad_cursor_is_rejected(self):
        client,user=self.enroll();key=self.key(client,user)['keyId']
        for name in ('a','b','c'):
            value=encrypted(user,key,'workout',name)
            self.assertEqual(client.put('/train/api/vault/records/workout/'+name,json={'base_revision':0,'envelope':value}).status_code,200)
        first=client.get('/train/api/vault/records',params={'limit':2}).json()
        self.assertEqual([item['id'] for item in first['items']],['a','b']);self.assertNotIn('cipherB64',str(first))
        second=client.get('/train/api/vault/records',params={'cursor':first['next_cursor']}).json()
        self.assertEqual([item['id'] for item in second['items']],['c'])
        self.assertEqual(client.get('/train/api/vault/records',params={'cursor':'invalid'}).status_code,422)


if __name__=='__main__':unittest.main()
