"""Resolve timed sprint slots and compare completed work with prescribed work."""

from collections import Counter, defaultdict
from datetime import datetime

LEAD = 30 * 60
MISSED_AFTER = 3 * 3600


def timed_slots(sprint, workouts):
    slots = [slot for slot in sprint['data']['scheduled'] if slot.get('starts_at')]
    keys = Counter((slot['date'], slot.get('template_id')) for slot in slots)
    by_id = defaultdict(set)
    by_date = defaultdict(set)
    from .analytics import scheduled_day
    for row in workouts:
        data = row['data']
        if data.get('sprint_id') != sprint['id']:
            continue
        companion = data.get('source', {}).get('companion')
        slot_id = companion.get('scheduled_session_id') if isinstance(companion, dict) else None
        if isinstance(slot_id, str) and slot_id:
            by_id[slot_id].add(data['status'])
        else:
            by_date[(scheduled_day(data).isoformat(), data.get('template_id'))].add(data['status'])
    result = []
    for slot in slots:
        key = (slot['date'], slot.get('template_id'))
        statuses = by_id[slot['id']] | (by_date[key] if keys[key] == 1 else set())
        state = next((state for state in ('completed', 'rest', 'active', 'paused', 'skipped') if state in statuses), 'pending')
        result.append((datetime.fromisoformat(slot['starts_at']).timestamp(), slot, state))
    return sorted(result, key=lambda entry: (entry[0], entry[1]['id']))


def shortfalls(template, workout):
    """Use logged completed sets, excluding warmups, and the stored template targets."""
    actual = defaultdict(list)
    for item in workout['sets']:
        if item['completed'] and item['kind'] in ('working', 'drop', 'failure'):
            actual[item['exercise_id']].append(item)
    misses = []
    for exercise in template['exercises']:
        eid = exercise['exercise_id']
        plan = exercise.get('set_plan', [])
        prescribed = [item for item in plan if item['kind'] != 'warmup']
        if not plan:
            distance = exercise.get('distance_m')
            prescribed = [{'reps': exercise.get('min_reps') if distance is None else None,
                           'weight_kg': exercise.get('weight_kg'), 'distance_m': distance,
                           'seconds': exercise.get('estimated_seconds') or None}] * exercise['sets']
        logged = actual[eid]
        if len(logged) < len(prescribed):
            misses.append({'exercise_id': eid, 'metric': 'sets', 'planned': len(prescribed), 'actual': len(logged)})
        for index, (target, completed) in enumerate(zip(prescribed, logged), start=1):
            for metric in ('reps', 'weight_kg', 'distance_m', 'seconds'):
                goal, value = target.get(metric), completed.get(metric)
                if goal is None or value is None:
                    continue
                too_slow = metric == 'seconds' and target.get('distance_m') and value > goal
                too_little = (metric != 'seconds' or not target.get('distance_m')) and value < goal
                if too_slow or too_little:
                    misses.append({'exercise_id': eid, 'set': index, 'metric': metric,
                                   'planned': goal, 'actual': value})
    return misses[:24]
