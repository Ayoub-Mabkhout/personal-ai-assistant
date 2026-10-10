"""Set up encrypted credentials or search/read a live IMAP mailbox."""
import argparse
import json
import os
import sys
import threading
from pathlib import Path
from personal_assistant.connectors.imap_mail import LiveIMAP, save_credentials


def setup(args):
    # Some Windows Python installations omit Tcl's path from the GUI launcher.
    for variable, folder in [('TCL_LIBRARY', 'tcl8.6'), ('TK_LIBRARY', 'tk8.6')]:
        library = Path(sys.base_prefix) / 'tcl' / folder
        if library.is_dir():
            os.environ.setdefault(variable, str(library))
    import tkinter as tk
    from tkinter import ttk
    window = tk.Tk()
    window.title('Connect student email')
    window.geometry('470x270')
    window.lift()
    window.attributes('-topmost', True)
    window.after(1500, lambda: window.attributes('-topmost', False))
    frame = ttk.Frame(window, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='Enter your university login and password locally.').pack(anchor='w')
    username = tk.StringVar(value=args.username or '')
    password = tk.StringVar()
    for label, variable, mask in [('University ID', username, ''), ('Password', password, '*')]:
        ttk.Label(frame, text=label).pack(anchor='w', pady=(10, 2))
        ttk.Entry(frame, textvariable=variable, show=mask, width=48).pack(anchor='w')
    status = tk.StringVar(value='Read-only connection. Password encrypted for this Windows user.')
    ttk.Label(frame, textvariable=status, wraplength=425).pack(anchor='w', pady=10)
    results = []
    def connect():
        config = {'host': args.host, 'port': args.port, 'username': username.get().strip(),
                  'password': password.get(), 'account': args.account}
        if not config['username'] or not config['password']:
            status.set('Enter both fields.'); return
        button.config(state='disabled')
        status.set('Checking the secure connection...')
        def run():
            try:
                with LiveIMAP(config) as mailbox:
                    mailbox.select('INBOX')
                save_credentials(config)
                results.append({'status': 'connected', 'read_only': True})
            except Exception:
                results.append({'status': 'failed', 'message': 'Connection failed. Check your ID/password and network; no credentials saved.'})
        threading.Thread(target=run, daemon=True).start()
    def poll():
        if results:
            result = results.pop(0)
            if args.status_file:
                args.status_file.parent.mkdir(parents=True, exist_ok=True)
                args.status_file.write_text(json.dumps(result), encoding='utf-8')
            password.set('')
            status.set('Connected. You can close this window.' if result['status'] == 'connected' else result['message'])
            button.config(state='normal')
        window.after(200, poll)
    button = ttk.Button(frame, text='Connect', command=connect)
    button.pack(anchor='e')
    window.after(200, poll)
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['setup', 'check', 'search', 'read'])
    parser.add_argument('--host')
    parser.add_argument('--port', type=int, default=993)
    parser.add_argument('--username')
    parser.add_argument('--account')
    parser.add_argument('--status-file', type=Path)
    parser.add_argument('--folder', default='INBOX')
    parser.add_argument('--subject')
    parser.add_argument('--sender')
    parser.add_argument('--uid')
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    if args.operation == 'setup':
        if not args.host or not args.account:
            parser.error('setup requires --host and --account')
        setup(args); return
    if not 1 <= args.limit <= 100:
        parser.error('limit must be 1..100')
    with LiveIMAP() as mailbox:
        if args.operation == 'search':
            result = mailbox.search(args.folder, args.subject, args.sender, args.limit)
        else:
            validity = mailbox.select(args.folder)
            result = {'status': 'connected', 'read_only': True} if args.operation == 'check' else mailbox.fetch(args.uid)
            result.update(folder=args.folder, uidvalidity=validity)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
