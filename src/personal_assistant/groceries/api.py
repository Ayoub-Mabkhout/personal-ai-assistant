"""Phone UI and authenticated cloud grocery API. Home Assistant owns login."""
import hashlib
import json
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.request
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from .store import Conflict, Groceries, split_items


class Ingredient(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=300)
    quantity: str = Field(default='', max_length=100)


class Recipe(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    title: str = Field(min_length=1, max_length=200)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=100)
    instructions: str = Field(default='', max_length=6000)
    source: str = Field(default='', max_length=1000)


class Mutation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    operation: Literal['add', 'complete', 'update', 'delete', 'recipe_save', 'recipe_delete', 'recipe_add']
    created_at: str | None = Field(default=None, max_length=100)
    items: list[Ingredient] | None = Field(default=None, max_length=100)
    target: str | None = Field(default=None, max_length=100)
    version: int | None = Field(default=None, ge=1)
    complete: bool = True
    name: str | None = Field(default=None, min_length=1, max_length=300)
    recipe: Recipe | None = None


class Voice(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    text: str = Field(min_length=1, max_length=2000)


class RecipeImport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str = Field(min_length=1, max_length=200000)
    format: Literal['auto', 'text', 'json', 'html'] = 'auto'
    source: str = Field(default='', max_length=1000)


def router(path, internal_token, ha_url, assets, store_info=None, user_verifier=None, phone_sender=None):
    if len(internal_token) < 32:
        raise ValueError('Use a dedicated grocery credential of at least 32 characters.')
    store = Groceries(path)
    api = APIRouter(prefix='/groceries')
    cache, lock = {}, threading.Lock()

    def authorize(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith('Bearer '):
            raise HTTPException(401, 'Sign in to Home Assistant.')
        token = authorization[7:]
        if secrets.compare_digest(token.encode(), internal_token.encode()):
            return
        if len(token) > 8192:
            raise HTTPException(401, 'Invalid login.')
        key = hashlib.sha256(token.encode()).hexdigest()
        with lock:
            if cache.get(key, 0) > time.monotonic():
                return
        try:
            if user_verifier:
                user_verifier(token)
            else:
                request = urllib.request.Request(ha_url.rstrip('/')+'/api/', headers={'Authorization': 'Bearer '+token})
                with urllib.request.urlopen(request, timeout=5) as response:
                    if response.status != 200:
                        raise OSError('Authentication rejected')
        except (OSError, urllib.error.HTTPError):
            raise HTTPException(401, 'Home Assistant login expired. Sign in again.') from None
        with lock:
            # Bounded and short-lived; access tokens are never written to disk.
            for old in list(cache):
                if cache[old] <= time.monotonic():
                    cache.pop(old)
            if len(cache) >= 256:
                cache.clear()
            cache[key] = time.monotonic()+15

    @api.get('/v1/list', dependencies=[Depends(authorize)])
    def snapshot():
        return {**store.snapshot(), 'store': store_info or {}}

    def change(value):
        try:
            return store.mutate(value)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from None

    @api.post('/v1/mutations', dependencies=[Depends(authorize)])
    def mutate(body: Mutation):
        value = body.model_dump(exclude_none=True)
        if body.operation == 'recipe_save' and body.recipe is None:
            raise HTTPException(422, 'A recipe is required.')
        return change(value)

    @api.post('/v1/voice', dependencies=[Depends(authorize)])
    def voice(body: Voice):
        names = split_items(body.text)
        if not names or len(names) > 100 or any(len(name)>300 for name in names):
            raise HTTPException(422, 'Could not identify the shopping items.')
        result = change({'id': body.id, 'operation': 'add', 'items': [{'name': name, 'quantity': ''} for name in names]})
        return {**result, 'names': names, 'summary': 'Added '+', '.join(names)+'.'}

    @api.post('/v1/recipes/import/preview', dependencies=[Depends(authorize)])
    def import_preview(body: RecipeImport):
        from .recipes import preview_import
        try:
            return preview_import(body.content, body.format, body.source)
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            raise HTTPException(422, str(exc)) from None

    @api.post('/v1/recipes/import/commit', dependencies=[Depends(authorize)])
    def import_commit(body: RecipeImport):
        from .recipes import commit_import
        try:
            return commit_import(store, body.content, body.format, body.source)
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            raise HTTPException(422, str(exc)) from None

    from .mobile import Devices,mobile_router
    api.devices=Devices(Path(path).with_name('phones.sqlite3'))
    mobile_api=mobile_router(api.devices,authorize,store,change,
        sender=phone_sender,apk=Path(path).with_name('companion.apk'))
    api.release_pump=mobile_api.release_pump
    api.release_feed=mobile_api.release_feed
    api.include_router(mobile_api)

    @api.get('/')
    def index():
        return FileResponse(Path(assets)/'index.html', headers={'Cache-Control':'no-store',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
            'Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'})

    @api.get('/{filename}')
    def asset(filename: str):
        if filename not in ('app.js','theme.js','style.css','sw.js','manifest.webmanifest','icon.svg','icon-192.png','icon-512.png'):
            raise HTTPException(404)
        response = FileResponse(Path(assets)/filename, headers={'Cache-Control':'no-cache', 'X-Content-Type-Options':'nosniff'})
        if filename == 'manifest.webmanifest':
            response.media_type = 'application/manifest+json'
        return response
    return api
