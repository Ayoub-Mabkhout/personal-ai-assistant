"""Phone-scoped, at-most-once Termux execution with durable result receipts."""
import json
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    phone: str = Field(min_length=1, max_length=64)
    script: str = Field(min_length=1, max_length=16000)
    workdir: str = Field(default='~/', max_length=1024)
    label: str = Field(default='Phone command', max_length=120)
    timeout: int = Field(default=60, ge=5, le=300)
    ttl: int = Field(default=3600, ge=60, le=86400)


class Claim(BaseModel):
    claim: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')


class Result(Claim):
    model_config = ConfigDict(extra='forbid')
    state: str = Field(pattern=r'^(completed|failed|uncertain)$')
    stdout: str = Field(default='', max_length=32000)
    stderr: str = Field(default='', max_length=32000)
    exit_code: int | None = None
    error: str = Field(default='', max_length=2000)
    truncated: bool = False


class TermuxCommands:
    def __init__(self, devices):
        self.devices = devices
        with devices.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS termux_commands(
            id TEXT PRIMARY KEY,phone TEXT NOT NULL,request TEXT NOT NULL,created REAL NOT NULL,
            expires REAL NOT NULL,state TEXT NOT NULL,claim TEXT,result TEXT);
            CREATE TABLE IF NOT EXISTS termux_capabilities(phone TEXT PRIMARY KEY,body TEXT NOT NULL,seen REAL NOT NULL);''')
            if 'started' not in {r['name'] for r in db.execute('PRAGMA table_info(termux_commands)')}:
                db.execute('ALTER TABLE termux_commands ADD COLUMN started REAL')

    def expire(self, db):
        now=self.devices.clock()
        db.execute("UPDATE termux_commands SET state='expired' WHERE state='queued' AND expires<=?",(now,))
        db.execute("UPDATE termux_commands SET state='uncertain' WHERE state='running' AND started+json_extract(request,'$.timeout')+40<=?",(now,))

    def enqueue(self, command):
        body = command.model_dump(); encoded = json.dumps(body, sort_keys=True)
        with self.devices.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM termux_commands WHERE id=?', (command.id,)).fetchone()
            if old:
                if old['request'] != encoded: raise ValueError('Command ID already has different contents.')
                return self.decode(old), False
            if not db.execute('SELECT id FROM phones WHERE id=? AND revoked=0', (command.phone,)).fetchone():
                raise ValueError('Pair the phone first.')
            now = self.devices.clock()
            db.execute('INSERT INTO termux_commands(id,phone,request,created,expires,state,claim,result) VALUES(?,?,?,?,?,?,NULL,NULL)',
                       (command.id, command.phone, encoded, now, now+command.ttl, 'queued'))
            return self.decode(db.execute('SELECT * FROM termux_commands WHERE id=?', (command.id,)).fetchone()), True

    @staticmethod
    def decode(row):
        result = dict(row); result['request'] = json.loads(result['request'])
        result['result'] = json.loads(result['result']) if result['result'] else None
        return result

    def pending(self, phone):
        with self.devices.db() as db:
            self.expire(db)
            return [self.decode(r) for r in db.execute("SELECT * FROM termux_commands WHERE phone=? AND state IN ('queued','running') ORDER BY created LIMIT 20", (phone,))]

    def status(self, identifier):
        with self.devices.db() as db:
            self.expire(db)
            row = db.execute('SELECT * FROM termux_commands WHERE id=?', (identifier,)).fetchone()
            if not row: raise HTTPException(404, 'Phone command not found.')
            return self.decode(row)

    def claim(self, phone, identifier, claim):
        with self.devices.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.expire(db)
            row = db.execute('SELECT * FROM termux_commands WHERE id=? AND phone=?', (identifier, phone)).fetchone()
            if not row: raise HTTPException(404, 'Phone command not found.')
            if row['claim'] == claim: return self.decode(row)
            if row['state'] != 'queued' or row['expires'] <= self.devices.clock():
                raise HTTPException(409, 'Command expired or already claimed; never execute it again.')
            db.execute("UPDATE termux_commands SET state='running',claim=?,started=? WHERE id=?", (claim, self.devices.clock(), identifier))
            return self.decode(db.execute('SELECT * FROM termux_commands WHERE id=?', (identifier,)).fetchone())

    def receipt(self, phone, identifier, body):
        encoded = json.dumps(body.model_dump(), sort_keys=True)
        with self.devices.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM termux_commands WHERE id=? AND phone=?', (identifier, phone)).fetchone()
            if not row: raise HTTPException(404, 'Phone command not found.')
            if not row['claim'] or not secrets.compare_digest(row['claim'], body.claim): raise HTTPException(409, 'Different execution claim.')
            if row['result'] == encoded: return {'saved': True}
            if row['state'] not in ('running', 'uncertain'): raise HTTPException(409, 'Result already recorded.')
            db.execute('UPDATE termux_commands SET state=?,result=? WHERE id=?', (body.state, encoded, identifier))
            return {'saved': True}


def termux_router(devices, device_auth, owner_auth):
    api = APIRouter(prefix='/termux'); store = TermuxCommands(devices)
    from .mobile_push import MobileEventStore
    events = MobileEventStore(devices)

    @api.post('/commands', dependencies=[Depends(owner_auth)])
    def submit(body: Command):
        row, _ = store.enqueue(body)
        # Retry submission repairs a lost hint without duplicating the command.
        events.enqueue({'type':'phone_command','tag':'termux-'+body.id,'title':'Phone command','message':body.label}, ttl=body.ttl, phone=body.phone)
        return row

    @api.get('/commands/{identifier}', dependencies=[Depends(owner_auth)])
    def status(identifier: str): return store.status(identifier)

    @api.get('/pending')
    def pending(phone=Depends(device_auth)): return store.pending(phone)

    @api.post('/commands/{identifier}/claim')
    def claim(identifier: str, body: Claim, phone=Depends(device_auth)): return store.claim(phone, identifier, body.claim)

    @api.post('/commands/{identifier}/result')
    def receipt(identifier: str, body: Result, phone=Depends(device_auth)): return store.receipt(phone, identifier, body)

    @api.post('/capabilities')
    def capability(body: dict, phone=Depends(device_auth)):
        clean = {k: bool(body.get(k, False)) for k in ('installed','permission','enabled')}
        with devices.db() as db: db.execute('INSERT OR REPLACE INTO termux_capabilities VALUES(?,?,?)', (phone, json.dumps(clean), devices.clock()))
        return {'saved': True}

    @api.get('/capabilities', dependencies=[Depends(owner_auth)])
    def capabilities():
        with devices.db() as db: return [{**dict(r), 'body':json.loads(r['body'])} for r in db.execute('SELECT c.* FROM termux_capabilities c JOIN phones p ON p.id=c.phone WHERE p.revoked=0')]

    return api
