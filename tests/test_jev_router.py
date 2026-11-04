"""Jev protocol and routing boundaries, using only a local fake HTTP transport."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from personal_assistant.orchestrator.jev import API_URL, MODEL, MAX_RESPONSE_BYTES, JevError, PROFILES, Router


def answer(profile='codex_luna_low', task_type='general', disposition='execute'):
    return {'model':'jev-1.14.0','answers':{
        name:{'type':'choice','choice':value,'confidence':.95}
        for name,value in {'profile':profile,'task_type':task_type,'disposition':disposition}.items()}}


class FakeHTTP:
    def __init__(self, result=None, error=None, after=None):
        self.raw = json.dumps(answer() if result is None else result).encode()
        self.error, self.after, self.calls = error, after, []

    def open(self, request, timeout):
        self.calls.append((request,timeout))
        if self.error:raise self.error
        if self.after:self.after()
        return io.BytesIO(self.raw)


class JevRouterTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'JEV_API_KEY':'private-test-key'},clear=True)
        self.env.start();self.addCleanup(self.env.stop)

    def decide(self, transport=None, config=None, **body):
        return Router(config or {},opener=transport or FakeHTTP()).decide({'user_request':'Reply exactly: Hi',**body})

    def test_verified_protocol_and_original_request_are_preserved(self):
        http=FakeHTTP();text='  Reply exactly: Hi\nDo not rewrite me.  '
        result=self.decide(http,user_request=text,requested_workspace='private/workspace',
            skill_catalog=[{'name':'email','description':'Find email','path':'private/skill'}],
            attachments=[{'name':'report.pdf','mime':'application/pdf','path':'private/attachment'}],
            agent_capacity={'codex':{'five_hour':{'remaining_percent':72}}})
        request,timeout=http.calls[0];body=json.loads(request.data)
        self.assertEqual((request.full_url,request.get_method(),timeout),(API_URL,'POST',10))
        self.assertEqual(request.get_header('Authorization'),'Bearer private-test-key')
        self.assertEqual(body['model'],MODEL)
        self.assertEqual(body['state']['user_request'],text)
        self.assertNotIn('private/',request.data.decode())
        self.assertEqual(body['state']['attachments'],[{'name':'report.pdf','mime':'application/pdf'}])
        self.assertEqual(set(body['questions']),{'disposition','profile','task_type'})
        self.assertTrue(all(q['type']=='choice' for q in body['questions'].values()))
        self.assertEqual(result,{'action':'dispatch','agent':'codex','model':'gpt-6-luna',
            'effort':'low','task_type':'general','profile':'codex_luna_low','confidence':.95,'routing_reason':'capacity_and_reset'})
        # Code chose the account, so Jev sees neither allowance figures nor the other account's profiles.
        self.assertEqual(body['state']['selected_account'],'codex')
        self.assertNotIn('agent_capacity',body['state'])
        self.assertTrue(all(name.startswith('codex_') for name in body['questions']['profile']['criteria']))

    def test_every_profile_round_trips_to_an_allowlisted_mapping(self):
        for name,profile in PROFILES.items():
            with self.subTest(profile=name):
                other='codex' if profile['agent']=='claude' else 'claude'
                selected=self.decide(FakeHTTP(answer(profile=name)),agent_availability={other:False})
                self.assertEqual({k:selected[k] for k in profile},profile)

    def test_key_file_takes_precedence_over_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            key=Path(directory)/'key';key.write_text('file-key\n',encoding='utf-8-sig')
            http=FakeHTTP();self.decide(http,{'jev_api_key_file':str(key)})
            self.assertEqual(http.calls[0][0].get_header('Authorization'),'Bearer file-key')

    def test_typesafe_environment_alias_and_missing_key(self):
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'alias-key'},clear=True):
            http=FakeHTTP();self.decide(http)
            self.assertEqual(http.calls[0][0].get_header('Authorization'),'Bearer alias-key')
        with patch.dict(os.environ,{},clear=True):
            http=FakeHTTP()
            with self.assertRaises(JevError):self.decide(http)
            self.assertEqual(http.calls,[])

    def test_bad_key_file_and_key_format_do_not_leak(self):
        for config in ({'jev_api_key_file':'relative-key'}, {'jev_api_key_file':str(Path(tempfile.gettempdir())/'missing-jev-key')}):
            http=FakeHTTP()
            with self.assertRaises(JevError) as caught:self.decide(http,config)
            self.assertEqual(http.calls,[])
            self.assertNotIn(str(config['jev_api_key_file']),str(caught.exception))
        with patch.dict(os.environ,{'JEV_API_KEY':'private\nkey'},clear=True):
            with self.assertRaises(JevError) as caught:self.decide()
            self.assertNotIn('private',str(caught.exception))

    def test_forwarding_is_only_allowed_when_configured(self):
        with self.assertRaisesRegex(JevError,'unavailable development forwarding'):
            self.decide(FakeHTTP(answer(disposition='forward')))
        result=self.decide(FakeHTTP(answer(disposition='forward')),dev_forwarding={'available':True})
        self.assertEqual(result['action'],'forward')

    def test_email_cannot_use_claude_tools(self):
        with self.assertRaisesRegex(JevError,'email tools'):
            self.decide(FakeHTTP(answer(profile='claude_sonnet_medium',task_type='email')),agent_availability={'codex':False})
        # A mail request is pinned to Codex before Jev is asked, whatever the allowance.
        http=FakeHTTP(answer(task_type='email'))
        result=self.decide(http,user_request='Find the invoice email from the landlord',
            agent_capacity={'codex':{'five_hour':{'remaining_percent':5}},'claude':{'five_hour':{'remaining_percent':95}}})
        self.assertEqual((result['agent'],result['routing_reason']),('codex','mail_tools'))
        with self.assertRaisesRegex(JevError,'Codex mailbox tools'):
            self.decide(FakeHTTP(),user_request='Use Claude to search my inbox for the invoice')
        self.assertEqual(self.decide(FakeHTTP(answer(task_type='email')))['task_type'],'email')

    def test_invalid_response_shapes_are_safe_errors(self):
        malformed=[[],{'answers':[]},{'answers':{'profile':{}}}]
        for value in malformed:
            with self.subTest(value=value),self.assertRaises(JevError):self.decide(FakeHTTP(value))
        for value in ('invented',{},None):
            result=answer();result['answers']['profile']['choice']=value
            with self.subTest(choice=value),self.assertRaises(JevError):self.decide(FakeHTTP(result))

    def test_invalid_confidence_is_rejected(self):
        for value in (None,True,-.1,1.1,float('nan'),float('inf')):
            result=answer();result['answers']['profile']['confidence']=value
            with self.subTest(confidence=value),self.assertRaises(JevError):self.decide(FakeHTTP(result))

    def test_provider_failures_are_not_retried_or_disclosed(self):
        for error in (HTTPError(API_URL,402,'private error',{},io.BytesIO(b'private body')),
                      URLError('private transport error')):
            http=FakeHTTP(error=error)
            with self.assertRaises(JevError) as caught:self.decide(http)
            self.assertEqual(len(http.calls),1)
            self.assertNotIn('private',str(caught.exception))
            self.assertIsInstance(caught.exception,ValueError)

    def test_cancellation_before_and_after_request(self):
        cancel=threading.Event();cancel.set();http=FakeHTTP()
        with self.assertRaisesRegex(JevError,'cancelled'):Router({},opener=http).decide({'user_request':'Hi'},cancel)
        self.assertEqual(http.calls,[])
        cancel.clear();http=FakeHTTP(after=cancel.set)
        with self.assertRaisesRegex(JevError,'cancelled'):Router({},opener=http).decide({'user_request':'Hi'},cancel)
        self.assertEqual(len(http.calls),1)

    def test_response_and_input_are_bounded(self):
        http=FakeHTTP();http.raw=b'x'*(MAX_RESPONSE_BYTES+100)
        with self.assertRaisesRegex(JevError,'too large'):self.decide(http)
        http=FakeHTTP()
        with self.assertRaisesRegex(JevError,'too large'):self.decide(http,user_request='x'*150000)
        self.assertEqual(http.calls,[])

    def test_endpoint_and_timeout_validation_precedes_request(self):
        for config in ({'jev_api_url':'http://example.org'}, {'jev_api_url':'https://key@example.org'},
                       {'jev_api_url':'https://example.org/?key=value'}, {'jev_timeout_seconds':float('nan')},
                       {'jev_timeout_seconds':60}):
            http=FakeHTTP()
            with self.subTest(config=config),self.assertRaises(JevError):self.decide(http,config)
            self.assertEqual(http.calls,[])

    def test_bad_json_is_not_leaked(self):
        http=FakeHTTP();http.raw=b'private malformed JSON'
        with self.assertRaisesRegex(JevError,'invalid JSON') as caught:self.decide(http)
        self.assertNotIn('private',str(caught.exception))


if __name__=='__main__':unittest.main()
