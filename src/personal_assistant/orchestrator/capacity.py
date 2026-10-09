"""Agent capacity snapshot for dispatch decisions, read from local Codex session logs.

Every Codex turn records the account's current rate-limit windows in its session
rollout. Reading the newest record costs no model call, so each dispatcher turn can
see how much of the five-hour and weekly allowance is left without checking itself.
"""
from datetime import datetime,timezone
import json
import os
from pathlib import Path

WINDOWS={300:'five_hour',10080:'weekly'}
TAIL=256*1024 # rate-limit records are near the end of a rollout; avoid reading whole logs


def codex_home(config):
    return Path(config.get('codex_home') or os.environ.get('CODEX_HOME') or Path.home()/'.codex')


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


def window(value,now):
    if not value:return None
    resets=value.get('resets_at')
    used=value.get('used_percent')
    # A window that reset after the record was written starts again from zero.
    reset=resets is not None and resets<=now
    return {'used_percent':0.0 if reset else used,'remaining_percent':100.0 if reset else (None if used is None else round(100-used,1)),
            'resets_in_minutes':None if resets is None or reset else round((resets-now)/60),
            'resets_at':None if resets is None else datetime.fromtimestamp(resets,timezone.utc).isoformat(),
            **({'reset_since_observed':True} if reset else {})}


def snapshot(config,now=None):
    """Compact, model-readable capacity summary. Never raises: dispatch must not fail on telemetry."""
    now=now or datetime.now(timezone.utc).timestamp()
    try:
        newest={}
        for path in recent_rollouts(codex_home(config)):
            for key,(stamp,limits) in latest_limits(path).items():
                if key not in newest or (stamp or '')>(newest[key][0] or ''):newest[key]=(stamp,limits)
        result={}
        for key,(stamp,limits) in newest.items():
            windows={WINDOWS.get((limits.get(name) or {}).get('window_minutes'),name):window(limits.get(name),now) for name in ('primary','secondary') if limits.get(name)}
            if not windows and not limits.get('rate_limit_reached_type'):continue # placeholder records carry no figures
            observed=datetime.fromisoformat(stamp.replace('Z','+00:00')) if stamp else None
            result[key]={**windows,'plan':limits.get('plan_type'),'limit_reached':limits.get('rate_limit_reached_type'),
                         'observed_minutes_ago':None if observed is None else round((now-observed.timestamp())/60)}
        if not result:return {'available':False,'note':'No recent Codex rate-limit record was found.'}
        return {'available':True,'source':'local Codex session logs (account-wide; shared by Luna, Sol and Astra)','limits':result}
    except Exception as error:
        return {'available':False,'note':'Capacity could not be read ('+type(error).__name__+').'}
