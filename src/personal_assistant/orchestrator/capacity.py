"""Agent capacity snapshot for dispatch decisions: remaining Codex and Claude allowance.

Codex records the account's rate-limit windows in every session rollout. Headless
Claude runs emit a rate_limit_event, which the Claude worker caches after each call.
Reading these costs no model call, so every dispatcher turn sees how much of each
agent's five-hour and weekly allowance is left without checking itself. When the
Claude figure is old, a minimal background Haiku call refreshes it at most hourly.
"""
from datetime import datetime,timezone
import json
import os
import queue
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

WINDOWS={300:'five_hour',10080:'weekly'}
TAIL=256*1024 # rate-limit records are near the end of a rollout; avoid reading whole logs
STALE=3600 # refresh Claude figures older than an hour
_refreshing=threading.Lock()


def codex_home(config):
    return Path(config.get('codex_home') or os.environ.get('CODEX_HOME') or Path.home()/'.codex')


def claude_executable(config):
    configured=config.get('claude')
    if configured:return configured if Path(configured).is_file() else None
    # The supervised service may not inherit the user PATH; the native installer uses ~/.local/bin.
    return shutil.which('claude') or shutil.which('claude',path=str(Path.home()/'.local'/'bin'))


def claude_cache(config):
    return Path(config['orchestrator_dir'])/'claude-capacity.json'


def recent_rollouts(home,limit=6):
    sessions=Path(home)/'sessions'
    if not sessions.is_dir():return []
    # Date folders sort lexically (YYYY/MM/DD); only the newest few days need a scan.
    days=sorted((d for y in sessions.iterdir() if y.is_dir() for m in y.iterdir() if m.is_dir() for d in m.iterdir() if d.is_dir()),reverse=True)[:3]
    files=[f for d in days for f in d.glob('rollout-*.jsonl')]
    return sorted(files,key=lambda f:f.stat().st_mtime,reverse=True)[:limit]


def latest_limits(path):
    """Newest rate-limit record per limit_id in one rollout, with its timestamp."""
    with open(path,'rb') as stream:
        stream.seek(0,os.SEEK_END);size=stream.tell();stream.seek(max(0,size-TAIL))
        lines=stream.read().decode('utf-8',errors='replace').splitlines()
    found={}
    for line in reversed(lines):
        if '"rate_limits"' not in line:continue
        try:event=json.loads(line)
        except ValueError:continue # the first line of the tail can be partial
        limits=(event.get('payload') or {}).get('rate_limits') or {}
        key=limits.get('limit_id') or 'codex'
        if key not in found:found[key]=(event.get('timestamp'),limits)
    return found


def window(used,resets,now):
    # A window that reset after the record was written starts again from zero.
    reset=resets is not None and resets<=now
    return {'used_percent':0.0 if reset else used,'remaining_percent':100.0 if reset else (None if used is None else round(100-used,1)),
            'resets_in_minutes':None if resets is None or reset else round((resets-now)/60),
            'resets_at':None if resets is None else datetime.fromtimestamp(resets,timezone.utc).isoformat(),
            **({'reset_since_observed':True} if reset else {})}


def codex_cache(config):
    return Path(config['orchestrator_dir'])/'codex-capacity.json'


def refresh_codex(config):
    """Read the subscription's account limits without starting a model turn."""
    executable = config.get('codex')
    if not executable:
        return
    prefix = [config.get('node', 'node'), executable] if Path(executable).suffix == '.js' else [executable]
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('OPENAI_') and key != 'CODEX_API_KEY'}
    env['CODEX_HOME'] = str(codex_home(config))
    incoming = queue.Queue()

    def read(stream):
        for line in stream:
            try:
                incoming.put(json.loads(line))
            except ValueError:
                continue
        incoming.put({})

    with tempfile.TemporaryDirectory(prefix='codex-capacity-') as directory:
        with subprocess.Popen(prefix+['app-server','--stdio'], cwd=directory, env=env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0) as process:
            reader = threading.Thread(target=read, args=(process.stdout,), daemon=True)
            reader.start()

            def send(body):
                process.stdin.write((json.dumps(body)+'\n').encode())
                process.stdin.flush()

            def receive(identity):
                while response := incoming.get(timeout=8):
                    if response.get('id') == identity:
                        return response.get('result') or {}
                return {}

            try:
                send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'assistant-capacity','version':'1'}}})
                if not receive(1):
                    return
                send({'method':'initialized'})
                send({'id':2,'method':'account/rateLimits/read'})
                result = receive(2)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                reader.join(timeout=1)
    limits = (result.get('rateLimitsByLimitId') or {}).get('codex') or result.get('rateLimits')
    if not limits:
        return
    mapped = {'limit_id': 'codex', 'plan_type': limits.get('planType'),
              'rate_limit_reached_type': limits.get('rateLimitReachedType')}
    for name in ('primary', 'secondary'):
        value = limits.get(name)
        if value:
            mapped[name] = {'window_minutes': value.get('windowDurationMins'),
                            'used_percent': value.get('usedPercent'), 'resets_at': value.get('resetsAt')}
    save_reading(codex_cache(config), {'stamp': datetime.now(timezone.utc).isoformat(), 'limits': mapped})


def codex(config,now):
    newest={}
    for path in recent_rollouts(codex_home(config)):
        for key,(stamp,limits) in latest_limits(path).items():
            if key not in newest or (stamp or '')>(newest[key][0] or ''):newest[key]=(stamp,limits)
    stamp,limits=newest.get('codex',(None,None))
    if config.get('orchestrator_dir'):
        path = codex_cache(config)
        if path.is_file():
            cached = json.loads(path.read_text(encoding='utf-8'))
            if cached['stamp'].replace('+00:00','Z') > (stamp or '').replace('+00:00','Z'):
                stamp,limits = cached['stamp'],cached['limits']
    if not limits:return {'available':False,'note':'No recent Codex rate-limit record was found.'}
    result={}
    for name in ('primary','secondary'):
        value=limits.get(name)
        if value:result[WINDOWS.get(value.get('window_minutes'),name)]=window(value.get('used_percent'),value.get('resets_at'),now)
    observed=datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp() if stamp else None
    return {'available':True,**result,'plan':limits.get('plan_type'),'limit_reached':limits.get('rate_limit_reached_type'),
            'observed_minutes_ago':None if observed is None else round((now-observed)/60)}


def claude_record(event,now):
    """Cacheable figures from a headless Claude rate_limit_event."""
    info=event.get('rate_limit_info') or {}
    return {'observed_at':now,'status':info.get('status'),'type':info.get('rateLimitType'),'resets_at':info.get('resetsAt'),
            'windows':{k:{'utilization':v.get('utilization'),'resets_at':v.get('resetsAt')} for k,v in (info.get('unifiedWindows') or {}).items()}}


def save_claude(config,events,now=None):
    """Called by the Claude worker with its parsed stream; keeps only the newest limit event."""
    now=now or datetime.now(timezone.utc).timestamp()
    latest=[e for e in events if e.get('type')=='rate_limit_event']
    if not latest:return
    save_reading(claude_cache(config), claude_record(latest[-1],now))


def save_reading(path, record):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',suffix='.new',delete=False) as stream:
        temporary=Path(stream.name);json.dump(record,stream)
    try:temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def refresh_claude(config):
    """Minimal Haiku call whose only purpose is a fresh rate_limit_event. Runs in the background."""
    if not _refreshing.acquire(blocking=False):return
    try:
        executable=claude_executable(config)
        if not executable:return
        marker=claude_cache(config).with_name('claude-capacity.attempt')
        marker.parent.mkdir(parents=True,exist_ok=True);marker.write_text(str(datetime.now(timezone.utc).timestamp()),encoding='utf-8')
        environment={k:v for k,v in os.environ.items() if k!='ANTHROPIC_API_KEY' and not k.startswith(('ASSISTANT_','CLAUDECODE','CLAUDE_CODE_'))}
        with tempfile.TemporaryDirectory() as directory:
            done=subprocess.run([executable,'-p','--output-format','stream-json','--verbose','--model','haiku','--effort','low',
                                 '--max-turns','1','--no-session-persistence','--strict-mcp-config'],input=b'Reply with exactly: OK',
                                capture_output=True,cwd=directory,env=environment,timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        parsed=[]
        for line in done.stdout.decode('utf-8',errors='replace').splitlines():
            try:parsed.append(json.loads(line))
            except ValueError:pass
        save_claude(config,parsed)
    except Exception:
        pass # telemetry only
    finally:
        _refreshing.release()


def claude(config,now,refresh=True):
    if not claude_executable(config):return {'available':False,'note':'Claude Code is not installed for the worker.'}
    cache=claude_cache(config)
    record=json.loads(cache.read_text(encoding='utf-8')) if cache.is_file() else None
    marker=cache.with_name('claude-capacity.attempt')
    attempted=float(marker.read_text(encoding='utf-8')) if marker.is_file() else 0
    if refresh and (record is None or now-record['observed_at']>STALE) and now-attempted>STALE/2:
        threading.Thread(target=refresh_claude,args=(config,),name='claude-capacity',daemon=True).start()
    if record is None:return {'available':False,'note':'No Claude limit figures yet; a background check was started.'}
    names={'five_hour':'five_hour','seven_day':'weekly'}
    result={names.get(k,k):window(None if v.get('utilization') is None else round(v['utilization']*100,1),v.get('resets_at'),now) for k,v in record['windows'].items()}
    rejected = record.get('status') not in (None, 'allowed', 'allowed_warning')
    if rejected and record.get('resets_at') is not None:
        name = names.get(record.get('type'), record.get('type')) or 'reported_limit'
        result.setdefault(name, window(100.0, record['resets_at'], now))
    return {'available':True,**result,'limit_reached':(record.get('type') or record.get('status')) if rejected else None,
            'observed_minutes_ago':round((now-record['observed_at'])/60)}


# Phrases the CLIs print when the subscription allowance (not the request) is the problem.
LIMIT_MARKERS=('usage limit','usage_limit','rate limit','rate_limit','too many requests','quota','out of credits')


def limited(text):
    text=str(text or '').lower().replace('’',"'")
    return any(marker in text for marker in LIMIT_MARKERS)


def exhausted(reading):
    """True when a capacity reading shows no allowance left in any window (windows that reset since count as free)."""
    if not reading or not reading.get('available'):return False
    windows=[v for v in reading.values() if isinstance(v,dict)]
    # A provider may reject a run without publishing a reset. Retry after the
    # same bounded cooldown used for a CLI limit error with no telemetry.
    recent = (reading.get('observed_minutes_ago') or 0) < 30
    if any(w.get('remaining_percent') is not None and w['remaining_percent']<=0
           and (w.get('resets_at') or recent) for w in windows):
        return True
    return recent and bool(reading.get('limit_reached')) and not any(w.get('reset_since_observed') for w in windows)


def exhausted_until(reading):
    """Latest known reset among windows that currently block this account."""
    if not exhausted(reading):
        return None
    return max(
        (datetime.fromisoformat(value['resets_at']).timestamp() for value in reading.values()
         if isinstance(value, dict) and value.get('remaining_percent') == 0 and value.get('resets_at')),
        default=None,
    )


def codex_limited(history,stderr=''):
    """A failed Codex exec run hit the usage limit. Only error events and stderr count, never answer text."""
    errors=[str(e.get('message') or (e.get('error') or {}).get('message') or '') for e in history if e.get('type') in ('error','turn.failed')]
    return limited('\n'.join(errors)+'\n'+str(stderr or ''))


def claude_limited(history,stderr=''):
    """A failed headless Claude run hit the usage limit: a rejected rate_limit_event, HTTP 429 or a limit error."""
    if any(e.get('type')=='rate_limit_event' and (e.get('rate_limit_info') or {}).get('status')=='rejected' for e in history):return True
    final=[e for e in history if e.get('type')=='result']
    last=final[-1] if final else {}
    if not last.get('is_error') and final:return False
    if last.get('api_error_status')==429:return True
    return limited('\n'.join([str(last.get('result') or ''),*map(str,last.get('errors') or []),str(stderr or '')]))


def snapshot(config,now=None,refresh=None):
    """Compact, model-readable capacity summary per agent. Never raises: dispatch must not fail on telemetry."""
    now=now or datetime.now(timezone.utc).timestamp()
    # Background Claude checks spend a little allowance, so only the live worker config enables them.
    if refresh is None:refresh=bool(config.get('claude_capacity_refresh'))
    result={'note':'Account-wide allowance. Codex limits are shared by Luna, Sol and Astra; Claude limits by all Claude models.'}
    for name,read in (('codex',codex),('claude',claude)):
        try:result[name]=read(config,now,refresh) if name=='claude' else read(config,now)
        except Exception as error:result[name]={'available':False,'note':'Capacity could not be read ('+type(error).__name__+').'}
    return result
