"""Per-user supervisor: worker and local dashboard; no administrator privileges."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
from personal_assistant.worker.runtime import Singleton
from personal_assistant.worker.processes import ProcessJob


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding='utf-8'))
    runtime=Path(config['runtime_dir'])
    runtime.mkdir(parents=True,exist_ok=True)
    stop=threading.Event()
    for signum in (signal.SIGINT,signal.SIGTERM):
        signal.signal(signum,lambda *_:stop.set())
    children={}
    commands={name:[config['python'],'-m',module,'--config',str(args.config)] for name,module in
        [('worker','personal_assistant.worker.runtime'),('dashboard','personal_assistant.dashboard')]}
    if config.get('whatsapp_binary'):
        commands['whatsapp']=[config['whatsapp_binary'],'--runtime',config['whatsapp_runtime']]
    if config.get('orchestrator_dir'):
        commands['agents']=[config['python'],'-m','personal_assistant.orchestrator.service','--config',str(args.config)]
    if config.get('calendar_reminder_sync'):
        commands['calendar-reminders']=[config['python'],str(Path(config['repository'])/'scripts/sync_calendar_reminders.py'),
            '--config',str(args.config),'--watch',*(['--db',config['calendar_db']] if config.get('calendar_db') else [])]
    if config.get('mail_automation_config'):
        commands['mail-automation']=[config['python'],str(Path(config['repository'])/'scripts/mail_automation.py'),
            '--config',config['mail_automation_config'],'--loop']
    files={}
    with Singleton(runtime/'services.lock'):
        job=ProcessJob()
        try:
            for name in commands:
                path=runtime/(name+'-service.log')
                if path.exists() and path.stat().st_size > 1024*1024:
                    path.replace(path.with_suffix('.previous.log'))
                files[name]=path.open('ab')
            while not stop.is_set():
                for name,command in commands.items():
                    if name not in children or children[name].poll() is not None:
                        children[name]=subprocess.Popen(command,cwd=config['repository'],
                            stdout=files[name],stderr=files[name],
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                (runtime/'services.json').write_text(json.dumps({'supervisor':os.getpid(),
                    **{name:process.pid for name,process in children.items()}}))
                stop.wait(10)
        finally:
            for process in children.values():
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
            for handle in files.values():
                handle.close()


if __name__=='__main__':
    try:
        main()
    except Exception:
        import traceback
        log=Path.home()/'.personal-assistant/worker/supervisor-error.log'
        log.parent.mkdir(parents=True,exist_ok=True)
        log.write_text(traceback.format_exc(),encoding='utf-8')
        raise
