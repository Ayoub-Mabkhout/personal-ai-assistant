"""Publish a signed APK/sidecar over SSH, then invoke the durable release push hook."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from personal_assistant.worker.notifications import HomeAssistantNotifier


def publish(apk,host,key,known_hosts,config):
    apk=Path(apk);metadata=apk.with_suffix('.release.json')
    release=json.loads(metadata.read_text(encoding='utf-8'))
    if release.get('diagnostic_only'):raise ValueError('Diagnostic model APKs cannot be published to the user release feed.')
    payload=apk.read_bytes()
    if (release.get('package_name')!='com.personalassistant.companion'
        or release.get('sha256')!=hashlib.sha256(payload).hexdigest()
        or release.get('size')!=len(payload) or len(payload)>50*1024*1024):
        raise ValueError('APK and release sidecar do not match.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+',host):raise ValueError('Use user@SSH-host.')
    ssh=['ssh','-i',str(key),'-o','IdentitiesOnly=yes','-o','BatchMode=yes',
         '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known_hosts),host]
    stage='/tmp/assistant-companion-'+uuid.uuid4().hex
    def remote(command,data=None):
        result=subprocess.run([*ssh,command],input=data,capture_output=True)
        if result.returncode:raise RuntimeError('Remote publication failed: '+result.stderr.decode(errors='replace')[-1500:])
    try:
        remote('umask 077; cat > '+shlex.quote(stage+'.apk'),payload)
        remote('umask 077; cat > '+shlex.quote(stage+'.json'),metadata.read_bytes())
        # Immutable version guard runs before replacing any public artifact.
        guard="""import json,sys,pathlib
incoming=json.loads(pathlib.Path(sys.argv[1]).read_text())
old=pathlib.Path('/opt/personal-assistant/data/relay/companion.release.json')
if old.exists():
 previous=json.loads(old.read_text())
 if incoming['version_code']<previous['version_code'] or (incoming['version_code']==previous['version_code'] and incoming['sha256']!=previous['sha256']):
  raise SystemExit('Increment the version before publishing different bytes.')
"""
        remote('sudo python3 - '+shlex.quote(stage+'.json'),guard.encode())
        directory='/opt/personal-assistant/data/relay/'
        for suffix,target in (('.apk','companion.apk'),('.json','companion.release.json')):
            temporary=directory+target+'.publishing'
            remote('sudo install -o 10001 -g 10001 -m 0644 '+shlex.quote(stage+suffix)+' '+shlex.quote(temporary))
            remote('sudo mv -f '+shlex.quote(temporary)+' '+shlex.quote(directory+target))
    finally:
        remote('rm -f -- '+shlex.quote(stage+'.apk')+' '+shlex.quote(stage+'.json'))
    settings=json.loads(Path(config).read_text(encoding='utf-8-sig'))
    receipt=HomeAssistantNotifier(settings).call('/groceries/v1/mobile/release/published',
        {'version_code':release['version_code'],'sha256':release['sha256']})
    return {'version_name':release['version_name'],'size':len(payload),'publication':receipt}


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--apk',type=Path,default=ROOT/'state/exports/assistant-companion.apk')
    cli.add_argument('--host',required=True)
    cli.add_argument('--key',type=Path,required=True)
    cli.add_argument('--known-hosts',type=Path,required=True)
    cli.add_argument('--config',type=Path,default=Path.home()/'.personal-assistant/worker/config.json')
    args=cli.parse_args();print(json.dumps(publish(args.apk,args.host,args.key,args.known_hosts,args.config),indent=2))
