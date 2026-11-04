"""Opaque client-encrypted storage. No server master key or decryption endpoint.

Only the vault API uses these tables, apart from progress photos: a photo entity with
vault=true has its bytes here (kind 'photo', same id), and the workout store checks and
deletes that row with the entity. Other workout entities and imports remain plaintext.
"""
import base64
import json
import re
import sqlite3

from ..relay.store import Conflict,Missing
from .identity import CLIENT_KDF_VERSION,CLIENT_KDF_ITERATIONS,unb64


MAX_PLAINTEXT_BYTES=16*1024*1024
MAX_CIPHER_BYTES=MAX_PLAINTEXT_BYTES+16
MAX_REVISION=2**53-1
KIND=re.compile(r'[A-Za-z][A-Za-z0-9_.:-]{0,63}')
OBJECT_ID=re.compile(r'[A-Za-z0-9_.:-]{1,200}')
ENVELOPE_FIELDS={'version','userId','keyId','kind','objectId','revision','nonceB64','cipherB64'}


def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def fields(value,expected):
    if not isinstance(value,dict) or set(value)!=set(expected):raise ValueError('Invalid encrypted vault fields.')


def revision(value,minimum=0):
    if type(value) is not int or not minimum<=value<=MAX_REVISION:raise ValueError('Invalid vault revision.')
    return value


def ciphertext(value,maximum):
    if not isinstance(value,str) or len(value)>(maximum*8+5)//6 or not re.fullmatch(r'[A-Za-z0-9_-]*',value):
        raise ValueError('Invalid vault ciphertext.')
    try:raw=base64.urlsafe_b64decode(value+'='*(-len(value)%4))
    except ValueError:raise ValueError('Invalid vault ciphertext.') from None
    if not 16<=len(raw)<=maximum or base64.urlsafe_b64encode(raw).decode().rstrip('=')!=value:
        raise ValueError('Invalid vault ciphertext.')


def envelope(value,*,user_id,key_id,kind,object_id,expected_revision,maximum=MAX_CIPHER_BYTES):
    fields(value,ENVELOPE_FIELDS)
    if type(value['version']) is not int or value['version']!=1:raise ValueError('Unsupported vault version.')
    revision(value['revision'],1)
    expected={'userId':user_id,'keyId':key_id,'kind':kind,'objectId':object_id,'revision':expected_revision}
    if any(value[key]!=bound for key,bound in expected.items()):raise ValueError('Encrypted vault identity does not match this object.')
    unb64(value['nonceB64'],12);ciphertext(value['cipherB64'],maximum)
    return value


def key_record(value,user_id,client_salt):
    fields(value,{'version','userId','keyId','password','recovery'})
    if type(value['version']) is not int or value['version']!=1 or value['userId']!=user_id:
        raise ValueError('Encrypted vault identity does not match this profile.')
    key_id=value['keyId'];unb64(key_id,16)
    fields(value['password'],{'parameters','wrappedMaster'});fields(value['recovery'],{'salt','wrappedMaster'})
    params=value['password']['parameters'];fields(params,{'version','kdf','hash','iterations','salt'})
    if (params['version']!=CLIENT_KDF_VERSION or params['kdf']!='PBKDF2' or params['hash']!='SHA-256'
        or type(params['iterations']) is not int or params['iterations']!=CLIENT_KDF_ITERATIONS or params['salt']!=client_salt):
        raise ValueError('Vault password parameters do not match the enrolled credential.')
    unb64(params['salt'],16);unb64(value['recovery']['salt'],16)
    password=value['password']['wrappedMaster']
    if not isinstance(password,dict):raise ValueError('Invalid encrypted password wrapper.')
    envelope(password,user_id=user_id,key_id=key_id,kind='vault-password-key',object_id=key_id,
             expected_revision=revision(password.get('revision'),1),maximum=48)
    recovery=value['recovery']['wrappedMaster']
    envelope(recovery,user_id=user_id,key_id=key_id,kind='vault-recovery-key',object_id=key_id,expected_revision=1,maximum=48)
    # A wrapped AES-256 key is 32 bytes plus its 16-byte GCM tag.
    if len(base64.urlsafe_b64decode(password['cipherB64']+'='*(-len(password['cipherB64'])%4)))!=48:
        raise ValueError('Invalid encrypted master key length.')
    if len(base64.urlsafe_b64decode(recovery['cipherB64']+'='*(-len(recovery['cipherB64'])%4)))!=48:
        raise ValueError('Invalid encrypted master key length.')
    return value


class PrivateVault:
    def __init__(self,workouts):
        self.workouts,self.clock=workouts,workouts.clock
        with workouts.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS train_vault_keys(user_id TEXT PRIMARY KEY,key_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,record TEXT NOT NULL,updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS train_vault_objects(user_id TEXT NOT NULL,kind TEXT NOT NULL,
                    id TEXT NOT NULL,key_id TEXT NOT NULL,revision INTEGER NOT NULL,envelope TEXT NOT NULL,
                    updated REAL NOT NULL,PRIMARY KEY(user_id,kind,id));
                CREATE TABLE IF NOT EXISTS train_vault_nonces(user_id TEXT NOT NULL,key_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,PRIMARY KEY(user_id,key_id,nonce));
            ''')

    def status(self,user_id):
        # Do not imply that adding encrypted storage has migrated existing APIs.
        return {'privacy_status':'migration_required','migration_required':True,
                'encrypted_scope':'vault_records_only','recovery_auth_available':False}

    def get_key(self,user_id):
        with self.workouts.db() as db:row=db.execute('SELECT * FROM train_vault_keys WHERE user_id=?',(user_id,)).fetchone()
        if not row:raise Missing('Enroll the encrypted vault first.')
        return {'revision':row['revision'],'record':json.loads(row['record']),'updated':row['updated'],**self.status(user_id)}

    def put_key(self,user_id,value,base_revision):
        revision(base_revision)
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            credential=db.execute('SELECT client_salt FROM train_credentials WHERE user_id=?',(user_id,)).fetchone()
            if not credential:raise ValueError('Enroll a password before the encrypted vault.')
            key_record(value,user_id,credential['client_salt']);encoded=encode(value)
            previous=db.execute('SELECT * FROM train_vault_keys WHERE user_id=?',(user_id,)).fetchone()
            if previous and previous['revision']==base_revision+1 and previous['record']==encoded:
                return {'revision':previous['revision'],'record':value,**self.status(user_id)}
            if (previous['revision'] if previous else 0)!=base_revision:raise Conflict('The encrypted vault changed; reload it first.')
            if previous and previous['key_id']!=value['keyId']:raise Conflict('Changing the master key requires an explicit data migration.')
            if value['password']['wrappedMaster']['revision']!=base_revision+1:
                raise ValueError('Password wrapper revision must match the vault update.')
            db.execute('''INSERT INTO train_vault_keys VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                revision=excluded.revision,record=excluded.record,updated=excluded.updated''',
                (user_id,value['keyId'],base_revision+1,encoded,self.clock()))
        return {'revision':base_revision+1,'record':value,**self.status(user_id)}

    def put(self,user_id,kind,identifier,value,base_revision):
        self._path(kind,identifier);revision(base_revision);encoded=encode(value)
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            key=db.execute('SELECT key_id FROM train_vault_keys WHERE user_id=?',(user_id,)).fetchone()
            if not key:raise Missing('Enroll the encrypted vault first.')
            envelope(value,user_id=user_id,key_id=key['key_id'],kind=kind,object_id=identifier,expected_revision=base_revision+1)
            previous=db.execute('SELECT * FROM train_vault_objects WHERE user_id=? AND kind=? AND id=?',(user_id,kind,identifier)).fetchone()
            if previous and previous['revision']==base_revision+1 and previous['envelope']==encoded:
                return {'revision':previous['revision'],'envelope':value}
            if (previous['revision'] if previous else 0)!=base_revision:raise Conflict('The encrypted object changed; reload it first.')
            try:db.execute('INSERT INTO train_vault_nonces VALUES(?,?,?)',(user_id,key['key_id'],value['nonceB64']))
            except sqlite3.IntegrityError:
                raise Conflict('This encryption nonce was already used; encrypt again.') from None
            db.execute('''INSERT INTO train_vault_objects VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,kind,id)
                DO UPDATE SET revision=excluded.revision,envelope=excluded.envelope,updated=excluded.updated''',
                (user_id,kind,identifier,key['key_id'],base_revision+1,encoded,self.clock()))
        return {'revision':base_revision+1,'envelope':value}

    def _path(self,kind,identifier):
        if not isinstance(kind,str) or not KIND.fullmatch(kind) or not isinstance(identifier,str) or not OBJECT_ID.fullmatch(identifier):
            raise ValueError('Invalid encrypted object identity.')

    def get(self,user_id,kind,identifier):
        self._path(kind,identifier)
        with self.workouts.db() as db:
            row=db.execute('SELECT * FROM train_vault_objects WHERE user_id=? AND kind=? AND id=?',(user_id,kind,identifier)).fetchone()
        if not row:raise Missing('Encrypted object not found.')
        return {'revision':row['revision'],'envelope':json.loads(row['envelope']),'updated':row['updated']}

    def listing(self,user_id,kind=None,cursor=None,limit=50):
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('Invalid encrypted object page size.')
        params=[user_id];where='user_id=?'
        if kind:
            self._path(kind,'placeholder');where+=' AND kind=?';params.append(kind)
        if cursor:
            try:
                if len(cursor)>600:raise ValueError()
                after=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
                if not isinstance(after,list) or len(after)!=2:raise ValueError()
                self._path(*after)
            except (ValueError,TypeError):raise ValueError('Invalid encrypted object cursor.') from None
            where+=' AND (kind,id)>(?,?)';params+=after
        with self.workouts.db() as db:
            rows=db.execute('SELECT kind,id,key_id,revision,updated FROM train_vault_objects WHERE '+where+
                            ' ORDER BY kind,id LIMIT ?',(*params,limit+1)).fetchall()
        items=[dict(row) for row in rows[:limit]];next_cursor=None
        if len(rows)>limit:
            last=rows[limit-1];next_cursor=base64.urlsafe_b64encode(encode([last['kind'],last['id']]).encode()).decode().rstrip('=')
        return {'items':items,'next_cursor':next_cursor,**self.status(user_id)}
