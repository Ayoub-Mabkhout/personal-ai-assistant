"""Passkey sign-in and forgotten-password reset, with synthetic PRF-derived secrets and envelopes."""
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
from personal_assistant.workout.identity import b64,NAME_ATTEMPTS,MAX_PASSKEYS
from personal_assistant.workout.store import Workouts
from personal_assistant.workout.web import Accounts,mount_train

from test_workout_private_vault import encrypted,wrapped


AUTH=b64(b'a'*32);SALT=b64(b'c'*16)
NEW_AUTH=b64(b'n'*32);NEW_SALT=b64(b'm'*16)
PASSKEY_SECRET=b64(b'p'*32);WRONG=b64(b'w'*32)
CREDENTIAL=b64(b'credential-one-16bytes')


class PasskeyCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.workouts=Workouts(self.root/'workouts.sqlite3')
        self.accounts=Accounts(self.workouts)
        app=FastAPI()
        for error,status in ((Conflict,409),(Missing,404),(ValueError,422)):
            async def handle(request,exc,code=status):return JSONResponse({'detail':str(exc)},status_code=code)
            app.add_exception_handler(error,handle)
        mount_train(app,self.workouts,lambda:None,self.root/'no-assets',require_identity=True)
        self.app=app

    def client(self):
        client=TestClient(self.app,base_url='https://train.test');self.addCleanup(client.close)
        return client

    def enroll(self,name='Synthetic Athlete'):
        client=self.client();invite=self.accounts.invite(None)['invite']
        response=client.post('/train/api/auth/register',json={'name':name,'auth_secret':AUTH,'client_salt':SALT,'invite':invite})
        self.assertEqual(response.status_code,200,response.text)
        return client,response.json()['id']

    def add(self,client,credential=CREDENTIAL,secret=PASSKEY_SECRET,**proof):
        proof=proof or {'password_auth_secret':AUTH}
        return client.post('/train/api/auth/passkeys',json={'credential_id':credential,'auth_secret':secret,**proof})



class WorkoutPasskeyTests(PasskeyCase):
    def test_add_list_and_remove_a_passkey(self):
        client,_=self.enroll()
        self.assertEqual(client.get('/train/api/auth/passkeys').json(),{'items':[]})
        added=self.add(client)
        self.assertEqual(added.status_code,200,added.text);self.assertIn('no-store',added.headers['cache-control'])
        items=client.get('/train/api/auth/passkeys').json()['items']
        self.assertEqual([item['credential_id'] for item in items],[CREDENTIAL]);self.assertIsNone(items[0]['last_used'])
        self.assertEqual(set(items[0]),{'credential_id','created','last_used'})
        with self.workouts.db() as db:
            stored=dict(db.execute('SELECT * FROM train_passkeys').fetchone())
        self.assertNotIn(PASSKEY_SECRET,str(stored));self.assertTrue(stored['verifier'].startswith('scrypt$'))
        # The same credential can't be registered twice, by this profile or another.
        self.assertEqual(self.add(client).status_code,409)
        other,_=self.enroll('Other Athlete')
        self.assertEqual(self.add(other).status_code,409)
        self.assertEqual(other.delete('/train/api/auth/passkeys/'+CREDENTIAL).status_code,404)
        self.assertEqual(client.delete('/train/api/auth/passkeys/'+CREDENTIAL).json(),{'items':[]})
        self.assertEqual(client.delete('/train/api/auth/passkeys/'+CREDENTIAL).status_code,404)
        self.assertEqual(self.client().get('/train/api/auth/passkeys').status_code,401)

    def test_adding_a_passkey_needs_proof_beyond_the_session(self):
        client,_=self.enroll()
        # A stolen session cookie alone can't add a passkey (and then reset the password with it).
        bare=client.post('/train/api/auth/passkeys',json={'credential_id':CREDENTIAL,'auth_secret':PASSKEY_SECRET})
        self.assertEqual(bare.status_code,401)
        self.assertEqual(self.add(client,password_auth_secret=WRONG).status_code,401)
        self.assertEqual(self.add(client,proof_credential_id=CREDENTIAL).status_code,401)  # incomplete passkey proof
        self.assertEqual(client.get('/train/api/auth/passkeys').json()['items'],[])
        # The current password proves it.
        self.assertEqual(self.add(client,password_auth_secret=AUTH).status_code,200)
        # So does an existing passkey of the same profile, but not a wrong secret or another profile's passkey.
        second=b64(b'credential-two-16bytes')
        self.assertEqual(self.add(client,second,proof_credential_id=CREDENTIAL,proof_auth_secret=WRONG).status_code,401)
        other,_=self.enroll('Other Athlete')
        foreign=b64(b'credential-foreign-xxx')
        self.assertEqual(self.add(other,foreign,proof_credential_id=CREDENTIAL,proof_auth_secret=PASSKEY_SECRET).status_code,401)
        added=self.add(client,second,proof_credential_id=CREDENTIAL,proof_auth_secret=PASSKEY_SECRET)
        self.assertEqual(added.status_code,200,added.text)
        self.assertEqual(len(added.json()['items']),2)

    def test_password_proof_for_adding_a_passkey_is_rate_limited(self):
        client,_=self.enroll()
        for index in range(NAME_ATTEMPTS):
            self.assertEqual(self.add(client,b64(b'credential-%02d-xxxxx'%index),password_auth_secret=WRONG).status_code,401)
        limited=self.add(client,password_auth_secret=AUTH)
        self.assertEqual(limited.status_code,429);self.assertIn('retry-after',limited.headers)
        # It shares the name bucket with password sign-in.
        self.assertEqual(self.client().post('/train/api/auth/login',json={'name':'Synthetic Athlete','auth_secret':AUTH}).status_code,429)

    def test_passkey_material_is_validated_and_limited(self):
        client,_=self.enroll()
        for credential,secret in (('short',PASSKEY_SECRET),('x'*1025,PASSKEY_SECRET),(CREDENTIAL+'=',PASSKEY_SECRET),
                                  (CREDENTIAL,'raw password'),(CREDENTIAL[:-1]+'B',PASSKEY_SECRET)):
            with self.subTest(credential=credential[:20]):
                self.assertEqual(self.add(client,credential,secret).status_code,422)
        for index in range(MAX_PASSKEYS):
            self.assertEqual(self.add(client,b64(b'credential-%02d-xxxxx'%index)).status_code,200)
        self.assertEqual(self.add(client,b64(b'credential-over-xxxx')).status_code,422)
        self.assertEqual(client.post('/train/api/auth/passkeys',json={'credential_id':CREDENTIAL,'auth_secret':PASSKEY_SECRET},
                                     headers={'Origin':'https://other.test'}).status_code,403)

    def test_sign_in_with_a_passkey(self):
        owner,user=self.enroll();self.add(owner)
        client=self.client()
        response=client.post('/train/api/auth/passkey/login',json={'credential_id':CREDENTIAL,'auth_secret':PASSKEY_SECRET})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['id'],user)
        for flag in ('HttpOnly','Secure','SameSite=strict'):self.assertIn(flag,response.headers['set-cookie'])
        self.assertIn('no-store',response.headers['cache-control'])
        self.assertEqual(client.get('/train/api/me').json()['id'],user)
        self.assertIsNotNone(owner.get('/train/api/auth/passkeys').json()['items'][0]['last_used'])

    def test_wrong_or_unknown_passkeys_fail_alike_and_are_rate_limited(self):
        owner,_=self.enroll();self.add(owner)
        client=self.client();path='/train/api/auth/passkey/login'
        unknown=client.post(path,json={'credential_id':b64(b'unknown-credential-x'),'auth_secret':PASSKEY_SECRET})
        wrong=client.post(path,json={'credential_id':CREDENTIAL,'auth_secret':WRONG})
        self.assertEqual((unknown.status_code,wrong.status_code),(401,401));self.assertEqual(unknown.json(),wrong.json())
        self.assertNotIn('set-cookie',wrong.headers)
        for _ in range(NAME_ATTEMPTS-1):self.assertEqual(client.post(path,json={'credential_id':CREDENTIAL,'auth_secret':WRONG}).status_code,401)
        limited=client.post(path,json={'credential_id':CREDENTIAL,'auth_secret':PASSKEY_SECRET})
        self.assertEqual(limited.status_code,429);self.assertIn('retry-after',limited.headers)
        # The reset route shares the same per-passkey limit.
        reset=client.post('/train/api/auth/passkey/reset-password',json={'credential_id':CREDENTIAL,'passkey_auth_secret':PASSKEY_SECRET,
                                                                         'auth_secret':NEW_AUTH,'client_salt':NEW_SALT})
        self.assertEqual(reset.status_code,429)

    def test_reset_a_forgotten_password_with_a_passkey(self):
        owner,user=self.enroll();self.add(owner);record=wrapped(user)
        self.assertEqual(owner.put('/train/api/vault/key-envelope',json={'base_revision':0,'record':record}).status_code,200)
        other_session=self.client()
        self.assertEqual(other_session.post('/train/api/auth/login',json={'name':'Synthetic Athlete','auth_secret':AUTH}).status_code,200)
        body={'credential_id':CREDENTIAL,'passkey_auth_secret':WRONG,'auth_secret':NEW_AUTH,'client_salt':NEW_SALT}
        client=self.client();path='/train/api/auth/passkey/reset-password'
        self.assertEqual(client.post(path,json=body).status_code,401)
        self.assertEqual(client.post(path,json={**body,'passkey_auth_secret':PASSKEY_SECRET,'client_salt':'bad'}).status_code,422)
        response=client.post(path,json={**body,'passkey_auth_secret':PASSKEY_SECRET})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['id'],user)
        self.assertEqual(client.get('/train/api/me').status_code,200)
        # Every other session is signed out, the old password no longer works and the new one does.
        self.assertEqual(owner.get('/train/api/me').status_code,401);self.assertEqual(other_session.get('/train/api/me').status_code,401)
        fresh=self.client()
        self.assertEqual(fresh.post('/train/api/auth/login',json={'name':'Synthetic Athlete','auth_secret':AUTH}).status_code,401)
        self.assertEqual(fresh.post('/train/api/auth/login',json={'name':'Synthetic Athlete','auth_secret':NEW_AUTH}).status_code,200)
        self.assertEqual(fresh.get('/train/api/auth/parameters',params={'name':'Synthetic Athlete'}).json()['salt'],NEW_SALT)
        # The passkey keeps working, and the vault record must now be re-wrapped for the new password parameters.
        self.assertEqual(self.client().post('/train/api/auth/passkey/login',json={'credential_id':CREDENTIAL,'auth_secret':PASSKEY_SECRET}).status_code,200)
        stale=client.get('/train/api/vault/key-envelope').json()
        self.assertEqual(stale['record'],record)
        rewrapped=deepcopy(record);rewrapped['password']['parameters']['salt']=NEW_SALT
        rewrapped['password']['wrappedMaster']=encrypted(user,record['keyId'],'vault-password-key',record['keyId'],2)
        self.assertEqual(client.put('/train/api/vault/key-envelope',json={'base_revision':1,'record':record}).status_code,422)
        self.assertEqual(client.put('/train/api/vault/key-envelope',json={'base_revision':1,'record':rewrapped}).status_code,200)

    def test_passkey_sign_in_rejects_a_removed_passkey(self):
        owner,_=self.enroll();self.add(owner)
        owner.delete('/train/api/auth/passkeys/'+CREDENTIAL)
        response=self.client().post('/train/api/auth/passkey/login',json={'credential_id':CREDENTIAL,'auth_secret':PASSKEY_SECRET})
        self.assertEqual(response.status_code,401)

    def test_registration_and_invite_rules_are_unchanged(self):
        client=self.client()
        self.assertEqual(client.post('/train/api/auth/register',json={'name':'No Invite','auth_secret':AUTH,'client_salt':SALT}).status_code,422)
        self.assertEqual(client.post('/train/api/join',json={'name':'Link Only'}).status_code,403)
        # A passkey can't be added without a signed-in, password-enrolled profile.
        self.assertEqual(self.add(client).status_code,401)
        _,legacy=self.accounts.join('Legacy Athlete')
        legacy_client=self.client();legacy_client.cookies.set('train_session',legacy,domain='train.test',path='/train/api')
        self.assertEqual(self.add(legacy_client).status_code,403)

    def test_disabled_mode_has_no_passkey_routes(self):
        app=FastAPI();mount_train(app,self.workouts,lambda:None,self.root/'no-assets',require_identity=False)
        client=TestClient(app,base_url='https://train.test');self.addCleanup(client.close)
        self.assertEqual(client.post('/train/api/auth/passkey/login',json={'credential_id':CREDENTIAL,'auth_secret':PASSKEY_SECRET}).status_code,404)


class PasskeyKeyEnvelopeTests(PasskeyCase):
    """The vault record may carry passkey wrappers; adding one is a valid update without re-wrapping the password."""

    def passkey(self,user,key,credential=CREDENTIAL):
        return {'credentialId':credential,'wrappedMaster':encrypted(user,key,'vault-passkey-key',key)}

    def put(self,client,record,base):
        return client.put('/train/api/vault/key-envelope',json={'base_revision':base,'record':record})

    def test_key_envelope_accepts_passkey_changes_without_rewrapping_the_password(self):
        client,user=self.enroll();record=wrapped(user)
        self.assertEqual(self.put(client,record,0).status_code,200)
        added=deepcopy(record);added['passkeys']=[self.passkey(user,record['keyId'])]
        response=self.put(client,added,1)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['revision'],2)
        self.assertEqual(self.put(client,added,1).status_code,200)  # identical lost-response retry
        self.assertEqual(client.get('/train/api/vault/key-envelope').json()['record'],added)
        # Nothing changed, or the recovery wrapper changed without a password re-wrap: refused.
        self.assertEqual(self.put(client,deepcopy(added),2).status_code,422)
        sneaky=deepcopy(added);sneaky['passkeys']=[];sneaky['recovery']['salt']=b64(secrets.token_bytes(16))
        self.assertEqual(self.put(client,sneaky,2).status_code,422)
        removed=deepcopy(added);removed['passkeys']=[]
        self.assertEqual(self.put(client,removed,2).status_code,200)
        # A later password change follows the previous password wrapper's revision, not the record revision.
        changed=deepcopy(removed);changed['password']['wrappedMaster']=encrypted(user,record['keyId'],'vault-password-key',record['keyId'],4)
        self.assertEqual(self.put(client,changed,3).status_code,422)
        changed['password']['wrappedMaster']=encrypted(user,record['keyId'],'vault-password-key',record['keyId'],2)
        self.assertEqual(self.put(client,changed,3).status_code,200)
        stale=deepcopy(changed);stale['passkeys']=[self.passkey(user,record['keyId'])]
        self.assertEqual(self.put(client,stale,3).status_code,409)

    def test_key_envelope_rejects_malformed_passkey_wrappers(self):
        client,user=self.enroll();record=wrapped(user);key=record['keyId']
        self.assertEqual(self.put(client,record,0).status_code,200)
        good=self.passkey(user,key)
        cases={
            'not a list':{'credentialId':CREDENTIAL},
            'too many':[self.passkey(user,key,b64(b'credential-%02d-xxxxx'%i)) for i in range(MAX_PASSKEYS+1)],
            'duplicate':[good,self.passkey(user,key)],
            'extra field':[{**good,'label':'x'}],
            'bad id':[{**good,'credentialId':'short'}],
            'wrong kind':[{**good,'wrappedMaster':encrypted(user,key,'vault-password-key',key)}],
            'wrong object':[{**good,'wrappedMaster':encrypted(user,key,'vault-passkey-key',CREDENTIAL)}],
            'other user':[{**good,'wrappedMaster':encrypted('other-user',key,'vault-passkey-key',key)}],
            'long cipher':[{**good,'wrappedMaster':encrypted(user,key,'vault-passkey-key',key,size=64)}],
            'short cipher':[{**good,'wrappedMaster':encrypted(user,key,'vault-passkey-key',key,size=32)}],
            'revision':[{**good,'wrappedMaster':encrypted(user,key,'vault-passkey-key',key,2)}],
            'raw key':[{**good,'masterKey':b64(b'k'*32)}],
        }
        for label,passkeys in cases.items():
            with self.subTest(label):
                value=deepcopy(record);value['passkeys']=passkeys
                self.assertEqual(self.put(client,value,1).status_code,422)
        self.assertEqual(client.get('/train/api/vault/key-envelope').json()['revision'],1)


if __name__=='__main__':unittest.main()
