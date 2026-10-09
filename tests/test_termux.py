import tempfile
import unittest
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from personal_assistant.groceries.mobile import Devices
from personal_assistant.relay.termux import Command, Result, TermuxCommands, termux_router
from personal_assistant.relay.api import BodyLimit


class TermuxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=1000;self.devices=Devices(Path(self.tmp.name)/'phones.sqlite3',clock=lambda:self.now)
        self.one=self.devices.exchange(self.devices.pairing()['code'],'one')
        self.two=self.devices.exchange(self.devices.pairing()['code'],'two')
        self.store=TermuxCommands(self.devices)

    def command(self): return Command(id='command-test-01',phone=self.one['id'],script='printf hello')

    def test_idempotent_submission_and_claim_survive_restart(self):
        cmd=self.command();self.assertTrue(self.store.enqueue(cmd)[1]);self.assertFalse(TermuxCommands(self.devices).enqueue(cmd)[1])
        with self.assertRaises(ValueError):self.store.enqueue(cmd.model_copy(update={'script':'different'}))
        a=self.store.claim(self.one['id'],cmd.id,'claim-12345');self.assertEqual(a['state'],'running')
        self.assertEqual(self.store.claim(self.one['id'],cmd.id,'claim-12345')['claim'],'claim-12345')
        with self.assertRaises(HTTPException):self.store.claim(self.one['id'],cmd.id,'another-claim')

    def test_expiry_is_not_reexecuted_and_late_callback_resolves_uncertainty(self):
        cmd=self.command();self.store.enqueue(cmd);self.now+=4000
        self.assertEqual(self.store.pending(self.one['id']),[])
        with self.assertRaises(HTTPException):self.store.claim(self.one['id'],cmd.id,'claim-12345')
        cmd=cmd.model_copy(update={'id':'command-test-02'});self.store.enqueue(cmd);self.store.claim(self.one['id'],cmd.id,'claim-12345')
        self.store.receipt(self.one['id'],cmd.id,Result(claim='claim-12345',state='uncertain'))
        result=Result(claim='claim-12345',state='completed',stdout='hello',exit_code=0)
        self.store.receipt(self.one['id'],cmd.id,result);self.store.receipt(self.one['id'],cmd.id,result)
        self.assertEqual(self.store.status(cmd.id)['result']['stdout'],'hello')

    def test_phone_scope_and_owner_auth(self):
        def owner(authorization:str=Header(default='')):
            if authorization!='Bearer owner':raise HTTPException(401)
        def device(authorization:str=Header(default='')):
            try:return self.devices.authenticate(authorization.removeprefix('Bearer '))
            except ValueError:raise HTTPException(401) from None
        app=FastAPI();app.include_router(termux_router(self.devices,device,owner));client=TestClient(app)
        cmd=self.command().model_dump()
        self.assertEqual(client.post('/termux/commands',json=cmd).status_code,401)
        self.assertEqual(client.post('/termux/commands',json=cmd,headers={'Authorization':'Bearer owner'}).status_code,200)
        headers={'Authorization':'Bearer '+self.two['token']}
        self.assertEqual(client.get('/termux/pending',headers=headers).json(),[])
        self.assertEqual(client.post('/termux/commands/'+cmd['id']+'/claim',json={'claim':'claim-12345'},headers=headers).status_code,404)
        self.assertEqual(client.get('/termux/commands/'+cmd['id'],headers=headers).status_code,401)

    def test_bounded_large_results_pass_through_relay_body_limit(self):
        self.store.enqueue(self.command());self.store.claim(self.one['id'],'command-test-01','claim-12345')
        app=FastAPI();app.add_middleware(BodyLimit)
        app.include_router(termux_router(self.devices,lambda:self.one['id'],lambda:None),prefix='/groceries/v1/mobile')
        client=TestClient(app)
        result={'claim':'claim-12345','state':'completed','stdout':'text '*6000,'stderr':'','exit_code':0}
        r=client.post('/groceries/v1/mobile/termux/commands/command-test-01/result',json=result)
        self.assertEqual(r.status_code,200)
        self.assertEqual(len(self.store.status('command-test-01')['result']['stdout']),30000)
