"""Route every native Assist pipeline through the configured Luna dispatcher.

Run as root on the prepared server. Credentials stay in private server files;
the original pipeline configuration is backed up before API updates.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from onboard_homeassistant import request, CLIENT


def configure():
    owner = json.loads(Path('/opt/personal-assistant/secrets/homeassistant-owner.json').read_text())
    token = request('/auth/token', {'grant_type': 'refresh_token',
                    'refresh_token': owner['refresh_token'], 'client_id': CLIENT}, form=True)['access_token']
    if not any(state['entity_id'] == 'conversation.assistant_dispatch'
               for state in request('/api/states', token=token)):
        raise RuntimeError('Assistant dispatch entity must be loaded before configuring pipelines.')
    inner = '''import asyncio,json,sys,aiohttp
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,'/source/scripts')
from assist_pipeline_config import dispatch_updates
token=json.load(sys.stdin)['token']
async def main():
 async with aiohttp.ClientSession() as session:
  async with session.ws_connect('http://127.0.0.1:8123/api/websocket') as ws:
   await ws.receive_json();await ws.send_json({'type':'auth','access_token':token})
   assert (await ws.receive_json())['type']=='auth_ok'
   counter=0
   async def call(payload):
    nonlocal counter
    counter+=1;await ws.send_json(dict(payload,id=counter))
    while True:
     result=await ws.receive_json()
     if result.get('id')==counter and result['type']=='result':
      if not result['success']:raise RuntimeError(str(result.get('error')))
      return result.get('result')
   before=await call({'type':'assist_pipeline/pipeline/list'})
   updates=dispatch_updates(before['pipelines'])
   if updates:
    backup=Path('/config')/('assist-pipelines.pre-dispatch-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.json')
    backup.write_text(json.dumps(before,indent=2));backup.chmod(0o600)
   for update in updates:await call(update)
   after=await call({'type':'assist_pipeline/pipeline/list'})
   assert not dispatch_updates(after['pipelines'])
   print(json.dumps({'updated_pipeline_ids':[p['pipeline_id'] for p in updates],
                     'pipelines':after['pipelines'],'preferred_pipeline':after['preferred_pipeline']}))
asyncio.run(main())
'''
    # Only reusable source is placed in the container; token travels via stdin.
    subprocess.run(['docker', 'exec', 'personal-assistant-homeassistant-1', 'mkdir', '-p', '/source/scripts'], check=True)
    subprocess.run(['docker', 'cp', str(Path(__file__).with_name('assist_pipeline_config.py')),
                    'personal-assistant-homeassistant-1:/source/scripts/assist_pipeline_config.py'], check=True)
    subprocess.run(['docker', 'exec', '-i', 'personal-assistant-homeassistant-1', 'python', '-c', inner],
                   input=json.dumps({'token': token}).encode(), check=True)


if __name__ == '__main__':
    configure()
