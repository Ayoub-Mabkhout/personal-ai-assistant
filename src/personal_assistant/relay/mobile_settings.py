"""Read-only paired phone preferences from a protected, deployment-local file."""
import json
import math
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse


class MobileSettings:
    def __init__(self, path):
        self.path = Path(path)

    def snapshot(self):
        # Missing, incomplete or invalid location configuration is an honest
        # System-theme fallback. No account profile, lookup or GPS is consulted.
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                return {'daylight': None}
            body = json.loads(raw)
            value = body.get('daylight') if isinstance(body, dict) else None
            if not isinstance(value, dict):
                return {'daylight': None}
            latitude, longitude = value.get('latitude'), value.get('longitude')
            if (type(latitude) not in (int, float) or type(longitude) not in (int, float)
                    or not math.isfinite(latitude) or not math.isfinite(longitude)
                    or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
                return {'daylight': None}
            return {'daylight': {'latitude': latitude, 'longitude': longitude}}
        except (OSError, ValueError, TypeError, OverflowError):
            return {'daylight': None}


def mobile_settings_router(devices, path):
    api = APIRouter(prefix='/groceries/v1/mobile')
    settings = MobileSettings(path)

    def device(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith('Bearer pa_mobile_'):
            raise HTTPException(401, 'Pair the companion app.')
        try:
            return devices.authenticate(authorization[7:])
        except ValueError as error:
            raise HTTPException(401, str(error)) from None

    @api.get('/preferences')
    def preferences(phone=Depends(device)):
        return JSONResponse(settings.snapshot(), headers={'Cache-Control': 'private, no-store'})

    return api
