"""Publish calendar reminders and the phone's agenda to the cloud, and apply entries added on the phone.

A complete reminder snapshot removes cancellations. The laptop calendar stays the only writer: phone entries are
queued in the cloud and added here with a stable source key, so a repeated request never creates a duplicate."""
import argparse
import json
import logging
from pathlib import Path
import time

from personal_assistant.calendar import Calendar, DEFAULT_DB
from personal_assistant.worker.runtime import RelayClient, TransportError


def apply_requests(calendar, client):
    """Add entries queued on the phone and report each outcome back to it."""
    applied = 0
    for request in client.call('/v1/calendar/requests')['requests']:
        birthday = request.get('kind') == 'birthday'
        try:
            if request.get('all_day') or birthday:
                result = calendar.add(request['title'], request['date'], all_day=True, kind='birthday' if birthday else 'event',
                                      source_ref='Companion', source_key='companion:' + request['id'])
            else:
                result = calendar.add(request['title'], request['date'] + 'T' + request['start'], request['date'] + 'T' + request['end'],
                                      source_ref='Companion', source_key='companion:' + request['id'])
        except ValueError as error:
            client.call('/v1/calendar/requests/' + request['id'], {'added': False, 'detail': str(error)})
        else:
            client.call('/v1/calendar/requests/' + request['id'], {'added': True, 'event_id': result['event']['id']})
            applied += 1
    return applied


def synchronize(database, client):
    calendar = Calendar(database)
    try:
        try:
            added = apply_requests(calendar, client)
        except TransportError as error:
            if error.status != 404:
                raise
            added = None  # A relay without the calendar feed still receives reminders.
        # Reconcile known current IDs only. Cancelled/moved occurrences have no local record.
        accepted = client.call('/v1/calendar/reminders/receipts')['receipts']
        current = {row['id'] for row in calendar.db.execute('SELECT id FROM reminders WHERE delivered_at IS NULL')}
        acknowledged = 0
        for receipt in accepted:
            if receipt['id'] in current:
                try:
                    calendar.acknowledge(receipt['id'])
                    acknowledged += 1
                except ValueError:
                    pass  # Calendar changed concurrently; next full projection removes it.
        result = client.call('/v1/calendar/reminders/snapshot', calendar.reminder_snapshot())
        if added is not None:
            client.call('/v1/calendar/agenda', calendar.phone_agenda(), method='PUT')
        return {**result, 'acknowledged': acknowledged, 'added': added}
    finally:
        calendar.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--config', type=Path, default=Path.home()/'.personal-assistant/worker/config.json')
    parser.add_argument('--interval', type=float, default=30)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    if args.interval < 5:
        parser.error('Sync interval must be at least five seconds.')
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    client = RelayClient(config['relay_url'], config['worker_token_file'], timeout=20)
    while True:
        try:
            result = synchronize(args.db, client)
            if not args.watch:
                print(json.dumps(result))
                return
        except Exception as error:
            if not args.watch:
                raise
            logging.warning('Calendar reminder sync failed (%s); retrying.', type(error).__name__)
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
