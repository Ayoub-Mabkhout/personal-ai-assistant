from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from personal_assistant.calendar import Calendar
from personal_assistant.relay.store import Queue, Conflict
from personal_assistant.worker.runtime import Worker, CalendarExecutor, TransportError, calendar_range, Singleton


class LocalRelay:
    def __init__(self, queue):
        self.queue, self.offline, self.lose_ack = queue, False, False

    def call(self,path,payload=None):
        if self.offline:
            raise TransportError()
        if path.endswith('/heartbeat'):
            return self.queue.heartbeat(payload['readiness'])
        if path.endswith('/claim'):
            return {'job':self.queue.claim(payload['lease_seconds'])}
        job_id=path.split('/')[-2]
        try:
            if path.endswith('/renew'):
                return self.queue.renew(job_id,payload['lease_token'],payload['lease_seconds'])
            if path.endswith('/result'):
                result=self.queue.finish(job_id,payload['lease_token'],payload['state'],payload['result'])
                if self.lose_ack:
                    self.lose_ack=False
                    raise TransportError()
                return result
        except Conflict:
            raise TransportError(409) from None
        raise AssertionError(path)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.calendar=self.root/'calendar.sqlite3'
        calendar=Calendar(self.calendar,'Europe/Berlin')
        calendar.add(title='Isolated test appointment',start='2026-10-03T10:00',end='2026-10-03T11:00')
        calendar.close()
        self.queue=Queue(self.root/'relay.sqlite3',clock=lambda:datetime(2026,10,4,tzinfo=timezone.utc).timestamp())
        self.client=LocalRelay(self.queue)
        self.config={'runtime_dir':str(self.root/'worker'),'calendar_db':str(self.calendar),
            'python':sys.executable,'repository':str(Path(__file__).resolve().parents[1])}
        self.payload={'id':'worker-test-123','command':"What is on my calendar tomorrow?",'timezone':'Europe/Berlin',
            'created_at':'2026-10-02T23:58:00+02:00'}

    def tearDown(self):
        self.temp.cleanup()

    def test_outage_keeps_request_and_reconnect_executes(self):
        self.queue.submit(self.payload)
        worker=Worker(self.config,self.client)
        self.client.offline=True
        with self.assertRaises(TransportError):
            worker.tick()
        self.assertEqual(self.queue.get(self.payload['id'])['state'],'queued')
        self.client.offline=False
        worker.tick()
        job=self.queue.get(self.payload['id'])
        self.assertEqual(job['state'],'completed')
        self.assertEqual(job['result']['range']['from'],'2026-10-03')
        self.assertEqual(job['result']['events'][0]['title'],'Isolated test appointment')

    def test_lost_ack_recovered_without_reexecution_after_restart(self):
        self.queue.submit(self.payload)
        executor=CalendarExecutor(self.config)
        original=executor.execute
        calls=[]
        executor.execute=lambda *args:(calls.append(1),original(*args))[1]
        worker=Worker(self.config,self.client,executor)
        self.client.lose_ack=True
        with self.assertRaises(TransportError):
            worker.tick()
        self.assertEqual(self.queue.get(self.payload['id'])['state'],'completed')
        restarted=Worker(self.config,self.client,executor)
        restarted.tick()
        self.assertEqual(len(calls),1)
        with restarted.ledger.db() as db:
            self.assertEqual(db.execute('SELECT state FROM runs').fetchone()[0],'acknowledged')
        self.assertEqual(restarted.ledger.pending(),[])

    def test_cancelled_job_cannot_acknowledge_or_notify(self):
        self.queue.submit(self.payload)
        executor=CalendarExecutor(self.config)
        original=executor.execute
        def cancel_then_execute(job,flag):
            self.queue.cancel(job['id'])
            return original(job,flag)
        executor.execute=cancel_then_execute
        notifications=[]
        worker=Worker(self.config,self.client,executor,lambda *args:notifications.append(args))
        worker.tick()
        self.assertEqual(self.queue.get(self.payload['id'])['state'],'cancelled')
        self.assertEqual(notifications,[])

    def test_relative_dates_anchor_to_original_request_and_dst(self):
        self.assertEqual(calendar_range(self.payload),('2026-10-03','2026-10-04'))
        self.assertEqual(calendar_range({**self.payload,'created_at':'2026-10-24T23:00:00+02:00'}),
            ('2026-10-25','2026-10-26'))
        self.assertEqual(calendar_range({**self.payload,'command':'Show calendar next week'}),
            ('2026-10-05','2026-10-12'))

    def test_writes_and_ambiguous_weekdays_need_input(self):
        self.assertIsNone(calendar_range({**self.payload,'command':'Delete all calendar appointments'}))
        self.assertIsNone(calendar_range({**self.payload,'command':'Show calendar next Friday'}))

    def test_missing_calendar_reports_blocked_without_claim(self):
        self.queue.submit(self.payload)
        worker=Worker({**self.config,'calendar_db':str(self.root/'missing.sqlite3')},self.client)
        worker.tick()
        self.assertEqual(self.queue.status()['laptop'],'blocked')
        self.assertEqual(self.queue.get(self.payload['id'])['state'],'queued')

    def test_single_instance(self):
        with Singleton(self.root/'singleton.lock'):
            with self.assertRaises((RuntimeError,OSError)):
                with Singleton(self.root/'singleton.lock'):
                    pass

    def test_notification_failure_backoff_survives_restart(self):
        self.queue.submit(self.payload)
        calls=[]
        def unavailable(*args):
            calls.append(1)
            raise OSError('offline')
        worker=Worker(self.config,self.client,notifier=unavailable)
        worker.tick()
        row=worker.ledger.pending()[0]
        self.assertEqual(row['acknowledged'],1)
        self.assertEqual(row['notification_attempts'],1)
        restarted=Worker(self.config,self.client,notifier=unavailable)
        restarted.tick()
        self.assertEqual(len(calls),1)
        with restarted.ledger.db() as db:
            db.execute('UPDATE outbox SET notify_after=0')
        delivered=[]
        restarted.notifier=lambda *args:delivered.append(args)
        restarted.tick()
        self.assertEqual(len(delivered),1)
        self.assertEqual(restarted.ledger.pending(),[])


if __name__ == '__main__':
    unittest.main()
