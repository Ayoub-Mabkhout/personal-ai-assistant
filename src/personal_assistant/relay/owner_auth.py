"""Standalone owner login. Passwords and browser credentials never enter JavaScript."""
import hashlib
from contextlib import contextmanager
import html
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from .owner_credentials import password_record

COOKIE = 'assistant_owner'


class OwnerAuth:
    def __init__(self, path, credentials_file, submit_token, clock=time.time):
        self.path, self.credentials_file, self.submit_token, self.clock = Path(path), Path(credentials_file), submit_token, clock
        self.lock = threading.Lock()
        self.failures = {}
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS owner_sessions (digest TEXT PRIMARY KEY, expires REAL NOT NULL)')

    @contextmanager
    def db(self):
        connection=sqlite3.connect(self.path)
        try:
            with connection: yield connection
        finally: connection.close()

    def verify_token(self, token):
        if secrets.compare_digest(token.encode(), self.submit_token.encode()):
            return
        raise OSError('Authentication required')

    def authorize(self, request, authorization=None):
        if authorization and authorization.startswith('Bearer '):
            try: return self.verify_token(authorization[7:])
            except OSError: raise HTTPException(401, 'Authentication required.') from None
        token = request.cookies.get(COOKIE, '')
        if not token or len(token) > 256:
            raise HTTPException(401, 'Sign in to Assistant.')
        with self.db() as db:
            row = db.execute('SELECT expires FROM owner_sessions WHERE digest=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or row[0] <= self.clock():
            raise HTTPException(401, 'Sign in to Assistant.')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            self.same_origin(request)

    @staticmethod
    def same_origin(request):
        origin = request.headers.get('origin', '')
        parsed = urlsplit(origin)
        if parsed.scheme != 'https' or parsed.netloc != request.headers.get('host') or parsed.path:
            raise HTTPException(403, 'Same-origin request required.')

    def login(self, username, password, peer):
        if len(username) > 200 or len(password) > 1000:
            raise HTTPException(422, 'Sign-in fields are too long.')
        with self.lock:
            now = self.clock()
            self.failures = {key: value for key, value in self.failures.items() if value[1] > now}
            count, until = self.failures.get(peer, (0, now + 300))
            if count >= 10:
                raise HTTPException(429, 'Try signing in later.')
            self.failures[peer] = (count + 1, until)
            if len(self.failures) > 1024:
                raise HTTPException(429, 'Try signing in later.')
            try:
                record = json.loads(self.credentials_file.read_text())
                digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(record['salt']), n=16384, r=8, p=1).hex()
                valid = secrets.compare_digest(username.encode(), record['username'].encode()) and secrets.compare_digest(digest, record['password_hash'])
            except (OSError, ValueError, KeyError):
                raise HTTPException(503, 'Owner login is not configured.') from None
            if not valid:
                raise HTTPException(401, 'Sign-in failed.')
            self.failures.pop(peer, None)
        token = secrets.token_urlsafe(48)
        with self.db() as db:
            db.execute('DELETE FROM owner_sessions WHERE expires<=?', (now,))
            db.execute('INSERT INTO owner_sessions VALUES (?,?)', (hashlib.sha256(token.encode()).hexdigest(), now + 86400))
        return token

    def router(self):
        api = APIRouter(prefix='/auth')
        def destination(value):
            if value != '/' and not value.startswith(('/groceries/', '/tasks/')):
                return '/groceries/'
            if '\\' in value or '\r' in value or '\n' in value:
                return '/groceries/'
            return value
        @api.get('/login')
        def form(next: str = '/groceries/'):
            response = HTMLResponse('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Assistant sign in</title><link rel="stylesheet" href="/groceries/style.css"><main class="shell"><h1>Assistant</h1><form class="card" method="post" action="/auth/login"><input type="hidden" name="next" value="'+html.escape(destination(next), quote=True)+'"><label>Username <input name="username" autocomplete="username" required maxlength="200"></label><label>Password <input name="password" type="password" autocomplete="current-password" required maxlength="1000"></label><button>Sign in</button></form></main></html>')
            response.headers.update({'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})
            return response
        @api.post('/login')
        async def login(request: Request):
            self.same_origin(request)
            fields = parse_qs((await request.body()).decode('utf-8'))
            token = self.login(fields.get('username', [''])[0], fields.get('password', [''])[0], request.client.host)
            response = RedirectResponse(destination(fields.get('next', ['/groceries/'])[0]), status_code=303)
            response.set_cookie(COOKIE, token, max_age=86400, secure=True, httponly=True, samesite='strict', path='/')
            response.headers['Cache-Control'] = 'no-store'
            return response
        @api.get('/session')
        def session(request: Request):
            self.authorize(request)
            return JSONResponse({'authenticated': True}, headers={'Cache-Control': 'no-store'})
        @api.post('/logout')
        def logout(request: Request):
            self.same_origin(request)
            with self.db() as db:
                db.execute('DELETE FROM owner_sessions WHERE digest=?', (hashlib.sha256(request.cookies.get(COOKIE, '').encode()).hexdigest(),))
            response = JSONResponse({'signed_out': True}, headers={'Cache-Control': 'no-store'})
            response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
            return response
        return api
