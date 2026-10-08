"""Configure the prepared Home Assistant server as root; no credentials printed."""
import json
from pathlib import Path
import subprocess
import sys
from onboard_homeassistant import request, CLIENT
credentials = json.loads(Path('/opt/personal-assistant/secrets/homeassistant-owner.json').read_text())
token = request('/auth/token', {'grant_type': 'refresh_token',
    'refresh_token': credentials['refresh_token'], 'client_id': CLIENT}, form=True)['access_token']
inner = '''import asyncio,json,aiohttp
async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('http://127.0.0.1:8123/api/websocket') as ws:
            assert (await ws.receive_json())['type'] == 'auth_required'
            await ws.send_json({'type':'auth','access_token':TOKEN})
            assert (await ws.receive_json())['type'] == 'auth_ok'
            headers = {'Authorization':'Bearer ' + TOKEN}
            async with session.get('http://127.0.0.1:8123/api/config/config_entries/entry',headers=headers) as response:
                entries = await response.json()
            if not any(x['domain'] == 'shopping_list' for x in entries):
                await ws.send_json({'id':1,'type':'config_entries/flow/progress'})
                flows = (await ws.receive_json())['result']
                pending = [x for x in flows if x['handler'] == 'shopping_list']
                if pending:
                    assert len(pending) == 1
                    flow = pending[0]
                else:
                    async with session.post('http://127.0.0.1:8123/api/config/config_entries/flow',headers=headers,
                        json={'handler':'shopping_list'}) as response:
                        flow = await response.json()
                async with session.post('http://127.0.0.1:8123/api/config/config_entries/flow/' + flow['flow_id'],
                    headers=headers,json={}) as response:
                    result = await response.json()
                assert result['type'] == 'create_entry', result.get('reason')
            print(json.dumps({'shopping_list_configured':True}),flush=True)
            await ws.send_json({'id':2,'type':'http/config'})
            current = (await ws.receive_json())['result']
            stable = current['stable']
            if current['pending'] is None and stable.get('use_x_forwarded_for') and stable.get('trusted_proxies') == ['172.30.0.2/32']:
                print(json.dumps({'http_configuration_stable':True}))
                return
            await ws.send_json({'id':3,'type':'http/config/configure','config':{
                'server_port':8123,'use_x_forwarded_for':True,
                'trusted_proxies':['172.30.0.2/32'],'ip_ban_enabled':True,
                'login_attempts_threshold':5}})
            result = await ws.receive_json()
            assert result['success'], result.get('error')
            print(json.dumps({'http_configuration_staged':True,'result':result['result']}))
asyncio.run(main())
'''
subprocess.run(['docker','exec','-i','personal-assistant-homeassistant-1','python3','-'],
    input=('TOKEN=' + repr(token) + '\n' + inner).encode(), check=True)
