import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from personal_assistant.groceries.mobile import Devices,mobile_router
from personal_assistant.groceries.store import Groceries
from personal_assistant.groceries.releases import ReleaseFeed,CompanionReleasePump
from fastapi import Header,HTTPException


class ReleaseTests(unittest.TestCase):
    def test_diagnostic_classifier_artifact_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);apk,release=self.artifact(root)
            release['diagnostic_only']=True
            apk.with_suffix('.release.json').write_text(json.dumps(release))
            feed=ReleaseFeed(apk)
            with self.assertRaises(ValueError):feed.manifest()
            with self.assertRaises(ValueError):feed.publish(release['version_code'],release['sha256'])
    def artifact(self,root,version=3):
        apk=root/'companion.apk';apk.write_bytes(('test-apk-'+str(version)).encode())
        release={'package_name':'com.personalassistant.companion','version_code':version,'version_name':'0.3.0','min_sdk':26,
            'size':apk.stat().st_size,'sha256':hashlib.sha256(apk.read_bytes()).hexdigest()}
        apk.with_suffix('.release.json').write_text(json.dumps(release))
        return apk,release

    def test_release_hook_owner_auth_matching_artifact_and_idempotency(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);apk,release=self.artifact(root)
            def owner(authorization:str|None=Header(default=None)):
                if authorization!='Bearer owner':raise HTTPException(401)
            app=FastAPI();app.include_router(mobile_router(Devices(root/'phones.sqlite3'),owner,
                Groceries(root/'groceries.sqlite3'),lambda body:None,sender=lambda body:None,apk=apk))
            client=TestClient(app);body={key:release[key] for key in ('version_code','sha256')}
            self.assertEqual(client.post('/v1/mobile/release/published',json=body).status_code,401)
            headers={'Authorization':'Bearer owner'}
            self.assertEqual(client.post('/v1/mobile/release/published',json={**body,'sha256':'0'*64},headers=headers).status_code,409)
            first=client.post('/v1/mobile/release/published',json=body,headers=headers).json()
            self.assertTrue(first['created']);self.assertEqual(first['state'],'pending')
            second=client.post('/v1/mobile/release/published',json=body,headers=headers).json()
            self.assertFalse(second['created']);self.assertFalse(second['handset_delivery_verified'])

    def test_push_retry_survives_restart_and_does_not_repeat_accepted_release(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);apk,release=self.artifact(root)
            now=[100.0];feed=ReleaseFeed(apk,clock=lambda:now[0])
            feed.publish(release['version_code'],release['sha256'])
            calls=[]
            def fail(payload):calls.append(payload);raise OSError('offline')
            CompanionReleasePump(feed,fail).tick()
            self.assertEqual(feed.status(3)['state'],'pending')
            now[0]+=11
            feed=ReleaseFeed(apk,clock=lambda:now[0])
            pump=CompanionReleasePump(feed,calls.append);pump.tick();pump.tick()
            self.assertEqual(feed.status(3)['state'],'accepted');self.assertEqual(len(calls),2)
            self.assertEqual(calls[-1]['message'],'command_broadcast_intent')
            self.assertEqual(calls[-1]['data']['intent_action'],'com.personalassistant.companion.RELEASE_PUBLISHED')
            self.assertNotIn('intent_extras',calls[-1]['data'])
            self.assertFalse(feed.publish(3,release['sha256'])['created']);pump.tick();self.assertEqual(len(calls),2)

    def test_same_version_cannot_change_and_new_publication_supersedes_old(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);apk,release=self.artifact(root)
            feed=ReleaseFeed(apk);feed.publish(3,release['sha256'])
            apk.write_bytes(b'changed artifact');release.update(size=apk.stat().st_size,sha256=hashlib.sha256(apk.read_bytes()).hexdigest())
            apk.with_suffix('.release.json').write_text(json.dumps(release))
            with self.assertRaises(ValueError):feed.publish(3,release['sha256'])
            apk,new=self.artifact(root,4);feed.publish(4,new['sha256'])
            self.assertEqual(feed.status(3)['state'],'superseded')
            self.assertEqual(feed.claim()[0],4)

    def test_release_manifest_checks_public_artifact_and_detects_partial_publication(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);apk=root/'companion.apk';metadata=apk.with_suffix('.release.json')
            app=FastAPI();app.include_router(mobile_router(Devices(root/'phones.sqlite3'),lambda:None,
                Groceries(root/'groceries.sqlite3'),lambda body:None,apk=apk))
            client=TestClient(app)
            self.assertEqual(client.get('/v1/mobile/release').status_code,404)
            apk.write_bytes(b'test apk bytes')
            release={'package_name':'com.personalassistant.companion','version_code':2,'version_name':'0.2.0','min_sdk':26,
                'size':apk.stat().st_size,'sha256':hashlib.sha256(apk.read_bytes()).hexdigest()}
            metadata.write_text(json.dumps(release))
            self.assertEqual(client.get('/v1/mobile/release').json(),release)
            self.assertEqual(client.get('/v1/mobile/companion.apk').content,apk.read_bytes())
            apk.write_bytes(b'changed artifact')
            self.assertEqual(client.get('/v1/mobile/release').status_code,503)
            release.update(size=apk.stat().st_size,sha256=hashlib.sha256(apk.read_bytes()).hexdigest(),package_name='another.package')
            metadata.write_text(json.dumps(release))
            self.assertEqual(client.get('/v1/mobile/release').status_code,503)
