import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from personal_assistant import calendar as calendar_module
from personal_assistant.calendar import Calendar
from personal_assistant.relay.calendar_feed import CalendarFeed, calendar_router
from personal_assistant.relay.reminders import ReminderPump, ReminderStore, epoch, wording

ROOT = Path(__file__).resolve().parents[1]


def at(text):
    """Freeze the calendar's clock at a UTC instant."""
    moment = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)
    return patch.object(calendar_module, 'datetime', Frozen)


class CalendarPageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.calendar = Calendar(self.path / 'local.db', 'Europe/Berlin')

    def tearDown(self):
        self.calendar.close()
        self.temp.cleanup()

    def local(self, value):
        return datetime.fromisoformat(value).astimezone(calendar_module.zone('Europe/Berlin')).strftime('%Y-%m-%d %H:%M')

    def test_reminder_rules_apply_by_kind_and_explicit_minutes_override_them(self):
        self.assertEqual(self.calendar.rules(), {})
        self.assertEqual(self.calendar.add('No rules yet', '2030-03-01T10:00', '2030-03-01T11:00')['event']['reminders'], [])
        self.calendar.rules(timed=[1440], all_day=[240], birthday=[9540, 15])
        with at('2030-01-01T12:00'):
            timed = self.calendar.add('Dentist', '2030-03-26T13:30', '2030-03-26T14:15')['event']
            day = self.calendar.add('Trip', '2030-03-27', all_day=True)['event']
            own = self.calendar.add('Call', '2030-03-28T09:00', '2030-03-28T09:30', reminder_minutes=[10])['event']
            none = self.calendar.add('Quiet', '2030-03-28T10:00', '2030-03-28T11:00', reminder_minutes=[])['event']
        # The day before at the same wall-clock time, even across the change to summer time on 31 March.
        self.assertEqual([self.local(r['due_at']) for r in timed['reminders']], ['2030-03-25 13:30'])
        self.assertEqual([self.local(r['due_at']) for r in day['reminders']], ['2030-03-26 20:00'])
        self.assertEqual([r['lead_minutes'] for r in own['reminders']], [10])
        self.assertEqual(none['reminders'], [])
        with self.assertRaises(ValueError):
            self.calendar.rules(weekly=[5])

    def test_birthdays_recur_yearly_with_a_week_ahead_and_late_evening_reminder(self):
        self.calendar.rules(birthday=[9540, 15])
        with at('2030-10-20T10:00'):
            birthday = self.calendar.add("Sam's birthday", '1994-10-29', all_day=True, kind='birthday')['event']
            self.assertEqual((birthday['start_date'], birthday['anchor']), ('2030-10-29', '1994-10-29'))
            self.assertEqual(sorted(self.local(r['due_at']) for r in birthday['reminders']),
                             ['2030-10-22 09:00', '2030-10-28 23:45'])
            later = self.calendar.agenda('2031-10-01', '2031-11-01')
            self.assertEqual([(e['title'], e['start_date'], e.get('occurrence')) for e in later], [("Sam's birthday", '2031-10-29', True)])
            with self.assertRaises(ValueError):
                self.calendar.add('Timed birthday', '2030-10-29T10:00', '2030-10-29T11:00', kind='birthday')
        with at('2030-10-29T22:30'):  # 23:30 in Berlin, still the 29th.
            self.assertEqual(self.calendar.roll(), 0)
        with at('2030-10-30T08:00'):
            snapshot = self.calendar.reminder_snapshot()
            moved = self.calendar.event(birthday['id'])
        self.assertEqual(moved['start_date'], '2031-10-29')
        self.assertEqual(sorted(self.local(r['due_at']) for r in moved['reminders']), ['2031-10-22 09:00', '2031-10-28 23:45'])
        self.assertEqual({r['kind'] for r in snapshot['reminders']}, {'birthday'})
        self.assertIn('rolled', [h['action'] for h in self.calendar.history(birthday['id'])])
        leap = self.calendar.add('Leap', '2000-02-29', all_day=True, kind='birthday', reminder_minutes=[])['event']
        self.assertEqual(leap['anchor'], '2000-02-29')

    def test_an_unchanged_calendar_resends_the_same_revision_after_kinds_were_added(self):
        store = ReminderStore(self.path / 'cloud.db', clock=lambda: epoch('2030-01-01T00:00:00+00:00'))
        self.calendar.add('Call', '2030-03-28T09:00', '2030-03-28T09:30', reminder_minutes=[10])
        snapshot = self.calendar.reminder_snapshot()
        legacy = dict(snapshot, reminders=[{k: v for k, v in r.items() if k != 'kind'} for r in snapshot['reminders']])
        self.assertTrue(store.project(legacy)['changed'])
        self.assertFalse(store.project(snapshot)['changed'])

    def test_reminder_wording_reads_from_when_it_fires(self):
        base = {'timezone': 'Europe/Berlin', 'location': ''}
        event = dict(base, title='Dentist', kind='event', all_day=0, start_utc='2030-10-22T11:30:00+00:00',
                     end_utc='2030-10-22T12:15:00+00:00', due_at='2030-10-21T11:30:00+00:00', location='Clinic')
        self.assertEqual(wording(event), ['Dentist', 'Tomorrow 13:30–14:15', 'Clinic'])
        birthday = dict(base, title="Sam's birthday", kind='birthday', all_day=1, start_utc='2030-10-28T23:00:00+00:00',
                        end_utc='2030-10-29T23:00:00+00:00')
        self.assertEqual(wording(dict(birthday, due_at='2030-10-28T22:45:00+00:00')), ["Sam's birthday is tomorrow", 'Tuesday 29 October'])
        self.assertEqual(wording(dict(birthday, due_at='2030-10-22T07:00:00+00:00'))[0], "Sam's birthday is in a week")
        sent = []
        store = ReminderStore(self.path / 'cloud.db', clock=lambda: epoch('2030-10-28T22:46:00+00:00'))
        with at('2030-10-20T10:00'):
            self.calendar.add("Sam's birthday", '1994-10-29', all_day=True, kind='birthday', reminder_minutes=[15])
            store.project(self.calendar.reminder_snapshot())
        ReminderPump(store, sent.append).tick()
        self.assertEqual((sent[0]['title'], sent[0]['data']['kind']), ('Birthday reminder', 'birthday'))
        self.assertTrue(sent[0]['message'].startswith("Sam's birthday is tomorrow"))

    def test_phone_reads_agenda_with_reminder_state_and_its_entries_reach_the_laptop_once(self):
        clock = [epoch('2030-10-20T10:00:00+00:00')]
        reminders = ReminderStore(self.path / 'cloud.db', clock=lambda: clock[0])
        feed = CalendarFeed(self.path / 'feed.db', reminders, clock=lambda: clock[0])
        app = FastAPI()
        def worker(authorization: str | None = Header(default=None)):
            if authorization != 'Bearer worker': raise HTTPException(401)
        def device(authorization: str | None = Header(default=None)):
            if authorization != 'Bearer phone': raise HTTPException(401)
        for router in calendar_router(feed, worker, device):
            app.include_router(router)
        api = TestClient(app)
        phone, laptop = {'Authorization': 'Bearer phone'}, {'Authorization': 'Bearer worker'}
        self.assertEqual(api.get('/groceries/v1/mobile/calendar').status_code, 401)
        self.assertEqual(api.get('/groceries/v1/mobile/calendar', headers=laptop).status_code, 401)
        entry = {'id': 'phone-entry-1', 'title': ' Haircut ', 'date': '2030-10-23', 'start': '16:00', 'end': '16:45'}
        self.assertEqual(api.post('/groceries/v1/mobile/calendar/requests', json=dict(entry, end='15:00'), headers=phone).status_code, 422)
        self.assertEqual(api.post('/groceries/v1/mobile/calendar/requests', json=dict(entry, kind='birthday'), headers=phone).status_code, 422)
        for _ in range(2):
            self.assertEqual(api.post('/groceries/v1/mobile/calendar/requests', json=entry, headers=phone).json()['state'], 'pending')
        self.assertEqual(api.post('/groceries/v1/mobile/calendar/requests', headers=phone,
                                  json={'id': 'phone-entry-2', 'title': 'Ana', 'date': '1990-11-02', 'all_day': True, 'kind': 'birthday'}).status_code, 200)
        spec = importlib.util.spec_from_file_location('calendar_sync_page', ROOT / 'scripts/sync_calendar_reminders.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        class Client:
            def call(self, path, payload=None, method=None):
                response = api.request(method or ('POST' if payload is not None else 'GET'), path, json=payload, headers=laptop) \
                    if not path.startswith('/v1/calendar/reminders') else None
                if path == '/v1/calendar/reminders/receipts': return {'receipts': reminders.receipts()}
                if path == '/v1/calendar/reminders/snapshot': return reminders.project(payload)
                self.assertOk(response)
                return response.json()
            def assertOk(self, response):
                if response.status_code != 200: raise AssertionError(response.text)
        self.calendar.rules(timed=[1440], birthday=[9540, 15])
        self.calendar.close()
        with at('2030-10-20T10:00'):
            result = script.synchronize(self.path / 'local.db', Client())
            self.assertEqual(result['added'], 2)
            self.assertEqual(script.synchronize(self.path / 'local.db', Client())['added'], 0)
        self.calendar = Calendar(self.path / 'local.db')
        view = api.get('/groceries/v1/mobile/calendar', headers=phone).json()
        self.assertEqual([(r['title'], r['state']) for r in view['requests']], [('Haircut', 'added'), ('Ana', 'added')])
        events = {e['title']: e for e in reversed(view['events'])}  # The first occurrence of each.
        self.assertEqual(events['Haircut']['origin'], 'companion')
        self.assertEqual([r['state'] for r in events['Haircut']['reminders']], ['scheduled'])
        self.assertEqual((events['Ana']['kind'], events['Ana']['start_date']), ('birthday', '2030-11-02'))
        self.assertNotIn('source_key', events['Haircut'])
        self.assertEqual(len([e for e in self.calendar.agenda('2030-10-01', '2030-12-01') if e['title'] == 'Haircut']), 1)


if __name__ == '__main__':
    unittest.main()
