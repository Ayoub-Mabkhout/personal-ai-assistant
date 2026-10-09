"""Phone UI and authenticated cloud grocery API. Standalone owner sessions and paired-device credentials."""
import json
from pathlib import Path
import secrets
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Request
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


def router(path, internal_token, assets, store_info=None, user_verifier=None, phone_sender=None, mobile_settings_file=None, owner_auth=None,retailer_check=None,shopping_config=None):
    if len(internal_token) < 32:
        raise ValueError('Use a dedicated grocery credential of at least 32 characters.')
    store = Groceries(path)
    api = APIRouter(prefix='/groceries')
    from .intelligence import ShoppingIntelligence
    from personal_assistant.relay.voice import VoiceLedger
    shopping_ai=ShoppingIntelligence(store,shopping_config or {},VoiceLedger(Path(path).with_name('voice.sqlite3')))
    api.shopping_ai=shopping_ai
    from personal_assistant.relay.mobile_settings import MobileSettings
    settings = MobileSettings(mobile_settings_file or Path(path).with_name('companion-preferences.json'))

    def authorize(request: Request, authorization: str | None = Header(default=None)):
        if authorization and secrets.compare_digest(authorization.encode(), ('Bearer '+internal_token).encode()):
            return
        if owner_auth:
            return owner_auth.authorize(request, authorization)
        if authorization and authorization.startswith('Bearer ') and user_verifier:
            try: return user_verifier(authorization[7:])
            except OSError: pass
        raise HTTPException(401, 'Sign in to Assistant.')

    @api.get('/v1/list', dependencies=[Depends(authorize)])
    def snapshot():
        return {**store.snapshot(), 'store': store_info or {}, **settings.snapshot()}

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
        try: result=shopping_ai.execute('grocery-'+body.id,body.text)
        except OSError: raise HTTPException(503,'Intelligent grocery commands are unavailable. No changes were applied.') from None
        except (ValueError,Conflict) as error: raise HTTPException(409,str(error)) from None
        return result or {'status':'not_grocery','reply':'That request is not a grocery-list change.','grocery_changed':False}

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
        if filename not in ('app.js','theme.js','daylight.js','style.css','sw.js','manifest.webmanifest','icon.svg','icon-192.png','icon-512.png'):
            raise HTTPException(404)
        target = Path(assets).parent/'shared'/filename if filename == 'daylight.js' else Path(assets)/filename
        response = FileResponse(target, headers={'Cache-Control':'no-cache', 'X-Content-Type-Options':'nosniff'})
        if filename == 'manifest.webmanifest':
            response.media_type = 'application/manifest+json'
        return response
    return api
