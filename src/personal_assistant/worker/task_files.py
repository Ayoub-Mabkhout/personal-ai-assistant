"""Return an explicitly selected deliverable inside its task conversation."""
import base64
import hashlib
import json
import mimetypes
from pathlib import Path
import re

from .send_file import client_from_config, digest
from .runtime import TransportError


def attach(config, task, path, name=None, client=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',task):raise ValueError('A valid task ID is required.')
    path=Path(path).resolve()
    if not path.is_file():raise ValueError('Choose a deliverable file, not a directory.')
    name=name or path.name
    if len(name.encode('utf-8'))>160:raise ValueError('Choose a shorter display file name (160 UTF-8 bytes maximum).')
    size=path.stat().st_size
    if size>25*1024*1024:raise ValueError('Task response files can be up to 25 MiB each.')
    sha=digest(path)
    identifier='reply-'+hashlib.sha256(json.dumps([task,name,sha]).encode()).hexdigest()[:48]
    manifest={'name':name,'size':size,'sha256':sha,'mime':mimetypes.guess_type(name)[0] or 'application/octet-stream'}
    headers={'X-Attachment-Manifest':base64.b64encode(json.dumps(manifest,ensure_ascii=False).encode()).decode()}
    client=client or client_from_config(config)
    try:existing=client.call('/v1/agent/attachments/'+identifier)
    except TransportError as error:
        if error.status!=404:raise
    else:
        if any(existing.get(k)!=v for k,v in manifest.items()):raise ValueError('Stored task file metadata differs.')
        return {**existing,'task_id':task,'created':False}
    with path.open('rb') as source:
        result=client.upload('/v1/agent/tasks/'+task+'/attachments/'+identifier,source,size,headers)
    return result
