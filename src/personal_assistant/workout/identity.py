"""Password-authentication seam for Iron League, independent of photo encryption.

The browser sends a domain-separated 32-byte auth secret, never the password or
vault key. Hashing this secret does not encrypt any workout records or photos.
The caller retains HTTPS, same-origin checks and Secure/HttpOnly session cookies.
Reference: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
"""
import base64
import hashlib
import hmac
import math
import re
import secrets
import sqlite3
import threading
import unicodedata
from uuid import uuid4


CLIENT_KDF_VERSION = 'pbkdf2sha256_600k_hkdfsha256_v1'
CLIENT_KDF_ITERATIONS = 600000
AUTH_HKDF_INFO = 'iron-league/auth/v1'
VAULT_HKDF_INFO = 'iron-league/vault-wrap/v1'
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**15, 8, 3
SCRYPT_MAXMEM = 64 * 1024 * 1024
AUTH_WINDOW = 600
NAME_ATTEMPTS = 8
CLIENT_ATTEMPTS = 30
_HASH_SLOTS = threading.BoundedSemaphore(2)
_DUMMY = 'scrypt$v1$32768$8$3$AAAAAAAAAAAAAAAAAAAAAA$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'


class IdentityError(ValueError):
    """Safe authentication message containing no credential material."""


class LoginFailed(IdentityError):
    def __init__(self):super().__init__('Name or password is incorrect.')


class EnrollmentDenied(IdentityError):
    def __init__(self):super().__init__('Use the existing profile session to set its password, or choose another name.')


class RateLimited(IdentityError):
    def __init__(self, retry_after):
        self.retry_after=max(1,math.ceil(retry_after))
        super().__init__('Too many sign-in attempts. Try again later.')


def b64(value):return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def unb64(value, size):
    if not isinstance(value,str) or len(value)!=(size*8+5)//6 or not re.fullmatch(r'[A-Za-z0-9_-]+',value):
        raise IdentityError('Invalid authentication material.')
    raw=base64.urlsafe_b64decode(value+'='*(-len(value)%4))
    if len(raw)!=size or b64(raw)!=value:raise IdentityError('Invalid authentication material.')
    return raw


def normalized_name(value):
    if not isinstance(value,str) or len(value)>320:raise IdentityError('Enter a name between 1 and 80 characters.')
    display=' '.join(unicodedata.normalize('NFKC',value).split())
    if not 1<=len(display)<=80 or not all(char.isprintable() for char in display):
        raise IdentityError('Enter a name between 1 and 80 characters.')
    return display,unicodedata.normalize('NFKC',display.casefold())


def _derive(secret,salt):
    # Bound simultaneous memory-hard verifications on the shared small relay.
    with _HASH_SLOTS:
        return hashlib.scrypt(secret,salt=salt,n=SCRYPT_N,r=SCRYPT_R,p=SCRYPT_P,
                              maxmem=SCRYPT_MAXMEM,dklen=32)


def hash_auth_secret(auth_secret):
    raw=unb64(auth_secret,32);salt=secrets.token_bytes(16)
    return 'scrypt$v1$32768$8$3$'+b64(salt)+'$'+b64(_derive(raw,salt))


def verify_auth_secret(auth_secret,verifier):
    raw=unb64(auth_secret,32)
    try:
        scheme,version,n,r,p,salt,digest=verifier.split('$')
        if (scheme,version,n,r,p)!=('scrypt','v1','32768','8','3'):return False
        salt,digest=unb64(salt,16),unb64(digest,32)
    except (ValueError,AttributeError):return False
    return hmac.compare_digest(_derive(raw,salt),digest)


class Identity:
    """Credential storage over an initialized Accounts/Workouts database.

    client_id must come from the server's trusted request context, not JSON. The
    callback hooks run in the write transaction: save an enrollment vault envelope
    and issue its cookie session there. In particular, issuing a login session in
    on_login avoids racing a password change after the verifier was checked.
    """
    def __init__(self,workouts):
        self.workouts,self.clock=workouts,workouts.clock
        with workouts.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS train_credentials(
                    user_id TEXT PRIMARY KEY, login_name TEXT NOT NULL UNIQUE,
                    client_salt TEXT NOT NULL, verifier TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS train_auth_limits(
                    key TEXT PRIMARY KEY, window_start REAL NOT NULL, attempts INTEGER NOT NULL);
            ''')

    def _profiles(self,db,key):
        result=[]
        for row in db.execute('SELECT id,name FROM train_users'):
            if not row['name']:continue
            try:matches=normalized_name(row['name'])[1]==key
            except IdentityError:continue
            if matches:result.append(row)
        return result

    def parameters(self,name):
        _,key=normalized_name(name)
        with self.workouts.db() as db:
            row=db.execute('SELECT client_salt FROM train_credentials WHERE login_name=?',(key,)).fetchone()
        # Always return the same shape. Names already appear in public standings;
        # this is public KDF metadata, never a credential or an account proof.
        return {'version':CLIENT_KDF_VERSION,'kdf':'PBKDF2','hash':'SHA-256',
                'iterations':CLIENT_KDF_ITERATIONS,'salt':row['client_salt'] if row else b64(secrets.token_bytes(16))}

    def _name_bucket(self,key):return 'name:'+hashlib.sha256(key.encode()).hexdigest()

    def _reserve(self,key,client_id):
        if not isinstance(client_id,str) or not 1<=len(client_id)<=256:
            raise IdentityError('A server-derived client identifier is required.')
        buckets=((self._name_bucket(key),NAME_ATTEMPTS),
                 ('client:'+hashlib.sha256(client_id.encode()).hexdigest(),CLIENT_ATTEMPTS))
        now=self.clock()
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM train_auth_limits WHERE window_start<=?',(now-AUTH_WINDOW,))
            for identifier,limit in buckets:
                row=db.execute('SELECT * FROM train_auth_limits WHERE key=?',(identifier,)).fetchone()
                if row and row['attempts']>=limit:raise RateLimited(row['window_start']+AUTH_WINDOW-now)
            for identifier,_ in buckets:
                db.execute('''INSERT INTO train_auth_limits VALUES(?,?,1) ON CONFLICT(key)
                    DO UPDATE SET attempts=attempts+1''',(identifier,now))

    def _success(self,db,key):db.execute('DELETE FROM train_auth_limits WHERE key=?',(self._name_bucket(key),))

    def register(self,name,auth_secret,client_salt,client_id,*,on_enroll=None):
        display,key=normalized_name(name);unb64(client_salt,16);unb64(auth_secret,32)
        self._reserve(key,client_id);verifier=hash_auth_secret(auth_secret);identifier=uuid4().hex
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._profiles(db,key) or db.execute('SELECT 1 FROM train_credentials WHERE login_name=?',(key,)).fetchone():
                raise EnrollmentDenied()
            db.execute('INSERT INTO train_users(id,name,setup_complete) VALUES(?,?,0)',(identifier,display))
            self._insert(db,identifier,key,client_salt,verifier)
            if on_enroll:on_enroll(db,identifier)
            self._success(db,key)
        return identifier

    def _insert(self,db,identifier,key,client_salt,verifier):
        now=self.clock()
        try:
            db.execute('''INSERT INTO train_credentials(user_id,login_name,client_salt,verifier,created,updated)
                VALUES(?,?,?,?,?,?)''',(identifier,key,client_salt,verifier,now,now))
        except sqlite3.IntegrityError:raise EnrollmentDenied() from None

    def claim(self,name,auth_secret,client_salt,prior_session,client_id,*,on_enroll=None):
        _,key=normalized_name(name);unb64(client_salt,16);unb64(auth_secret,32)
        self._reserve(key,client_id);verifier=hash_auth_secret(auth_secret)
        if not isinstance(prior_session,str) or len(prior_session)!=43:raise EnrollmentDenied()
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE');profiles=self._profiles(db,key)
            if len(profiles)!=1:raise EnrollmentDenied()
            identifier=profiles[0]['id']
            proof=db.execute('SELECT 1 FROM train_sessions WHERE hash=? AND user_id=? AND expires>?',
                (hashlib.sha256(prior_session.encode()).hexdigest(),identifier,self.clock())).fetchone()
            if not proof:raise EnrollmentDenied()
            self._insert(db,identifier,key,client_salt,verifier)
            db.execute('DELETE FROM train_sessions WHERE user_id=?',(identifier,))
            if on_enroll:on_enroll(db,identifier)
            self._success(db,key)
        return identifier

    def login(self,name,auth_secret,client_id,*,on_login=None):
        _,key=normalized_name(name);unb64(auth_secret,32);self._reserve(key,client_id)
        with self.workouts.db() as db:
            row=db.execute('SELECT * FROM train_credentials WHERE login_name=?',(key,)).fetchone()
        valid=verify_auth_secret(auth_secret,row['verifier'] if row else _DUMMY)
        if not row or not valid:raise LoginFailed()
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT revision FROM train_credentials WHERE user_id=?',(row['user_id'],)).fetchone()
            if not current or current['revision']!=row['revision']:raise LoginFailed()
            if on_login:on_login(db,row['user_id'])
            self._success(db,key)
        return row['user_id']

    def change_secret(self,user_id,current_secret,new_secret,new_client_salt,client_id,*,on_enroll=None):
        unb64(new_client_salt,16);unb64(new_secret,32);unb64(current_secret,32)
        with self.workouts.db() as db:
            row=db.execute('SELECT * FROM train_credentials WHERE user_id=?',(user_id,)).fetchone()
        key=row['login_name'] if row else 'unknown-user:'+str(user_id)
        self._reserve(key,client_id)
        valid=verify_auth_secret(current_secret,row['verifier'] if row else _DUMMY)
        if not row or not valid:raise LoginFailed()
        verifier=hash_auth_secret(new_secret)
        with self.workouts.db() as db:
            db.execute('BEGIN IMMEDIATE')
            changed=db.execute('''UPDATE train_credentials SET verifier=?,client_salt=?,revision=revision+1,updated=?
                WHERE user_id=? AND revision=?''',(verifier,new_client_salt,self.clock(),user_id,row['revision'])).rowcount
            if not changed:raise LoginFailed()
            db.execute('DELETE FROM train_sessions WHERE user_id=?',(user_id,))
            if on_enroll:on_enroll(db,user_id)
            self._success(db,key)

    def revoke(self,session):
        if not isinstance(session,str) or len(session)!=43:return
        with self.workouts.db() as db:
            db.execute('DELETE FROM train_sessions WHERE hash=?',(hashlib.sha256(session.encode()).hexdigest(),))

    def revoke_all(self,user_id):
        with self.workouts.db() as db:
            db.execute('DELETE FROM train_sessions WHERE user_id=?',(user_id,))
            # Invalidate successful verifications racing session issuance as well.
            db.execute('UPDATE train_credentials SET revision=revision+1,updated=? WHERE user_id=?',(self.clock(),user_id))
