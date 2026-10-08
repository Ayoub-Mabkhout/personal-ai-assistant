"""Run only after explicit read-only OAuth setup for each selected mailbox."""
import argparse
import json
from pathlib import Path
from personal_assistant.connectors.mail import Archive, GmailCrawler, OutlookCrawler, MailHTTP, OAuthFile
from personal_assistant.worker.runtime import Singleton

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['gmail','outlook'], required=True)
    parser.add_argument('--account', required=True, help='Stable unique account label; never a secret')
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--restart-scan', action='store_true')
    args=parser.parse_args()
    crawler=GmailCrawler if args.provider == 'gmail' else OutlookCrawler
    archive=Archive(args.archive)
    with Singleton(archive.root/'crawl.lock'):
        output=crawler(MailHTTP(OAuthFile(args.credentials),args.provider),archive,
            args.provider + ':' + args.account).scan(args.restart_scan)
    print(json.dumps(output))
