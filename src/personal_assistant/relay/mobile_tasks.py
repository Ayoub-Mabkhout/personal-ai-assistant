"""Paired-owner task conversations; no HA login, worker traces or admin capability."""
import base64
import json
import hashlib
from pydantic import BaseModel,ConfigDict,Field
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from .continuations import Continuations, Followup


class MobileTasks:
    def __init__(self, queues):
        self.queues = queues
        self.continuations = Continuations(queues['agent'])

    def history(self, query='', cursor=None, limit=30):
        boundary = None
        if cursor:
            try:
                boundary = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
                if (not isinstance(boundary, list) or len(boundary) != 3
                        or type(boundary[0]) not in (int, float) or boundary[1] not in self.queues
                        or not isinstance(boundary[2], str)):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError('Invalid task history cursor.') from None
        items = []
        for kind, queue in self.queues.items():
            sql = '''WITH conversations AS (
                SELECT COALESCE(json_extract(payload,'$.resume_task.root_id'),id) AS root,
                    MAX(updated) AS activity, MAX(rowid) AS latest,
                    MAX(CASE WHEN instr(lower(json_extract(payload,'$.command')),lower(?))>0
                        OR instr(lower(COALESCE(json_extract(result,'$.summary'),'')),lower(?))>0
                        THEN 1 ELSE 0 END) AS matched FROM jobs GROUP BY root)
                SELECT original.id,original.payload,original.created,conversation.activity,
                    latest.state,latest.result FROM conversations conversation
                JOIN jobs original ON original.id=conversation.root
                JOIN jobs latest ON latest.rowid=conversation.latest WHERE (?='' OR matched=1)'''
            parameters = [query, query, query]
            if boundary:
                sql += ' AND (activity,?,original.id)<(?,?,?)'
                parameters += [kind, *boundary]
            sql += ' ORDER BY activity DESC,original.id DESC LIMIT ?'
            parameters.append(limit + 1)
            with queue.connection() as db:
                rows = db.execute(sql, parameters).fetchall()
            for row in rows:
                items.append({'id': row['id'], 'kind': kind,
                              'request': json.loads(row['payload'])['command'],
                              'state': row['state'], 'summary': json.loads(row['result'] or '{}').get('summary', ''),
                              'created': row['created'], 'updated': row['activity']})
        items.sort(key=lambda item: (item['updated'], item['kind'], item['id']), reverse=True)
        more = len(items) > limit
        items = items[:limit]
        next_cursor = None
        if more:
            last = items[-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps([last['updated'], last['kind'], last['id']]).encode()).decode().rstrip('=')
        return {'items': items, 'next_cursor': next_cursor}

    def detail(self, kind, identifier):
        if kind not in self.queues:
            raise HTTPException(404, 'Task not found.')
        queue = self.queues[kind]
        job = queue.get(identifier)
        turns = self.continuations.turns(identifier) if kind == 'agent' else []
        root = self.continuations.root(identifier) if kind == 'agent' else job
        latest = turns[-1] if turns else job
        return {'id': job['id'], 'kind': kind, 'state': job['state'],
                'request': job['payload']['command'], 'created': job['created'], 'updated': job['updated'],
                'summary': (job['result'] or {}).get('summary', ''), 'connection': queue.status(),
                'history': [{'at': e['at'], 'kind': e['kind']} for e in queue.history(identifier)
                            if e['kind'] != 'phone_notification_accepted'],
                'root_id': root['id'], 'original_request': root['payload']['command'],
                'original_summary': (root['result'] or {}).get('summary', ''),
                'original_state': root['state'], 'original_updated': root['updated'],
                'can_followup': kind == 'agent',
                'turns': [{'id': t['id'], 'instruction': t['payload']['command'], 'state': t['state'],
                           'summary': (t['result'] or {}).get('summary', ''), 'created': t['created'], 'updated': t['updated']} for t in turns],
                'conversation_state': latest['state'], 'conversation_updated': latest['updated']}

    def followup(self, kind, identifier, body):
        if kind != 'agent':
            raise HTTPException(422, 'This task has no headless agent session.')
        job, created = self.continuations.accept(identifier, body)
        return {'id': job['id'], 'root_id': self.continuations.root(identifier)['id'],
                'state': job['state'], 'created': created, 'connection': self.queues['agent'].status()}


class NewTask(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id:str=Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    text:str=Field(min_length=1,max_length=4096)
    created_at:str
    timezone:str='UTC'
    attachments:list[str]=Field(default_factory=list,max_length=10)


def mobile_task_router(devices, queues,attachments=None):
    api = APIRouter(prefix='/groceries/v1/mobile')
    tasks = MobileTasks(queues)

    def device(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith('Bearer pa_mobile_'):
            raise HTTPException(401, 'Pair the companion app.')
        try:
            return devices.authenticate(authorization[7:])
        except ValueError as error:
            raise HTTPException(401, str(error)) from None

    @api.get('/tasks')
    def history(q: str = Query(default='', max_length=300), cursor: str | None = Query(default=None, max_length=500),
                limit: int = Query(default=30, ge=1, le=100), phone=Depends(device)):
        return tasks.history(q, cursor, limit)

    @api.post('/tasks')
    def new_task(body:NewTask,phone=Depends(device)):
        identifier='mobile-'+hashlib.sha256((phone+'|'+body.id).encode()).hexdigest()[:48]
        if body.attachments:
            if attachments is None:raise HTTPException(503,'Task attachments unavailable.')
            attachments.bind(body.attachments,identifier,phone)
        payload={'id':identifier,'command':body.text,'created_at':body.created_at,'timezone':body.timezone}
        if body.attachments:payload['attachments']=body.attachments
        job,created=queues['agent'].submit(payload,source='phone_typed')
        return {'task_id':job['id'],'status':job['state'],'reply':'Queued to the laptop: '+body.text,'created':created,'connection':queues['agent'].status()}

    @api.get('/tasks/{kind}/{identifier}')
    def detail(kind: str, identifier: str, phone=Depends(device)):
        result=tasks.detail(kind, identifier)
        if attachments and kind=='agent':
            root=tasks.continuations.root(identifier)
            result['attachments']=attachments.describe(root['payload'].get('attachments',[]))
            for turn,job in zip(result['turns'],tasks.continuations.turns(identifier)):
                turn['attachments']=attachments.describe(job['payload'].get('attachments',[]))
        return result

    @api.post('/tasks/{kind}/{identifier}/followups')
    def followup(kind: str, identifier: str, body: Followup, phone=Depends(device)):
        if body.attachments:
            if kind!='agent' or attachments is None:raise HTTPException(422,'Attachments require an agent task.')
            tasks.continuations.root(identifier)
            child='continue-'+hashlib.sha256(body.id.encode()).hexdigest()[:48]
            attachments.bind(body.attachments,child,phone)
        return tasks.followup(kind, identifier, body)

    return api
