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


def codex(config,now):
    newest={}
    for path in recent_rollouts(codex_home(config)):
        for key,(stamp,limits) in latest_limits(path).items():
            if key not in newest or (stamp or '')>(newest[key][0] or ''):newest[key]=(stamp,limits)
    stamp,limits=newest.get('codex',(None,None))
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
    return {'observed_at':now,'status':info.get('status'),'type':info.get('rateLimitType'),
            'windows':{k:{'utilization':v.get('utilization'),'resets_at':v.get('resetsAt')} for k,v in (info.get('unifiedWindows') or {}).items()}}


def save_claude(config,events,now=None):
    """Called by the Claude worker with its parsed stream; keeps only the newest limit event."""
    now=now or datetime.now(timezone.utc).timestamp()
    latest=[e for e in events if e.get('type')=='rate_limit_event']
    if not latest:return
    path=claude_cache(config);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.new');temporary.write_text(json.dumps(claude_record(latest[-1],now)),encoding='utf-8');temporary.replace(path)


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
    return {'available':True,**result,'limit_reached':None if record.get('status') in (None,'allowed','allowed_warning') else record.get('type') or record.get('status'),
            'observed_minutes_ago':round((now-record['observed_at'])/60)}


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
