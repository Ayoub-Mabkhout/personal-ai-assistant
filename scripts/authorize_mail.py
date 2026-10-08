"""Interactive OAuth PKCE setup, invoked only when the owner is ready to sign in.

No password is read by this program. Authorization codes/tokens are never logged.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import urllib.parse
import urllib.request
import webbrowser
from personal_assistant.worker.runtime import NoRedirect


def authorize(provider,client_config,output,expected_email,port=8768):
    output=Path(output).resolve()
    source=Path(__file__).resolve().parents[1]
    if output.is_relative_to(source) or 'onedrive' in str(output).casefold():
        raise ValueError('Credentials must remain outside the repository and OneDrive.')
    if output.exists():
        raise ValueError('Existing credentials preserved. Choose a new file before authorizing.')
    config=json.loads(Path(client_config).read_text())
    config=config.get('installed',config)
    verifier=secrets.token_urlsafe(64)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    state=secrets.token_urlsafe(32)
    redirect=f'http://localhost:{port}/callback'
    if provider=='gmail':
        endpoint='https://accounts.google.com/o/oauth2/v2/auth'
        token_endpoint='https://oauth2.googleapis.com/token'
        scopes='https://www.googleapis.com/auth/gmail.readonly'
    else:
        tenant=config.get('tenant','common')
        if not re.fullmatch(r'common|consumers|organizations|[a-fA-F0-9-]{36}',tenant):
            raise ValueError('Invalid Microsoft tenant')
        endpoint=f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize'
        token_endpoint=f'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'
        scopes='offline_access https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read'
    parameters={'client_id':config['client_id'],'redirect_uri':redirect,'response_type':'code',
        'scope':scopes,'state':state,'code_challenge':challenge,'code_challenge_method':'S256',
        'login_hint':expected_email}
    if provider=='gmail':
        parameters.update(access_type='offline',prompt='consent')
    result={}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            parsed=urllib.parse.urlsplit(self.path)
            query=urllib.parse.parse_qs(parsed.query)
            valid=parsed.path=='/callback' and secrets.compare_digest(query.get('state',[''])[0],state)
            if valid:
                if 'code' in query:
                    result['code']=query['code'][0]
                elif 'error' in query:
                    result['error']=query['error'][0]
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'Authorization received. Return to your assistant.' if valid else b'Unexpected callback rejected.')
    with HTTPServer(('127.0.0.1',port),Callback) as server:
        server.timeout=1
        url=endpoint+'?'+urllib.parse.urlencode(parameters)
        webbrowser.open(url)
        print(json.dumps({'status':'Waiting for your provider sign-in and read-only consent','authorization_url':url}),flush=True)
        deadline=time.monotonic()+480
        while not result and time.monotonic()<deadline:
            server.handle_request()
    if not result.get('code'):
        raise RuntimeError('Authorization did not complete; provider error or timeout. No credentials saved.')
    body={'client_id':config['client_id'],'grant_type':'authorization_code','code':result['code'],
        'redirect_uri':redirect,'code_verifier':verifier}
    if config.get('client_secret'):
        body['client_secret']=config['client_secret']
    if provider=='outlook':
        body['scope']=scopes
    opener=urllib.request.build_opener(NoRedirect)
    request=urllib.request.Request(token_endpoint,data=urllib.parse.urlencode(body).encode(),
        headers={'Content-Type':'application/x-www-form-urlencoded'})
    with opener.open(request,timeout=30) as response:
        tokens=json.load(response)
    profile_endpoint='https://gmail.googleapis.com/gmail/v1/users/me/profile' if provider=='gmail' else 'https://graph.microsoft.com/v1.0/me?$select=id,mail,userPrincipalName'
    with opener.open(urllib.request.Request(profile_endpoint,headers={'Authorization':'Bearer '+tokens['access_token']}),timeout=30) as response:
        profile=json.load(response)
    identities=[profile.get(field,'') for field in ('emailAddress','mail','userPrincipalName')]
    if expected_email.casefold() not in [value.casefold() for value in identities if value]:
        raise ValueError('Signed-in account does not match the expected mailbox. Credentials were not saved.')
    if not tokens.get('refresh_token'):
        raise ValueError('Provider did not supply offline access. Credentials were not saved.')
    output.parent.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        user=os.environ['USERDOMAIN']+'\\'+os.environ['USERNAME']
        subprocess.run(['icacls',str(output.parent),'/inheritance:r','/grant:r',user+':(OI)(CI)F','/Q'],
            check=True,capture_output=True)
    auth={'provider':provider,'client_id':config['client_id'],'refresh_token':tokens['refresh_token'],
        'access_token':tokens['access_token'],'expires_at':time.time()+tokens['expires_in'],
        'account_email':expected_email,'scope':scopes}
    if config.get('client_secret'):
        auth['client_secret']=config['client_secret']
    if provider=='outlook':
        auth['tenant']=config.get('tenant','common')
    if output.exists():
        raise ValueError('Existing credentials preserved. Choose a new file or review before replacing them.')
    with output.open('x',encoding='utf-8') as handle:
        json.dump(auth,handle)
    if os.name!='nt':
        output.chmod(0o600)
    return {'status':'Read-only mailbox authorization saved','credential_file':str(output),'tokens_printed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider',choices=['gmail','outlook'],required=True)
    parser.add_argument('--client-config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--expected-email',required=True)
    parser.add_argument('--port',type=int,default=8768)
    args=parser.parse_args()
    print(json.dumps(authorize(args.provider,args.client_config,args.output,args.expected_email,args.port)))
