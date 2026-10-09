"""Phone task conversation and scoped follow-ups, with HA or signed-link access."""
import hashlib
import base64
import json
from pathlib import Path
import threading
import time
import urllib.request
from fastapi import APIRouter,Header,HTTPException,Query
from fastapi.responses import FileResponse
from .continuations import Continuations,Followup


def task_router(queues,ha_url,assets,user_verifier=None,task_links=None,mobile_settings_file=None):
    api=APIRouter(prefix='/tasks');cache={};lock=threading.Lock();continuations=Continuations(queues['agent'])
    @api.get('/v1/preferences')
    def preferences(authorization:str|None=Header(default=None)):
        authorize(authorization)
        from .mobile_settings import MobileSettings
        from fastapi.responses import JSONResponse
        value=MobileSettings(mobile_settings_file).snapshot() if mobile_settings_file else {'daylight':None}
        return JSONResponse(value,headers={'Cache-Control':'private, no-store'})
    @api.get('/v1/history')
    def history(authorization:str|None=Header(default=None),q:str=Query(default='',max_length=300),
                cursor:str|None=Query(default=None,max_length=500),limit:int=Query(default=30,ge=1,le=100)):
        authorize(authorization)
        boundary=None
        if cursor:
            try:
                boundary=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
                if (not isinstance(boundary,list) or len(boundary)!=3 or type(boundary[0]) not in (float,int)
                    or boundary[1] not in queues or not isinstance(boundary[2],str)):raise ValueError()
            except (ValueError,TypeError):raise HTTPException(422,'Invalid history cursor.') from None
        items=[]
        for kind,queue in queues.items():
            sql='''WITH conversations AS (
                SELECT COALESCE(json_extract(payload,'$.resume_task.root_id'),id) AS root,
                    MAX(updated) AS activity,MAX(rowid) AS latest,
                    MAX(CASE WHEN instr(lower(json_extract(payload,'$.command')),lower(?))>0
                        OR instr(lower(COALESCE(json_extract(result,'$.summary'),'')),lower(?))>0 THEN 1 ELSE 0 END) AS matched
                FROM jobs GROUP BY root)
                SELECT original.id,original.payload,original.created,conversation.activity,
                    latest.state,latest.result
                FROM conversations conversation JOIN jobs original ON original.id=conversation.root
                    JOIN jobs latest ON latest.rowid=conversation.latest WHERE (?='' OR matched=1)'''
            parameters=[q,q,q]
            if boundary:
                sql+=' AND (activity,?,original.id)<(?,?,?)';parameters+=[kind,*boundary]
            sql+=' ORDER BY activity DESC,original.id DESC LIMIT ?';parameters.append(limit+1)
            with queue.connection() as db:rows=db.execute(sql,parameters).fetchall()
            for row in rows:
                items.append({'id':row['id'],'kind':kind,'request':json.loads(row['payload'])['command'],
                              'state':row['state'],'summary':json.loads(row['result'] or '{}').get('summary',''),
                              'created':row['created'],'updated':row['activity'],
                              'url':'/tasks/'+kind+'/'+row['id']})
        items.sort(key=lambda item:(item['updated'],item['kind'],item['id']),reverse=True)
        more=len(items)>limit;items=items[:limit]
        next_cursor=None
        if more:
            last=items[-1];next_cursor=base64.urlsafe_b64encode(json.dumps([last['updated'],last['kind'],last['id']]).encode()).decode().rstrip('=')
        return {'items':items,'next_cursor':next_cursor}
    @api.get('/v1/{kind}/{identifier}')
    def detail(kind:str,identifier:str,authorization:str|None=Header(default=None),x_task_view:str|None=Header(default=None)):
        if kind not in queues: raise HTTPException(404)
        if task_links and x_task_view:
            if not task_links.verify(kind,identifier,x_task_view): raise HTTPException(401,'Invalid task link.')
            return result(kind,identifier)
        authorize(authorization)
        return result(kind,identifier)

    def authorize(authorization):
        if not authorization or not authorization.startswith('Bearer ') or len(authorization)>8200:
            raise HTTPException(401,'Sign in to Home Assistant.')
        token=authorization[7:];key=hashlib.sha256(token.encode()).hexdigest()
        with lock: valid=cache.get(key,0)>time.monotonic()
        if not valid:
            try:
                if user_verifier: user_verifier(token)
                else:
                    request=urllib.request.Request(ha_url.rstrip('/')+'/api/',headers={'Authorization':'Bearer '+token})
                    with urllib.request.urlopen(request,timeout=5) as response:
                        if response.status!=200: raise OSError('Login rejected')
            except OSError: raise HTTPException(401,'Home Assistant login expired.') from None
            with lock:
                if len(cache)>256: cache.clear()
                cache[key]=time.monotonic()+15

    @api.post('/v1/{kind}/{identifier}/followups')
    def followup(kind:str,identifier:str,body:Followup,authorization:str|None=Header(default=None),x_task_followup:str|None=Header(default=None)):
        if kind!='agent':raise HTTPException(422,'This task has no headless agent session.')
        if task_links and x_task_followup:
            if not task_links.verify_followup(kind,identifier,x_task_followup):raise HTTPException(401,'Invalid follow-up link.')
        else:authorize(authorization)
        job,created=continuations.accept(identifier,body)
        return {'id':job['id'],'state':job['state'],'created':created,'connection':queues['agent'].status()}

    def result(kind,identifier):
        queue=queues[kind];job=queue.get(identifier)
        turns=continuations.turns(identifier) if kind=='agent' else []
        root=continuations.root(identifier) if kind=='agent' else job
        latest=turns[-1] if turns else job
        return {'id':job['id'],'state':job['state'],'request':job['payload']['command'],
            'created':job['created'],'updated':job['updated'],'summary':(job['result'] or {}).get('summary',''),
            'connection':queue.status(),'history':[{'at':e['at'],'kind':e['kind']} for e in queue.history(identifier)
                if e['kind']!='phone_notification_accepted'],
            'root_id':root['id'],'original_request':root['payload']['command'],
            'can_followup':kind=='agent','followup_token':task_links.followup_token(kind,identifier) if task_links and kind=='agent' else None,
            'turns':[{'id':t['id'],'instruction':t['payload']['command'],'state':t['state'],
                      'summary':(t['result'] or {}).get('summary',''),'created':t['created']} for t in turns],
            'conversation_state':latest['state'],'conversation_updated':latest['updated']}

    @api.get('/')
    def index():
        return FileResponse(Path(assets)/'index.html',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'",
            'X-Content-Type-Options':'nosniff'})

    @api.get('/{kind}/{identifier}')
    def task_page(kind:str,identifier:str):
        if kind not in queues: raise HTTPException(404)
        return index()

    @api.get('/{filename}')
    def asset(filename:str):
        if filename not in ('app.js','style.css','theme.js','daylight.js'): raise HTTPException(404)
        target=Path(assets).parent/'shared'/filename if filename=='daylight.js' else Path(assets)/filename
        return FileResponse(target,headers={'Cache-Control':'no-cache','X-Content-Type-Options':'nosniff'})
    return api
