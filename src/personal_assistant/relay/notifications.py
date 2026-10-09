"""Cloud-owned durable task notifications. HA acceptance is not handset receipt."""
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


ACTIVE={'queued','running'}
# Home Assistant tints the card and swaps its status-bar icon; the native Companion ignores these keys.
COLOR='#7B58E8'
ICONS={'queued':'mdi:clock-outline','running':'mdi:progress-clock','completed':'mdi:check-circle-outline',
    'failed':'mdi:alert-circle-outline','needs_input':'mdi:message-question-outline','cancelled':'mdi:cancel','expired':'mdi:clock-alert-outline'}
TITLES={'queued':'Task queued','running':'Task in progress','completed':'Task completed',
    'failed':'Task failed','needs_input':'Task needs your input','cancelled':'Task cancelled','expired':'Task expired'}


def notification(kind,job,connection,public_url,visibility='private',task_links=None):
    state=job['state'];short=job['id'][-8:]
    request=' '.join(job['payload']['command'].split())[:160]
    if state=='queued':
        if connection['laptop']=='unavailable': status='Laptop offline. Saved on the server; waiting for it to reconnect.'
        elif connection['laptop']=='blocked': status='Laptop cannot run tasks right now. Saved on the server and waiting.'
        else: status='Acknowledged and saved on the server. Waiting to start.'
    elif state=='running': status='Laptop disconnected. Waiting to reconcile progress when it reconnects.' if connection['laptop']=='unavailable' else 'The laptop is working on this task.'
    else: status=(job.get('result') or {}).get('summary') or TITLES[state]+'.'
    page_id=(job['payload'].get('resume_task') or {}).get('root_id',job['id'])
    link=task_links.url(public_url,kind,page_id) if task_links else public_url.rstrip('/')+'/tasks/'+kind+'/'+page_id
    title='Task connection interrupted' if state=='running' and connection['laptop']=='unavailable' else TITLES[state]
    from .replies import reply_action
    return {'title':title+' · '+short,'message':request+'\n\n'+str(status)[:1800],
        'data':{'tag':'assistant-'+kind+'-'+job['id'],'group':'assistant-tasks','channel':'Assistant tasks',
            'persistent':state in ACTIVE,'sticky':state in ACTIVE,'alert_once':state in ACTIVE,
            'visibility':visibility,'priority':'high','ttl':86400,'clickAction':link,'color':COLOR,'notification_icon':ICONS[state],
            'progress_indeterminate':state=='running','progress':0 if state=='running' else -1,
            'actions':[{'action':'URI','title':'Details','uri':link},
                {'action':reply_action(kind,job['id']),'title':'Reply','behavior':'textInput'}]}}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


class HomeAssistantPush:
    def __init__(self,config):
        self.base=config['ha_url'].rstrip('/');parsed=urllib.parse.urlsplit(self.base)
        if (parsed.scheme!='https' and self.base!='http://homeassistant:8123') or parsed.username or parsed.password or parsed.path:
            raise ValueError('Invalid Home Assistant origin.')
        self.service=config['mobile_service']
        if not re.fullmatch(r'mobile_app_[a-z0-9_]+',self.service): raise ValueError('Select one Companion notification service.')
        self.auth_file=Path(config['auth_file']);self.token=None;self.expires=0
        self.opener=urllib.request.build_opener(NoRedirect)

    def call(self,path,payload,authenticated=True):
        if authenticated and time.monotonic()>=self.expires:
            auth=json.loads(self.auth_file.read_text(encoding='utf-8-sig'))
            fresh=self.call('/auth/token',{'grant_type':'refresh_token','refresh_token':auth['refresh_token'],'client_id':auth['client_id']},False)
            self.token=fresh['access_token'];self.expires=time.monotonic()+fresh['expires_in']-60
        body=json.dumps(payload).encode() if authenticated else urllib.parse.urlencode(payload).encode()
        headers={'Content-Type':'application/json' if authenticated else 'application/x-www-form-urlencoded'}
        if authenticated: headers['Authorization']='Bearer '+self.token
        try:
            with self.opener.open(urllib.request.Request(self.base+path,data=body,headers=headers),timeout=10) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code==401: self.expires=0
            raise

    def __call__(self,payload):
        self.call('/api/services/notify/'+self.service,payload)


class NotificationPump:
    def __init__(self,queues,sender,public_url,interval=2,visibility='private',task_links=None,max_age=None):
        self.queues=queues;self.sender=sender;self.public_url=public_url;self.interval=interval;self.max_age=max_age
        parsed=urllib.parse.urlsplit(public_url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
            raise ValueError('Task links require the public HTTPS origin.')
        self.stop=threading.Event();self.thread=None
        if visibility not in ('private','public','secret'): raise ValueError('Invalid notification visibility.')
        self.visibility=visibility
        self.task_links=task_links

    def tick(self):
        for kind,queue in self.queues.items():
            connection=queue.status()
            for row in queue.notification_rows():
                if row['next_attempt']>queue.clock(): continue
                job=queue.get(row['job_id'])
                # A final state that waited this long for a recipient is history, not news for a newly paired phone.
                if self.max_age and job['state'] not in ACTIVE and row['revision']!=row['delivered_revision'] and queue.clock()-(row['changed'] or queue.clock())>self.max_age:
                    queue.notification_expired(job['id'],row['revision']);continue
                payload=notification(kind,job,connection,self.public_url,self.visibility,self.task_links)
                encoded=json.dumps(payload,sort_keys=True)
                namespace=getattr(self.sender,'fingerprint_namespace','')
                fingerprint=hashlib.sha256((namespace+encoded).encode()).hexdigest()
                if row['delivered_revision']==row['revision'] and row['fingerprint']==fingerprint: continue
                try:
                    # An explicit refresh must reach the phone even when nothing changed; once delivered, later changes are ordinary updates.
                    if row['cause']=='notification_requested' and row['delivered_revision']!=row['revision'] and hasattr(self.sender,'renotify'): self.sender.renotify(payload,row['revision'])
                    else: self.sender(payload)
                except Exception as error:
                    queue.notification_failed(job['id'],row['revision'],type(error).__name__)
                    logging.warning('Task push failed (%s); retry saved.',type(error).__name__)
                else: queue.notification_accepted(job['id'],row['revision'],fingerprint)

    def run(self):
        while not self.stop.is_set():
            try: self.tick()
            except Exception as error: logging.warning('Task notification poll failed (%s).',type(error).__name__)
            self.stop.wait(self.interval)

    def start(self):
        self.thread=threading.Thread(target=self.run,name='phone-task-notifications',daemon=True);self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=12)
