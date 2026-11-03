import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from personal_assistant.workout.reminder import Subscription, TrainReminders
from personal_assistant.workout.store import Workouts
from personal_assistant.workout.web_push import WebPush


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


class Push:
    def __init__(self):
        self.sent = []
        self.status = 201

    def send(self, subscription, payload, ttl):
        self.sent.append((subscription['endpoint'], json.loads(payload), ttl))
        return self.status


class ScheduledTrainTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        self.now = datetime(2026, 11, 6, 17, 25, tzinfo=timezone.utc).timestamp()
        self.root = Workouts(self.path/'workout.sqlite3', clock=lambda: self.now)
        self.store = self.root.for_user('athlete')
        self.provider = Push()
        self.reminders = TrainReminders(self.root, self.provider)
        public = ec.generate_private_key(ec.SECP256R1()).public_key()
        point = public.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.sub = Subscription(endpoint='https://fcm.googleapis.com/fcm/send/synthetic',
                                keys={'auth': b64(bytes(16)), 'p256dh': b64(point)})
        self.reminders.subscribe('athlete', self.sub)
        self.reminders.settings('athlete', {'scheduled_sprints': True})

    def record(self, kind, identifier, data, revision=0):
        return self.store.mutate([{'kind': kind, 'id': identifier, 'base_revision': revision,
                                  'mutation_id': f'{kind}-{identifier}-{revision}', 'data': data}])[0]

    def plan(self):
        return {'name': 'Plan', 'phase': 'build', 'status': 'active', 'start': '2026-11-01',
                'scheduled': [
                    {'id': f'slot-{day}', 'date': f'2026-11-0{day}',
                     'starts_at': f'2026-11-0{day}T19:00:00+01:00', 'template_id': 'template'}
                    for day in (4, 5, 6)]}

    def test_fallback_at_due_with_escalation_private_photo_and_no_duplicate(self):
        self.record('sprint', 'sprint', self.plan())
        raw = b'\xff\xd8\xffsynthetic'
        digest = hashlib.sha256(raw).hexdigest()
        self.store.put_blob(digest, 'image/jpeg', raw)
        self.record('photo', 'photo', {'blob_id': digest, 'captured_at': '2026-11-04T16:00:00Z'})
        self.reminders.settings('athlete', {'enabled': True, 'roast': True, 'photos_enabled': True,
                                           'photo_ids': ['photo']})
        self.reminders.tick()
        self.assertEqual(self.provider.sent, [])
        self.now += 300
        self.reminders.tick()
        self.reminders.tick()
        self.assertEqual(len(self.provider.sent), 1)
        _, payload, ttl = self.provider.sent[0]
        self.assertEqual(ttl, 1800)
        self.assertIn('Two misses', payload['body'])
        self.assertEqual(payload['image'], '/train/api/photos/'+digest)
        self.assertEqual(self.reminders.history('athlete', payload['id']), payload)
        from personal_assistant.relay.store import Missing
        with self.assertRaises(Missing):
            self.reminders.history('another-athlete', payload['id'])
        self.reminders.settings('athlete', {'roast': False})
        self.assertIsNone(self.reminders.history('athlete', payload['id'])['image'])

    def test_reminder_photo_opt_in_is_separate_and_rotates_selected_uploads(self):
        self.record('sprint', 'sprint', self.plan())
        paths = []
        for identifier in ('photo-one', 'photo-two'):
            raw = b'\xff\xd8\xff' + identifier.encode()
            digest = hashlib.sha256(raw).hexdigest()
            self.store.put_blob(digest, 'image/jpeg', raw)
            self.record('photo', identifier, {'blob_id': digest, 'captured_at': '2026-11-03T16:00:00Z'})
            paths.append('/train/api/photos/'+digest)
        ids = ['photo-one', 'photo-two']
        self.reminders.settings('athlete', {'enabled': True, 'roast': True, 'photo_ids': ids})
        self.now += 300 - 2 * 86400
        self.reminders.tick()
        self.assertIsNone(self.provider.sent[-1][1]['image'])
        self.reminders.settings('athlete', {'photos_enabled': True})
        for expected in paths:
            self.now += 86400
            self.reminders.tick()
            self.assertEqual(self.provider.sent[-1][1]['image'], expected)
        self.reminders.settings('athlete', {'photos_enabled': False})
        self.assertEqual(self.reminders.settings('athlete')['photo_ids'], ids)
        for _, payload, _ in self.provider.sent:
            self.assertIsNone(self.reminders.history('athlete', payload['id'])['image'])

    def test_ready_coach_supplies_message_and_cancelled_slot_does_not_retry(self):
        plan = self.plan()
        sprint = self.record('sprint', 'sprint', plan)
        self.reminders.settings('athlete', {'enabled': True, 'roast': True})
        self.store.heartbeat()
        self.reminders.tick()
        job = self.store.claim()
        self.assertEqual(job['context']['missed_streak'], 2)
        self.assertEqual(self.root.claim(), None)
        self.store.finish(job['id'], job['token'], 'Coach line.', [])
        self.assertEqual(self.store.conversation(), [])
        self.now += 300
        self.provider.status = 503
        self.reminders.tick()
        self.assertEqual(self.provider.sent[0][1]['body'], 'Coach line.')
        plan['status'] = 'cancelled'
        self.record('sprint', 'sprint', plan, sprint['revision'])
        self.now += 60
        self.reminders.tick()
        self.assertEqual(len(self.provider.sent), 1)

    def test_completed_sets_compare_with_plan_and_recovery_keeps_brief_optional(self):
        self.record('template', 'template', {'name': 'Plan', 'exercises': [
            {'exercise_id': 'bench', 'sets': 2, 'min_reps': 6, 'weight_kg': 50}]})
        self.reminders.settings('athlete', {'roast': True})
        self.record('workout', 'short', {'name': 'Workout', 'started_at': '2026-11-06',
            'status': 'completed', 'template_id': 'template', 'source': {'companion': {}},
            'sets': [{'id': 'warmup', 'exercise_id': 'bench', 'kind': 'warmup', 'reps': 9},
                     {'id': 'work', 'exercise_id': 'bench', 'reps': 4, 'weight_kg': 45}]})
        job = self.store.claim()
        self.assertEqual([item['metric'] for item in job['context']['shortfalls']], ['sets', 'reps', 'weight_kg'])
        self.store.finish(job['id'], job['token'], 'Brief.', [])
        self.record('workout', 'met', {'name': 'Workout', 'started_at': '2026-11-06',
            'status': 'completed', 'template_id': 'template', 'source': {'companion': {}},
            'sets': [{'id': str(i), 'exercise_id': 'bench', 'reps': 6, 'weight_kg': 50} for i in range(2)]})
        self.assertIsNone(self.store.claim())

    def test_push_uses_encryption_and_refuses_unknown_destinations(self):
        import http_ece
        private = ec.generate_private_key(ec.SECP256R1())
        key = self.path/'push.pem'
        key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
        provider = WebPush(key, 'mailto:train@example.test')
        public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        subscription = self.sub.model_dump()
        subscription['keys']['p256dh'] = b64(public)

        def inspect(request, timeout):
            self.assertTrue(request.get_header('Authorization').startswith('vapid '))
            self.assertEqual(http_ece.decrypt(request.data, private_key=private, auth_secret=bytes(16)), b'hello')
            from urllib.error import HTTPError
            raise HTTPError(request.full_url, 410, 'expired', {}, None)

        provider.opener.open = inspect
        self.assertEqual(provider.send(subscription, b'hello', 1800), 410)
        subscription['endpoint'] = 'https://fcm.googleapis.com.attacker.test/fcm/send/synthetic'
        with self.assertRaises(ValueError):
            provider.send(subscription, b'hello', 1800)
