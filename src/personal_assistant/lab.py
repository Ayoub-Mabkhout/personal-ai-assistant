"""Per-task dependency environments. These are not OS security sandboxes."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import venv


def default_root():
    return Path.home() / '.personal-assistant/lab'


def create(name, root=None, javascript=False):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', name):
        raise ValueError('Use a simple task name without path separators.')
    if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]', name, re.I):
        raise ValueError('Reserved Windows device name.')
    root = Path(root or default_root()).resolve()
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    environment = directory / '.venv'
    if not environment.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    tools = {key: shutil.which(key) for key in ('node','git','pwsh','javac','dotnet','go','rustc','cargo')}
    node = tools['node']
    if javascript and node:
        npm_script = Path(node).parent / 'node_modules/npm/bin/npm-cli.js'
        if not npm_script.is_file():
            raise ValueError('Node was found but its npm CLI path needs configuration.')
        package = directory / 'package.json'
        if not package.exists():
            package.write_text(json.dumps({'name':name.casefold(),'private':True,'version':'0.0.0',
                'scripts':{'typecheck':'tsc --noEmit'}},indent=2)+'\n')
        result = subprocess.run([node,str(npm_script),'install','--ignore-scripts','--save-dev','typescript'],
            cwd=directory,capture_output=True,timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            raise RuntimeError('npm setup failed; see the task package files before retrying.')
    report = {'workspace':str(directory),'python':str(python),'tools':tools,
        'node_dependencies_local':bool(javascript and node),'created_at':datetime.now(timezone.utc).isoformat(),
        'isolation':'Per-task dependency isolation; runs as the current OS user, not a security sandbox.'}
    (directory / 'environment.json').write_text(json.dumps(report,indent=2)+'\n')
    instructions = directory / 'AGENTS.md'
    if not instructions.exists():
        instructions.write_text('Work only on the explicitly requested task.\n'
            'This directory organizes dependencies and execution records. The owner allows\n'
            'full-computer access to the files needed for the requested task.\n'
            'Use this task\'s .venv for Python and local node_modules for JavaScript/TypeScript.\n'
            'Do not read unrelated personal files or credential stores. Do not send messages,\n'
            'purchase anything or publish externally without explicit authorization.\n')
    return report


def run_coding_task(workspace, prompt, codex=None, node=None, timeout=1200):
    """Public launches enter the same cloud inbox and Luna session as phone tasks."""
    from personal_assistant.orchestrator.submit import submit
    return submit(prompt,workspace=workspace,wait=True,timeout=timeout)


def _run_coding_task(workspace, prompt, codex, node=None, timeout=1200):
    workspace=Path(workspace).resolve()
    if not workspace.is_relative_to(default_root().resolve()) or not (workspace/'environment.json').is_file():
        raise ValueError('Use a prepared task workspace under the private lab root.')
    run=workspace/'runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run.mkdir(parents=True)
    (run/'prompt.txt').write_text(prompt,encoding='utf-8')
    executable=[str(codex)]
    if Path(codex).suffix == '.js':
        if not node:
            raise ValueError('The Codex JavaScript entry point needs the Node executable.')
        executable=[str(node),str(codex)]
    args=executable+['exec','--json','--ignore-user-config','--sandbox','danger-full-access',
        '-c','approval_policy="never"','--skip-git-repo-check','-C',str(workspace),
        '--output-last-message',str(run/'result.txt'),'-']
    clean_env={key:value for key,value in os.environ.items()
        if not key.startswith(('ASSISTANT_','OCI_','OPENAI_')) and key not in ('CODEX_API_KEY',)}
    exit_code, error, termination = None, None, None
    with (run/'events.jsonl').open('wb') as out, (run/'stderr.log').open('wb') as err:
        try:
            process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=out,stderr=err,env=clean_env,
                cwd=workspace,creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                start_new_session=os.name != 'nt')
            try:
                process.communicate(prompt.encode(),timeout=timeout)
                exit_code=process.returncode
            except subprocess.TimeoutExpired:
                error='timeout'
                if process.poll() is None:
                    if os.name == 'nt':
                        killed=subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                            capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
                        termination='process_tree' if killed.returncode == 0 else 'tree_kill_failed'
                        if killed.returncode:
                            process.kill()
                    else:
                        import signal
                        os.killpg(process.pid,signal.SIGKILL)
                        termination='process_group'
                process.communicate(timeout=15)
                exit_code=process.returncode
        except subprocess.TimeoutExpired:
            error=error or 'termination_timeout'
        except OSError:
            error=error or 'launch_failed'
    sessions=[]
    for line in (run/'events.jsonl').read_text(encoding='utf-8',errors='replace').splitlines():
        try:
            event=json.loads(line)
            if event.get('type') == 'thread.started':
                sessions.append(event['thread_id'])
        except (ValueError,KeyError):
            pass
    record={'exit_code':exit_code,'error':error,'termination':termination,'session_ids':sessions,
        'prompt':str(run/'prompt.txt'),'trace':str(run/'events.jsonl'),'stderr':str(run/'stderr.log'),
        'result':str(run/'result.txt'),'workspace':str(workspace),'verified_effects':False}
    (run/'record.json').write_text(json.dumps(record,indent=2))
    return record
