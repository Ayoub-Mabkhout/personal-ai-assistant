"""Verify public authenticated HTTPS/WebSocket before confirming HTTP settings.

Run as root on the prepared Linux server after publishing the proxy. The public
hostname is read from the private deployment environment, never from user input.
"""
import json
from pathlib import Path
import subprocess
import time

from onboard_homeassistant import request, CLIENT

directory = Path('/opt/personal-assistant')
settings = dict(line.split('=', 1) for line in (directory / '.env').read_text().splitlines()
    if line and not line.startswith('#'))
base = 'https://' + settings['ASSISTANT_DOMAIN']
credentials = json.loads((directory / 'secrets/homeassistant-owner.json').read_text())
for attempt in range(60):
    try:
        token = request('/auth/token', {'grant_type': 'refresh_token',
            'refresh_token': credentials['refresh_token'], 'client_id': CLIENT}, form=True)['access_token']
        break
    except OSError:
        if attempt == 59:
            raise
        time.sleep(2)

inner = '''import asyncio,json,aiohttp
async def main():
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        async with session.get(BASE) as response:
            assert response.status == 200
        async with session.ws_connect(BASE + '/api/websocket',origin=BASE) as ws:
            assert (await ws.receive_json())['type'] == 'auth_required'
            await ws.send_json({'type':'auth','access_token':TOKEN})
            assert (await ws.receive_json())['type'] == 'auth_ok'
            async def call(number,payload):
                await ws.send_json(dict(payload,id=number))
                result=await ws.receive_json()
                assert result.get('id') == number and result['success'],result.get('error')
                return result['result']
            http=await call(1,{'type':'http/config'})
            if http['active_config_type'] == 'pending':
                assert http['pending']['trusted_proxies'] == ['172.30.0.2/32']
                await call(2,{'type':'http/config/promote'})
            http=await call(3,{'type':'http/config'})
            assert http['pending'] is None and http['stable']['use_x_forwarded_for']
            assert http['stable']['trusted_proxies'] == ['172.30.0.2/32']
            pipeline=await call(4,{'type':'assist_pipeline/pipeline/get'})
            assert pipeline['conversation_engine'] == 'conversation.home_assistant'
            assert pipeline['stt_engine'] == 'stt.faster_whisper' and pipeline['tts_engine'] == 'tts.piper'
        for path in ['/relay/v1/status','/api/']:
            async with session.get(BASE+path) as response:
                assert response.status == 401
        print(json.dumps({'authenticated_public_https':True,'public_websocket':True,
            'proxy_configuration_confirmed':True,'preferred_voice_pipeline':pipeline['name'],
            'anonymous_endpoints_rejected':True}))
asyncio.run(main())
'''
subprocess.run(['docker', 'exec', '-i', 'personal-assistant-homeassistant-1', 'python3', '-'],
    input=('TOKEN=' + repr(token) + '\nBASE=' + repr(base) + '\n' + inner).encode(), check=True)
