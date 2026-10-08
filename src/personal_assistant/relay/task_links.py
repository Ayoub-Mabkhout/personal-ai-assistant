"""Stable task-page access and distinct task-scoped continuation capabilities."""
import base64
import hashlib
import hmac
import os
from pathlib import Path
import secrets


class TaskLinks:
    def __init__(self,key):
        if len(key)<32: raise ValueError('Task link key must contain at least 32 bytes.')
        self.key=key

    @classmethod
    def load(cls,path):
        path=Path(path)
        if not path.exists():
            try:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as stream: stream.write(secrets.token_bytes(32))
            except FileExistsError: pass
        return cls(path.read_bytes())

    def token(self,kind,identifier):
        digest=hmac.new(self.key,('task-view-v1:'+kind+'/'+identifier).encode(),hashlib.sha256).digest()
        return 'v1.'+base64.urlsafe_b64encode(digest).decode().rstrip('=')

    def verify(self,kind,identifier,token):
        return isinstance(token,str) and len(token)<128 and hmac.compare_digest(self.token(kind,identifier).encode(),token.encode())

    def url(self,origin,kind,identifier):
        return origin.rstrip('/')+'/tasks/'+kind+'/'+identifier+'?view='+self.token(kind,identifier)

    def followup_token(self,kind,identifier):
        digest=hmac.new(self.key,('task-followup-v1:'+kind+'/'+identifier).encode(),hashlib.sha256).digest()
        return 'f1.'+base64.urlsafe_b64encode(digest).decode().rstrip('=')

    def verify_followup(self,kind,identifier,token):
        return isinstance(token,str) and len(token)<128 and hmac.compare_digest(self.followup_token(kind,identifier).encode(),token.encode())
