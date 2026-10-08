"""Agent prompts are always submitted to the durable cloud inbox."""
import json
from pathlib import Path
import time
import uuid
import re
from datetime import datetime,timezone
from personal_assistant.worker.runtime import RelayClient


def submit(prompt,workspace=None,request_id=None,config_path=None,wait=False,timeout=1200):
    config_path=Path(config_path or Path.home()/'.personal-assistant/worker/config.json')
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    client=RelayClient(config['relay_url'],config['submit_token_file'])
    payload={'id':request_id or str(uuid.uuid4()),'prompt':prompt,'timezone':config.get('timezone','Europe/Berlin'),
             'created_at':datetime.now(timezone.utc).isoformat(),'workspace':str(workspace) if workspace else None}
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',payload['id']): raise ValueError('Invalid agent prompt ID')
    # Preserve the exact envelope for retries, including its original timestamp.
    runtime=Path(config.get('agent_runtime_dir',Path.home()/'.personal-assistant/agents'))
    runtime.mkdir(parents=True,exist_ok=True)
    pending=runtime/('submission-'+payload['id']+'.json')
    if pending.is_file():
        original=json.loads(pending.read_text(encoding='utf-8'))
        if original['prompt']!=prompt or original.get('workspace')!=payload['workspace']:
            raise ValueError('This submission ID already has different content')
        payload=original
    else:
        from .runtime import write_json
        write_json(pending,payload)
    acknowledgement=client.call('/v1/agent/prompts',payload)
    if not wait: return acknowledgement
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        job=client.call('/v1/agent/prompts/'+payload['id'])
        if job['state'] not in ('queued','running'): return job
        time.sleep(2)
    return {'job':client.call('/v1/agent/prompts/'+payload['id']),'wait_timed_out':True}
