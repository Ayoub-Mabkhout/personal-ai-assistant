import tempfile
import unittest
from pathlib import Path

from personal_assistant.relay.answer_streams import Snapshot,queue_snapshot,coach_snapshot,money_snapshot,read_many
from personal_assistant.relay.store import Queue,Conflict
from personal_assistant.relay.mobile_tasks import MobileTasks
from personal_assistant.relay.banking import Banking,ConversationQuestion,ConversationAnswer
from personal_assistant.workout.store import Workouts


class AnswerSnapshotsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.now=1000
        self.queue=Queue(self.root/'queue.sqlite3',clock=lambda:self.now)
        self.queue.submit({'id':'stream-test-job','command':'Reply','created_at':'1970-01-01T00:16:40Z','timezone':'UTC'})
        self.queue.heartbeat('ready')
        self.job=self.queue.claim(60)

    def body(self,text='',sequence=0,token=None):
        return Snapshot(token=token or self.job['lease_token'],sequence=sequence,text=text)

    def test_lease_fencing_sequences_and_final_authority(self):
        queue_snapshot(self.queue,self.job['id'],self.body())
        result=queue_snapshot(self.queue,self.job['id'],self.body('Hello',1))
        self.assertEqual(queue_snapshot(self.queue,self.job['id'],self.body('Hello',1)),result)
        with self.assertRaises(Conflict):queue_snapshot(self.queue,self.job['id'],self.body('Other',1))
        with self.assertRaises(Conflict):queue_snapshot(self.queue,self.job['id'],self.body('Wrong',2,'wrong-lease-token'))
        tasks=MobileTasks({'agent':self.queue})
        partial=tasks.detail('agent',self.job['id'])
        self.assertEqual(partial['partial_answer'],'Hello')
        version=partial['version']
        self.queue.finish(self.job['id'],self.job['lease_token'],'completed',{'summary':'Final answer'})
        final=tasks.detail('agent',self.job['id'])
        self.assertEqual(final['summary'],'Final answer');self.assertNotIn('partial_answer',final)
        self.assertNotEqual(final['version'],version)
        with self.assertRaises(Conflict):queue_snapshot(self.queue,self.job['id'],self.body('Late text',2))

    def test_expired_attempt_cannot_overwrite_retry(self):
        queue_snapshot(self.queue,self.job['id'],self.body())
        queue_snapshot(self.queue,self.job['id'],self.body('Old answer',1))
        self.now+=61
        self.queue.heartbeat('ready')
        new=self.queue.claim(60)
        queue_snapshot(self.queue,self.job['id'],self.body('',0,new['lease_token']))
        with self.assertRaises(Conflict):queue_snapshot(self.queue,self.job['id'],self.body('Stale answer',2))
        with self.queue.connection() as db:
            self.assertEqual(read_many(db,'agent',[self.job['id']])[self.job['id']]['partial_answer'],'')

    def test_coach_streams_are_user_scoped_and_do_not_apply_changes(self):
        store=Workouts(self.root/'workout.sqlite3',clock=lambda:self.now)
        store.question('coach-stream-test','Hi')
        job=store.claim()
        coach_snapshot(store,job['id'],Snapshot(token=job['token'],sequence=0,text=''))
        old_version=store.conversation_view()['version']
        coach_snapshot(store,job['id'],Snapshot(token=job['token'],sequence=1,text='Hello athlete'))
        view=store.conversation_view()
        self.assertEqual(view['items'][0]['partial_answer'],'Hello athlete')
        self.assertNotEqual(view['version'],old_version)
        self.assertFalse(view['items'][0]['proposals'])
        with store.db() as db:self.assertEqual(read_many(db,'coach:another-user',[job['id']]),{})
        store.finish(job['id'],job['token'],'Final coaching answer',[])
        self.assertNotIn('partial_answer',store.conversation()[0])
        with self.assertRaises(Conflict):coach_snapshot(store,job['id'],Snapshot(token=job['token'],sequence=2,text='Late'))

    def test_money_partial_is_replaced_by_final_and_stays_private(self):
        bank=Banking(self.root/'banking.sqlite3',clock=lambda:self.now)
        bank.ask(ConversationQuestion(id='money-stream-test',text='Explain spending'))
        body=Snapshot(token='private-stream-attempt',sequence=0,text='')
        money_snapshot(bank,'money-stream-test',body)
        money_snapshot(bank,'money-stream-test',body.model_copy(update={'sequence':1,'text':'Checking purchases'}))
        self.assertEqual(bank.conversation('money-stream-test')['partial_answer'],'Checking purchases')
        bank.reply('money-stream-test',ConversationAnswer(text='Final spending answer'))
        self.assertNotIn('partial_answer',bank.conversation('money-stream-test'))
        with self.assertRaises(Conflict):money_snapshot(bank,'money-stream-test',body)


if __name__=='__main__':unittest.main()
