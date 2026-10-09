"""Read-only paired phone preferences from a protected, deployment-local file."""
import json
import logging
import math
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

MAX_BYTES = 4096


class SettingsUnreadable(OSError):
    """The file exists but cannot be read now; that is not the same as unconfigured."""


class MobileSettings:
    def __init__(self, path):
        self.path = Path(path)

    def snapshot(self, strict=False):
        # Missing, incomplete or invalid location configuration is an honest
        # System-theme fallback. No account profile, lookup or GPS is consulted.
        # Problems are logged by reason only, never with the path or file content.
        # strict=True raises for a present-but-unreadable file so a caller can keep
        # its last valid value instead of treating a transient failure as "unset".
        unset = {'daylight': None}
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
        except FileNotFoundError:
            return unset
        except (OSError, ValueError) as error:
            logging.warning('Daylight preferences file is unreadable (%s).', type(error).__name__)
            if strict:
                raise SettingsUnreadable(type(error).__name__) from None
            return unset
        if len(raw) > MAX_BYTES:
            logging.warning('Daylight preferences file is oversized; ignored.')
            return unset
        try:
            body = json.loads(raw)
        except (ValueError, TypeError, OverflowError) as error:
            logging.warning('Daylight preferences are invalid (%s); ignored.', type(error).__name__)
            return unset
        if isinstance(body, dict) and body.get('daylight') is None:
            return unset
        value = body['daylight'] if isinstance(body, dict) else None
        latitude, longitude = (value.get('latitude'), value.get('longitude')) if isinstance(value, dict) else (None, None)
        try:
            usable = (type(latitude) in (int, float) and type(longitude) in (int, float)
                      and math.isfinite(latitude) and math.isfinite(longitude)
                      and -90 <= latitude <= 90 and -180 <= longitude <= 180)
        except OverflowError:
            # An integer literal too large for a float.
            usable = False
        if not usable:
            logging.warning('Daylight preferences are invalid (coordinates missing or out of range); ignored.')
            return unset
        return {'daylight': {'latitude': latitude, 'longitude': longitude}}


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
