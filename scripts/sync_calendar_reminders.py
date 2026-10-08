"""Publish calendar reminders to the cloud; a complete snapshot removes cancellations."""
import argparse
import json
import logging
from pathlib import Path
import time

from personal_assistant.calendar import Calendar, DEFAULT_DB
from personal_assistant.worker.runtime import RelayClient


def synchronize(database, client):
    calendar = Calendar(database)
    try:
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
        return {**result, 'acknowledged': acknowledged}
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
