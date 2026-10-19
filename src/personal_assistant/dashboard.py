"""A private local control surface; never bind to a public interface."""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import secrets
import sqlite3
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, FileResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
import threading
from typing import Literal
from personal_assistant.worker.runtime import RelayClient, TransportError
from personal_assistant.relay.client import OwnerClient
from personal_assistant.relay.features import FeatureEdit, NewFeature

ROOT=Path(__file__).resolve().parents[2]


def read_rows(path,sql):
    path=Path(path)
    if not path.is_file():
        return []
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    db.row_factory=sqlite3.Row
    try:
        return [dict(row) for row in db.execute(sql)]
    finally:
        db.close()


class Command(BaseModel):
    id:str=Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    command:str=Field(min_length=1,max_length=4096)
    created_at:str


class Pause(BaseModel):
    paused:bool


class ProfileEdit(BaseModel):
    revision:int = Field(ge=0)
    focus:str = Field(max_length=1000)
    location:str = Field(max_length=150)
    language_goal:str = Field(max_length=1000)
    planning_preferences:str = Field(max_length=1000)


class Note(BaseModel):
    id:str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    text:str = Field(min_length=1,max_length=6000)


class ShoppingItem(BaseModel):
    id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    name:str=Field(min_length=1,max_length=500)
    complete:bool


class FollowupEdit(BaseModel):
    state:Literal['open','resolved','dismissed']
    note:str=Field(default='',max_length=1000)


class MoneyQuestion(BaseModel):
    request_id:str=Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    text:str=Field(min_length=1,max_length=4096)
    transaction:str|None=Field(default=None,max_length=200)


class MoneyAnswer(BaseModel):
    request_id:str=Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    transaction:str=Field(min_length=1,max_length=200)
    choice:str
    note:str=Field(default='',max_length=1000)


class MoneyAllowance(BaseModel):
    mode:Literal['auto','pinned']
    amount_cents:int|None=Field(default=None,ge=0,le=100_000_000)
    start_day:int=Field(default=1,ge=1,le=28)
    definition:str=Field(default='Regular monthly income less recurring costs; fixed costs do not count as elective spending.',min_length=1,max_length=400)


def create_app(config):
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost'])
    token=secrets.token_urlsafe(32)
    runtime=Path(config['runtime_dir'])
    money_path=Path(config.get('banking_ledger') or (Path.home()/'.personal-assistant'/'banking'/'ledger.sqlite3')).expanduser()
    profile=ROOT/'private/profile'
    edit_lock=threading.Lock()
    cloud=OwnerClient(config) if config.get('submit_token_file') else None

    @app.middleware('http')
    async def protect(request:Request,call_next):
        if request.url.path.startswith('/api/'):
            if not secrets.compare_digest(request.headers.get('x-dashboard-token',''),token):
                return __import__('starlette.responses',fromlist=['JSONResponse']).JSONResponse({'detail':'Local dashboard token required'},401)
            origin=request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return __import__('starlette.responses',fromlist=['JSONResponse']).JSONResponse({'detail':'Origin rejected'},403)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.get('/',response_class=HTMLResponse)
    def index():
        return (ROOT/'apps/dashboard/index.html').read_text(encoding='utf-8').replace('__DASHBOARD_TOKEN__',token)

    @app.get('/whatsapp',response_class=HTMLResponse)
    def link_whatsapp():
        return (ROOT/'apps/dashboard/whatsapp.html').read_text(encoding='utf-8').replace('__DASHBOARD_TOKEN__',token)

    @app.get('/daylight.js')
    def daylight_script():
        return FileResponse(ROOT/'apps/shared/daylight.js',media_type='text/javascript')

    @app.get('/api/preferences')
    def preferences():
        from personal_assistant.relay.mobile_settings import MobileSettings, SettingsUnreadable
        configured=config.get('mobile_settings_file')
        path=Path(configured).expanduser() if configured else runtime/'companion-preferences.json'
        try:
            return MobileSettings(path).snapshot(strict=True)
        except SettingsUnreadable:
            # A transient read failure must not look like "no place configured": the page would clear its cached place.
            raise HTTPException(503,'Daylight preferences are temporarily unreadable.') from None

    @app.get('/api/profile')
    def profile_data():
        manifest=json.loads((profile/'manifest.json').read_text(encoding='utf-8'))
        for theme in manifest['themes']:
            path=(profile/theme['file']).resolve()
            if path.parent != profile.resolve() or path.suffix != '.md':
                raise HTTPException(500,'Invalid profile theme path')
            theme['content']=path.read_text(encoding='utf-8') if path.exists() else 'Not documented yet.'
        return manifest

    @app.get('/api/profile/digest')
    def digest():
        path=profile/'dashboard.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'name':'Profile','revision':0}

    @app.post('/api/profile/digest')
    def edit_digest(body:ProfileEdit):
        with edit_lock:
            path=profile/'dashboard.json'
            data=json.loads(path.read_text(encoding='utf-8'))
            if data.get('revision',0)!=body.revision:
                raise HTTPException(409,'Profile changed. Refresh before saving.')
            updates=body.model_dump(exclude={'revision'})
            data.update(updates)
            data['revision']=body.revision+1
            data['updated_at']=datetime.now(timezone.utc).isoformat()
            # Curated UI edits supplement the imported snapshot; retain provenance.
            audit={'at':data['updated_at'],'source':'direct user edit in local dashboard','updates':updates}
            with (profile/'dashboard-edits.jsonl').open('a',encoding='utf-8') as handle:
                handle.write(json.dumps(audit,ensure_ascii=False)+'\n')
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            temporary.replace(path)
            return data

    @app.get('/api/profile/photo')
    def photo():
        path=profile/'photo.png'
        if not path.is_file():
            raise HTTPException(404,'No profile photo saved.')
        return FileResponse(path,media_type='image/png')

    @app.get('/api/notes')
    def notes():
        return read_rows(runtime/'notes.sqlite3','SELECT * FROM notes ORDER BY created DESC')

    @app.post('/api/notes')
    def save_note(body:Note):
        with sqlite3.connect(runtime/'notes.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY,text TEXT NOT NULL,created TEXT NOT NULL)')
            row=db.execute('SELECT text FROM notes WHERE id=?',(body.id,)).fetchone()
            if row and row[0]!=body.text:
                raise HTTPException(409,'This note ID already has different content.')
            db.execute('INSERT OR IGNORE INTO notes VALUES(?,?,?)',(body.id,body.text,datetime.now(timezone.utc).isoformat()))
        return {'saved':True}

    @app.get('/api/connections')
    def connections():
        whatsapp=Path(config.get('whatsapp_runtime',str(Path.home()/'.personal-assistant/whatsapp')))
        status=whatsapp/'status.json'
        data=json.loads(status.read_text()) if status.is_file() else {'state':'not_started'}
        return {'whatsapp':data,'emails':['personal Gmail','TUM Outlook'],'work_email':'excluded'}

    @app.get('/api/whatsapp/qr')
    def whatsapp_qr():
        whatsapp=Path(config.get('whatsapp_runtime',str(Path.home()/'.personal-assistant/whatsapp')))
        path=whatsapp/'pairing.png'
        if not path.is_file():
            raise HTTPException(404,'No active pairing code. Check the account state.')
        return FileResponse(path,media_type='image/png')

    @app.get('/api/status')
    def status():
        path=runtime/'status.json'
        worker=json.loads(path.read_text()) if path.is_file() else {'state':'not_started'}
        if worker.get('updated_at'):
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(worker['updated_at'])).total_seconds()
            if age>45:
                worker={**worker,'state':'unavailable'}
        try:
            relay=RelayClient(config['relay_url'],config['submit_token_file'],timeout=5).call('/v1/status')
        except (TransportError,OSError):
            relay={'laptop':'unknown','queued':None}
        environment=Path(config.get('lab_environment',''))
        lab=json.loads(environment.read_text()) if environment.is_file() else {}
        checks=environment.parent/'checks.json'
        if checks.is_file():
            lab['checks']=json.loads(checks.read_text())
        return {'worker':worker,'relay':relay,'mail':{'gmail':'Authentication pending','outlook':'Authentication pending'},'lab':lab}

    @app.get('/api/activity')
    def activity():
        rows=read_rows(runtime/'execution.sqlite3','SELECT id,state,outcome,started,updated FROM runs ORDER BY updated DESC LIMIT 25')
        if config.get('agent_runtime_dir'):
            rows+=read_rows(Path(config['agent_runtime_dir'])/'execution.sqlite3','SELECT id,state,outcome,started,updated FROM runs ORDER BY updated DESC LIMIT 25')
            rows=sorted(rows,key=lambda row:row['updated'],reverse=True)[:25]
        for row in rows:
            outcome=json.loads(row.pop('outcome') or '{}')
            row['summary']=outcome.get('result',{}).get('summary','In progress')
            row['state']=outcome.get('state',row['state'])
        return rows

    @app.get('/api/shopping')
    def shopping():
        if cloud is None:
            raise HTTPException(503,'Shopping-list connection is not configured.')
        try:
            return [{'id':item['id'],'name':item['name'],'complete':item['complete']} for item in cloud.call('/groceries/v1/list')['items']]
        except OSError:
            raise HTTPException(503,'Shopping list is temporarily unreachable.') from None

    @app.post('/api/shopping')
    def check_shopping_item(body:ShoppingItem):
        if cloud is None:
            raise HTTPException(503,'Shopping-list connection is not configured.')
        try:
            snapshot=cloud.call('/groceries/v1/list')
            item=next(item for item in snapshot['items'] if item['id']==body.id)
            return cloud.call('/groceries/v1/mutations',{'id':__import__('uuid').uuid4().hex,'operation':'complete','target':body.id,'version':item['version'],'complete':body.complete})
        except OSError:
            raise HTTPException(503,'Shopping-list change was not confirmed. Refresh to check its state.') from None

    @app.get('/api/calendar')
    def calendar():
        from .worker.runtime import CalendarExecutor
        import threading
        now=datetime.now(timezone.utc)
        job={'created':now.timestamp(),'payload':{'command':'Show my calendar this week',
            'timezone':config.get('timezone','Europe/Berlin'),'created_at':now.isoformat()}}
        return CalendarExecutor(config).execute(job,threading.Event())

    @app.get('/api/money')
    def money(period_start:str|None=Query(default=None)):
        # Read only the already configured local ledger. Loading this page never opens a bank
        # connection or invokes the auditor; an absent ledger remains an honest empty state.
        if period_start is not None:
            try:
                if date.fromisoformat(period_start).isoformat()!=period_start:
                    raise ValueError()
            except ValueError:
                raise HTTPException(422,'Choose an available money period start date.') from None
        if not money_path.is_file():
            if period_start is not None:
                raise HTTPException(422,'That money period is not available.')
            return {'months':[],'current_start':None,'historical':False,'total_spent_cents':0,'available':False,'period':None,'allowance':None,'spent_cents':0,'remaining_cents':0,
                    'income_cents':0,'fixed_cents':0,'free_cents':0,'categories':[],'fixed_costs':[],
                    'review':[],'transactions':[],'insights':[]}
        try:
            from .banking.ledger import Ledger, summarise
            from .banking.service import history
            from .banking.tools import logo_catalog
            ledger=Ledger(money_path)
            current=summarise(ledger)
            current_start=current['period']['start']
            previous=history(ledger,date.fromisoformat(current_start))
            boards=[current,*previous]
            months=[{'start':board['period']['start'],'end':board['period']['end'],
                     'spent_cents':board['spent_cents'],
                     'total_spent_cents':sum(int(c.get('cents') or 0) for c in board.get('categories',[])),
                     'historical':index>0} for index,board in enumerate(boards)]
            value=next((board for board in boards if board['period']['start']==period_start),None) if period_start else current
            if value is None:
                raise HTTPException(422,'That money period is not available.')
            historical=value['period']['start']!=current_start
            if historical:
                rows={row['id']:{**row,'category':name} for name,items in value['category_transactions'].items() for row in items}
                value={**value,'transactions':list(rows.values()),'allowance':None,'remaining_cents':0,
                       'free_cents':0,'review':[],'insights':[],
                       'fixed_cost_transactions':[row for row in rows.values() if row.get('kind')=='fixed_cost']}
            total_spent_cents=sum(int(c.get('cents') or 0) for c in value.get('categories',[]))
        except (OSError,sqlite3.Error,KeyError,ValueError):
            raise HTTPException(503,'The local money ledger is temporarily unavailable.') from None
        transactions=value.get('transactions') or []
        # Prefer the ledger's complete aggregate fields; the legacy transaction list is capped.
        explicit=value.get('fixed_costs')
        if isinstance(explicit,list):
            fixed_costs={str(x.get('name') or 'Fixed costs'):int(x.get('cents') or x.get('amount_cents') or 0) for x in explicit}
        else:
            fixed_costs={}
            for row in transactions:
                if row.get('kind')=='fixed_cost' and row.get('amount_cents',0)<0:
                    name=row.get('category') or 'Fixed costs'
                    fixed_costs[name]=fixed_costs.get(name,0)-row.get('amount_cents',0)
        categories={}
        raw_categories=value.get('categories')
        if isinstance(raw_categories,list):
            categories={str(x.get('name') or 'Other'):int(x.get('cents') or x.get('amount_cents') or 0) for x in raw_categories}
            # Fixed costs occupy their own map region. Remove them from the elective region.
            for name,cents in fixed_costs.items():
                if name in categories:
                    categories[name]=max(0,categories[name]-cents)
            categories={name:cents for name,cents in categories.items() if cents>0}
        else:
            for row in transactions:
                if row.get('counts') and row.get('kind')!='fixed_cost':
                    name=row.get('category') or 'Other'
                    categories[name]=categories.get(name,0)-int(row.get('amount_cents') or 0)
        regular_income=value.get('regular_income_cents',value.get('income_cents',0))
        free=value.get('free_to_spend_cents',value.get('free_cents',(value.get('allowance') or {}).get('amount_cents',0)))
        return {**value,'available':True,'months':months,'current_start':current_start,
                'merchant_logos':logo_catalog(ledger),
                'historical':historical,'total_spent_cents':total_spent_cents,'categories':sorted(({'name':k,'cents':v} for k,v in categories.items()),key=lambda x:-x['cents']),
                'fixed_costs':[{'name':k,'cents':v} for k,v in fixed_costs.items()],
                'fixed_cents':sum(fixed_costs.values()),'regular_income_cents':regular_income,'free_cents':free,
                'category_transactions':value.get('category_transactions') or {},
                'fixed_cost_transactions':value.get('fixed_cost_transactions') or []}

    @app.post('/api/money/questions')
    def ask_money_question(body:MoneyQuestion):
        from .banking import service
        from .banking.ledger import Ledger
        if not body.text.strip(): raise HTTPException(422,'Enter a question for the local money auditor.')
        try:
            sequence=service.ask_question(Ledger(money_path),body.request_id,body.text.strip(),body.transaction)
        except ValueError as error:
            raise HTTPException(409,str(error)) from None
        return {'sequence':sequence,'state':'queued','request_id':body.request_id}

    @app.get('/api/money/questions/{sequence}')
    def money_question_status(sequence:int):
        from .banking.ledger import Ledger
        if sequence<1 or not money_path.is_file(): raise HTTPException(404,'Question not found.')
        ledger=Ledger(money_path)
        with ledger.db() as db:
            job=db.execute("SELECT kind,state FROM audit_jobs WHERE seq=? AND kind IN ('question','explanation')",(sequence,)).fetchone()
        if not job: raise HTTPException(404,'Question not found.')
        reply=ledger.audit_output(sequence)
        return {'sequence':sequence,'state':'replied' if reply is not None else job['state'],'reply':reply}

    @app.post('/api/money/answers')
    def answer_money_question(body:MoneyAnswer):
        from .banking import service
        from .banking.ledger import KINDS,Ledger
        if body.choice not in (*KINDS,'confirm'):
            raise HTTPException(422,'Choose a supported transaction classification.')
        if not body.note.strip(): raise HTTPException(422,'Add a short note explaining your answer.')
        ledger=Ledger(money_path)
        event_key='dashboard:'+body.request_id
        with ledger.db() as db:
            previous=db.execute('SELECT payload FROM audit_jobs WHERE kind=? AND job_key=?',('owner_answer',event_key)).fetchone()
        row=next((item for item in ledger.transactions(include_gone=True) if item['id']==body.transaction),None)
        if not row: raise HTTPException(404,'Transaction not found.')
        if previous:
            previous_payload=json.loads(previous['payload'])
            expected_kind=row['kind'] if body.choice=='confirm' else body.choice
            expected_reason='Set by you: '+body.note.strip()
            if previous_payload.get('id')!=body.transaction or previous_payload.get('kind')!=expected_kind or previous_payload.get('reasoning')!=expected_reason:
                raise HTTPException(409,'This answer request ID was already used for a different decision.')
            return {'recorded':True,'duplicate':True}
        if not row.get('question'): raise HTTPException(409,'This auditor question has already been answered.')
        if not service.answer(ledger,row,body.choice,body.note.strip(),event_key=event_key):
            raise HTTPException(422,'This choice cannot be applied to the transaction.')
        return {'recorded':True,'duplicate':False}

    @app.get('/api/money/allowance')
    def money_allowance():
        from .banking.ledger import DEFAULTS,Ledger
        if not money_path.is_file(): return DEFAULTS['allowance']
        return Ledger(money_path).setting('allowance') or DEFAULTS['allowance']

    @app.post('/api/money/allowance')
    def save_money_allowance(body:MoneyAllowance):
        from .banking.ledger import DEFAULTS,Ledger
        value={**DEFAULTS['allowance'],'mode':body.mode,'start_day':body.start_day,'definition':body.definition.strip()}
        if body.mode=='pinned':
            if body.amount_cents is None: raise HTTPException(422,'Enter a manual monthly amount.')
            value['amount_cents']=body.amount_cents
        ledger=Ledger(money_path)
        ledger.set_setting('allowance',value)
        return ledger.setting('allowance')

    @app.get('/api/documents')
    def documents(query:str=Query(default='',max_length=200)):
        catalog=Path(config.get('mail_archive',str(Path.home()/'.personal-assistant/mail')))/'catalog.sqlite3'
        if not catalog.is_file():
            return {'attachments':[],'counts':[],'total':0}
        db=sqlite3.connect(catalog.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
        db.row_factory=sqlite3.Row
        try:
            rows=[dict(row) for row in db.execute('SELECT account,name,mime,status,category FROM attachments WHERE name LIKE ? OR category LIKE ? LIMIT 100',('%'+query+'%','%'+query+'%'))]
            counts=[dict(row) for row in db.execute('SELECT status,COUNT(*) AS count FROM attachments GROUP BY status')]
            total=db.execute('SELECT COUNT(*) FROM attachments').fetchone()[0]
            return {'attachments':rows,'counts':counts,'total':total}
        finally:
            db.close()

    def followup_config():
        settings={
            'archive':config.get('mail_archive',str(Path.home()/'.personal-assistant/mail')),
            'followups_db':config.get('followups_db'),
            'policy':config.get('mail_policy',str(ROOT/'private/auth/mail-connections.json')),
        }
        path=config.get('mail_automation_config')
        if path and Path(path).is_file():
            try: settings.update(json.loads(Path(path).read_text(encoding='utf-8-sig')))
            except (ValueError,OSError): raise HTTPException(503,'Email follow-ups are temporarily unavailable.') from None
        if not settings.get('followups_db'): settings['followups_db']=str(Path(settings['archive'])/'followups.sqlite3')
        return settings

    @app.get('/api/followups')
    def followups(state:Literal['open','resolved','dismissed','all']='open'):
        settings=followup_config()
        metadata={}
        if settings.get('runtime'):
            path=Path(settings['runtime'])/'state.json'
            if path.is_file():
                try: metadata=json.loads(path.read_text(encoding='utf-8'))
                except (ValueError,OSError): pass
        from .mail_followups import Followups
        items=Followups(settings['followups_db'],settings['archive'],settings.get('policy')).list(None if state=='all' else state) if Path(settings['followups_db']).is_file() else []
        visible=[]
        for row in items:
            data=row['data']
            visible.append({key:row[key] for key in ('id','kind','title','state','certainty','due_date','updated_at')} | {
                'source_url':data.get('source_url'),'quote':data.get('quote','')[:4000],
                'checked_at':data.get('checked_at'),'message_id':data.get('message_id')})
        if metadata.get('last_result',{}).get('error'):
            note='Email checking needs attention. Saved follow-ups remain available.'
        elif not metadata.get('watermark'):
            note='The first email check is pending. This list may be incomplete.'
        else:
            checked=datetime.fromtimestamp(metadata['watermark'],timezone.utc).isoformat()
            note='Recent email checked through '+checked[:10]+'. Older mail is collected gradually.'
        return {'items':visible,'coverage_note':note}

    @app.post('/api/followups/{identity}')
    def edit_followup(identity:str,body:FollowupEdit):
        import re
        if not re.fullmatch(r'[a-f0-9]{24}',identity): raise HTTPException(404,'Follow-up not found.')
        settings=followup_config()
        if not Path(settings['followups_db']).is_file(): raise HTTPException(404,'Follow-up not found.')
        from .mail_followups import Followups
        try:
            record=Followups(settings['followups_db'],settings['archive'],settings.get('policy')).set_state(identity,body.state,body.note)
        except KeyError: raise HTTPException(404,'Follow-up not found.') from None
        return {'id':record['id'],'state':record['state']}

    @app.post('/api/commands')
    def submit(body:Command):
        client=RelayClient(config['relay_url'],config['submit_token_file'])
        try:
            return client.call('/v1/commands',{'id':body.id,'command':body.command,
                'timezone':config.get('timezone','Europe/Berlin'),'created_at':body.created_at})
        except TransportError as exc:
            raise HTTPException(503,'Acknowledgement unavailable. The request is saved in this browser; retry uses the same request ID.') from exc

    @app.post('/api/agent-prompts')
    def submit_agent(body:Command):
        client=RelayClient(config['relay_url'],config['submit_token_file'])
        try:
            return client.call('/v1/agent/prompts',{'id':body.id,'prompt':body.command,
                'timezone':config.get('timezone','Europe/Berlin'),'created_at':body.created_at})
        except TransportError as error:
            raise HTTPException(503,'The acknowledgement is unavailable. Your prompt remains in this browser; retry keeps the same ID.') from error

    # The features checklist lives on the relay so the paired phone shares it over mobile data.
    def features_call(path='',payload=None,method=None):
        if not config.get('relay_url') or not config.get('submit_token_file'):
            raise HTTPException(503,'The features list is not connected to the relay.')
        try:
            return RelayClient(config['relay_url'],config['submit_token_file']).call('/v1/features'+path,payload,method)
        except TransportError as error:
            if error.status==404: raise HTTPException(404,'Feature not found. Refresh the list.') from None
            if error.status==409: raise HTTPException(409,'This feature was deleted on another device.') from None
            if error.status in (400,422): raise HTTPException(422,'Check the feature title and details.') from None
            raise HTTPException(503,'The change was not confirmed. Refresh to check the list.' if payload is not None or method else 'The features list is temporarily unreachable.') from None
        except (OSError,ValueError):
            raise HTTPException(503,'The features list is not connected to the relay.') from None

    @app.get('/api/features')
    def features():
        return features_call()

    @app.post('/api/features')
    def add_feature(body:NewFeature):
        return features_call('',body.model_dump(exclude_none=True))

    def feature_path(identity):
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',identity): raise HTTPException(404,'Feature not found.')
        return '/'+identity

    @app.patch('/api/features/{identity}')
    def edit_feature(identity:str,body:FeatureEdit):
        return features_call(feature_path(identity),body.model_dump(exclude_none=True),'PATCH')

    @app.delete('/api/features/{identity}')
    def delete_feature(identity:str):
        return features_call(feature_path(identity),method='DELETE')

    @app.post('/api/pause')
    def pause(body:Pause):
        path=runtime/'pause.flag'
        if body.paused:
            path.write_text('Paused through local dashboard\n')
        else:
            path.unlink(missing_ok=True)
        return {'paused':body.paused}

    return app


def main():
    import argparse
    import uvicorn
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8787)
    args=parser.parse_args()
    app=create_app(json.loads(args.config.read_text(encoding='utf-8')))
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)


if __name__ == '__main__':
    main()
