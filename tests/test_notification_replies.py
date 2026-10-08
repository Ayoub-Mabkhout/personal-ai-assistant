from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from personal_assistant.relay.notifications import notification
from personal_assistant.relay.replies import NotificationReply, ReplyInbox, reply_action, reply_router
from personal_assistant.relay.store import Conflict, Queue
from personal_assistant.relay.task_links import TaskLinks


class NotificationReplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.now = 1900000000
        self.agents = Queue(self.root/'agents.sqlite3', clock=lambda:self.now, serial=True, notifications=True)
        self.commands = Queue(self.root/'commands.sqlite3', clock=lambda:self.now)
        self.queues = {'agent':self.agents, 'command':self.commands}
        self.inbox = ReplyInbox(self.queues)
        self.agents.submit({'id':'parent-task-123', 'command':'Find my invoice', 'timezone':'Europe/Berlin',
                            'workspace':'C:/example'})
        self.agents.heartbeat('ready')
        parent = self.agents.claim()
        self.agents.finish(parent['id'], parent['lease_token'], 'needs_input', {'summary':'Which supplier?'})
        self.event = {'event_id':'event-context-123', 'action':reply_action('agent','parent-task-123'),
                      'tag':'assistant-agent-parent-task-123', 'reply_text':'The electricity supplier',
                      'time_fired':datetime.fromtimestamp(self.now,timezone.utc).isoformat()}

    def tearDown(self):
        self.temp.cleanup()

    def accept(self, **changes):
        return self.inbox.accept(NotificationReply(**{**self.event, **changes}))

    def test_needs_input_followup_uses_same_queue_without_reopening_parent(self):
        before = self.agents.get('parent-task-123')
        job, created = self.accept()
        self.assertTrue(created)
        self.assertEqual(job['state'], 'queued')
        self.assertEqual(job['source'], 'notification_reply')
        context = job['payload']['reply_context']
        self.assertEqual(context['parent_state'], 'needs_input')
        self.assertEqual(context['parent_summary'], 'Which supplier?')
        self.assertEqual(context['original_request'], 'Find my invoice')
        self.assertEqual(job['payload']['command'], self.event['reply_text'])
        self.assertEqual(job['payload']['workspace'], 'C:/example')
        self.assertEqual(self.agents.get('parent-task-123'), before)
        self.assertEqual(self.agents.claim()['id'], job['id'])

    def test_http_crash_replay_and_restart_preserve_exact_envelope(self):
        original = self.agents.submit
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('Lost response after successful queue write')
        self.agents.submit = interrupted
        with self.assertRaises(OSError):
            self.accept()
        self.agents.submit = original
        # Change the parent to demonstrate that retry uses the saved context.
        with self.agents.connection(True) as db:
            db.execute("UPDATE jobs SET result=? WHERE id='parent-task-123'", ('{"summary":"Changed later"}',))
        restored = ReplyInbox(self.queues)
        job, created = restored.accept(NotificationReply(**self.event))
        self.assertFalse(created)
        self.assertEqual(job['payload']['reply_context']['parent_summary'], 'Which supplier?')
        with self.agents.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE source='notification_reply'").fetchone()[0],1)
        with self.assertRaises(Conflict):
            self.accept(reply_text='A different instruction')

    def test_followup_chain_retains_root_and_command_queue_enters_agent_queue(self):
        self.commands.submit({'id':'calendar-query-123','command':'Agenda tomorrow','timezone':'Europe/Berlin'})
        first,_ = self.accept(action=reply_action('command','calendar-query-123'), tag='assistant-command-calendar-query-123')
        second,_ = self.accept(event_id='event-context-456',action=reply_action('agent',first['id']),
                              tag='assistant-agent-'+first['id'], reply_text='And the next day?')
        context = second['payload']['reply_context']
        self.assertEqual(context['original_request'],'Agenda tomorrow')
        self.assertEqual(context['ancestry'],[{'kind':'command','id':'calendar-query-123'},{'kind':'agent','id':first['id']}])
        self.assertEqual(self.commands.get('calendar-query-123')['state'],'queued')

    def test_startup_recovers_receipt_saved_before_queue_transaction(self):
        original = self.agents.submit
        def interrupted(*args, **kwargs):
            raise OSError('Interrupted before queue transaction')
        self.agents.submit = interrupted
        with self.assertRaises(OSError):
            self.accept()
        self.agents.submit = original
        self.assertEqual(self.agents.status()['queued'],0)
        ReplyInbox(self.queues)
        self.assertEqual(self.agents.status()['queued'],1)
        job,created = self.accept()
        self.assertFalse(created)
        self.assertEqual(job['state'],'queued')

    def test_all_parent_states_remain_unchanged_and_new_event_is_new_instruction(self):
        for state in ('queued','running','completed','failed','needs_input','cancelled','expired'):
            with self.subTest(state=state):
                identifier = 'parent-state-' + state
                self.agents.submit({'id':identifier,'command':'Original task','timezone':'Europe/Berlin'})
                with self.agents.connection(True) as db:
                    db.execute('UPDATE jobs SET state=? WHERE id=?',(state,identifier))
                before = self.agents.get(identifier)
                job,created = self.accept(event_id='event-state-'+state, action=reply_action('agent',identifier),
                                          tag='assistant-agent-'+identifier)
                self.assertTrue(created)
                self.assertEqual(job['payload']['reply_context']['parent_state'],state)
                self.assertEqual(self.agents.get(identifier),before)
        first,_ = self.accept()
        second,created = self.accept(event_id='event-same-text-new')
        self.assertTrue(created)
        self.assertNotEqual(first['id'],second['id'])

    def test_card_identity_blank_text_and_future_events_are_rejected(self):
        for changes in ({'tag':'assistant-agent-other-task-123'}, {'action':'REPLY'},
                        {'time_fired':datetime.fromtimestamp(self.now+301,timezone.utc).isoformat()},
                        {'reply_text':'   '}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.accept(**changes)
        self.assertEqual(self.agents.status()['queued'],0)

    def test_remote_ingress_requires_service_auth_and_not_read_only_view_token(self):
        def authorize(authorization:str|None=Header(default=None)):
            if authorization!='Bearer service-test-token':
                raise HTTPException(401)
        app = FastAPI()
        app.include_router(reply_router(self.queues, authorize))
        client = TestClient(app)
        token = TaskLinks(b'x'*32).token('agent','parent-task-123')
        self.assertEqual(client.post('/v1/notification-replies',json=self.event).status_code,401)
        self.assertEqual(client.post('/v1/notification-replies',json=self.event,
                                    headers={'X-Task-View':token}).status_code,401)
        headers = {'Authorization':'Bearer service-test-token'}
        result = client.post('/v1/notification-replies',json=self.event,headers=headers)
        self.assertEqual(result.status_code,201)
        duplicate = client.post('/v1/notification-replies',json=self.event,headers=headers)
        self.assertEqual(duplicate.status_code,200)
        self.assertEqual(duplicate.json()['job']['id'],result.json()['job']['id'])
        self.assertEqual(client.post('/v1/notification-replies',json={**self.event,'reply_text':'Different'},headers=headers).status_code,409)
        missing = {**self.event, 'event_id':'event-missing-task', 'action':reply_action('agent','missing-task-123'),
                   'tag':'assistant-agent-missing-task-123'}
        self.assertEqual(client.post('/v1/notification-replies',json=missing,headers=headers).status_code,404)

    def test_notification_keeps_signed_details_and_unique_text_input_action(self):
        links = TaskLinks(b'x'*32)
        value = notification('agent',self.agents.get('parent-task-123'),self.agents.status(),
                             'https://assistant.example.com',task_links=links)
        actions = value['data']['actions']
        self.assertEqual(actions[0]['action'],'URI')
        self.assertEqual(actions[1], {'action':self.event['action'],'title':'Reply','behavior':'textInput'})
        self.assertEqual(actions[0]['uri'],links.url('https://assistant.example.com','agent','parent-task-123'))


if __name__=='__main__':
    unittest.main()
