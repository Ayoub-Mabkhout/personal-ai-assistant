"""Configure the prepared Home Assistant server as root; no credentials printed."""
import json
from pathlib import Path
import subprocess
import sys
import time

from onboard_homeassistant import request, CLIENT

credentials = json.loads(Path('/opt/personal-assistant/secrets/homeassistant-owner.json').read_text())
tokens = request('/auth/token', {'grant_type': 'refresh_token',
    'refresh_token': credentials['refresh_token'], 'client_id': CLIENT}, form=True)
token = tokens['access_token']
if not any(state['entity_id'] == 'conversation.assistant_dispatch'
           for state in request('/api/states', token=token)):
    raise RuntimeError('Load assistant_dispatch before configuring the voice pipeline.')
storage = Path('/opt/personal-assistant/data/homeassistant/.storage/core.config_entries')
entries = json.loads(storage.read_text())['data']['entries'] if storage.exists() else []
hosts = {x['data'].get('host') for x in entries if x['domain'] == 'wyoming'}
for host, port in [('whisper', 10300), ('piper', 10200)]:
    if host in hosts:
        continue
    flow = request('/api/config/config_entries/flow', {'handler': 'wyoming',
        'show_advanced_options': False}, token)
    result = request('/api/config/config_entries/flow/' + flow['flow_id'],
        {'host': host, 'port': port}, token)
    if result['type'] != 'create_entry':
        raise RuntimeError('Wyoming connection failed: ' + json.dumps(result.get('errors')))
    print(json.dumps({'wyoming_added': host}), flush=True)
for _ in range(30):
    states = request('/api/states', token=token)
    registry_path = Path('/opt/personal-assistant/data/homeassistant/.storage/core.entity_registry')
    registry = json.loads(registry_path.read_text())['data']['entities'] if registry_path.exists() else []
    active = {x['entity_id'] for x in states}
    stt = [x['entity_id'] for x in registry if x['platform'] == 'wyoming'
           and x['entity_id'].startswith('stt.') and x['entity_id'] in active]
    tts = [x['entity_id'] for x in registry if x['platform'] == 'wyoming'
           and x['entity_id'].startswith('tts.') and x['entity_id'] in active]
    if len(stt) == len(tts) == 1:
        break
    time.sleep(1)
else:
    print(json.dumps({'speech_entities': [x['entity_id'] for x in states
        if x['entity_id'].startswith(('stt.', 'tts.'))], 'wyoming_stt': stt, 'wyoming_tts': tts}))
    raise RuntimeError('Expected one Wyoming STT and one Wyoming TTS provider.')

inner = '''import asyncio,json,aiohttp
async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('http://127.0.0.1:8123/api/websocket') as ws:
            assert (await ws.receive_json())['type'] == 'auth_required'
            await ws.send_json({'type':'auth','access_token':TOKEN})
            assert (await ws.receive_json())['type'] == 'auth_ok'
            counter = 0
            async def call(payload):
                nonlocal counter
                counter += 1
                await ws.send_json(dict(payload,id=counter))
                while True:
                    result = await ws.receive_json()
                    if result.get('id') == counter and result['type'] == 'result':
                        if not result['success']:
                            raise RuntimeError(json.dumps(result.get('error')))
                        return result.get('result')
            pipelines = await call({'type':'assist_pipeline/pipeline/list'})
            native_engine = 'conversation.assistant_dispatch'
            existing = [x for x in pipelines['pipelines'] if x['name'] == 'Personal assistant']
            if existing:
                settings = {k:v for k,v in existing[0].items() if k != 'id'}
                settings['conversation_engine'] = native_engine
                settings['prefer_local_intents'] = False
                pipeline = await call(dict(settings,type='assist_pipeline/pipeline/update',
                    pipeline_id=existing[0]['id']))
            else:
                pipeline = await call({'type':'assist_pipeline/pipeline/create',
                    'name':'Personal assistant','language':'en',
                    'conversation_engine':native_engine,'conversation_language':'en',
                    'stt_engine':STT,'stt_language':'en',
                    'tts_engine':TTS,'tts_language':'en_US',
                    'tts_voice':'en_US-lessac-medium',
                    'wake_word_entity':None,'wake_word_id':None,
                    'prefer_local_intents':False})
            await call({'type':'assist_pipeline/pipeline/set_preferred','pipeline_id':pipeline['id']})
            print(json.dumps({'voice_pipeline':pipeline,'websocket_auth_verified':True}))
asyncio.run(main())
'''
inner = ('TOKEN=' + repr(token) + '\nSTT=' + repr(stt[0]) + '\nTTS=' + repr(tts[0]) + '\n' + inner)
subprocess.run(['docker', 'exec', '-i', 'personal-assistant-homeassistant-1', 'python3', '-'],
    input=inner.encode(), check=True)
from configure_homeassistant_dispatch import configure
configure()
