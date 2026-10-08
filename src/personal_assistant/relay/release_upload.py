"""Narrow CI artifact publication; this credential grants no assistant data access."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import threading
import zipfile

from fastapi import APIRouter, Header, HTTPException, Request

MAX_APK_BYTES = 64 * 1024 * 1024
RELEASE_FIELDS = {'package_name', 'version_code', 'version_name', 'min_sdk', 'size', 'sha256',
                  'native_push_configured', 'diagnostic_only', 'contains_private_audio_fixture'}


def _manifest(encoded):
    try:
        if len(encoded) > 16384:
            raise ValueError()
        value = json.loads(base64.b64decode(encoded, validate=True))
        if (not isinstance(value, dict) or set(value) - RELEASE_FIELDS or value.get('diagnostic_only')
                or value.get('contains_private_audio_fixture')
                or value.get('package_name') != 'com.personalassistant.companion'
                or type(value.get('version_code')) is not int or value['version_code'] <= 0
                or not isinstance(value.get('version_name'), str) or not 0 < len(value['version_name']) < 100
                or type(value.get('min_sdk')) is not int or value['min_sdk'] < 26
                or type(value.get('size')) is not int or not 0 < value['size'] <= MAX_APK_BYTES
                or not isinstance(value.get('sha256'), str) or len(value['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in value['sha256'])):
            raise ValueError()
        return value
    except (TypeError, ValueError, KeyError):
        raise HTTPException(400, 'Invalid release manifest.') from None


def _check_archive(path):
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if ('AndroidManifest.xml' not in names or 'classes.dex' not in names
                    or sum(i.file_size for i in archive.infolist()) > 250 * 1024 * 1024
                    or any('replay/' in n or 'voice/templates/' in n or n.endswith(('.pcm', '.p12', '.pem', '.key'))
                           or '/secrets/' in n for n in names)):
                raise ValueError()
            manifest = archive.read('AndroidManifest.xml')
            if (b'personalassistant.diagnostic_only' in manifest
                    or 'personalassistant.diagnostic_only'.encode('utf-16le') in manifest):
                raise ValueError()
            if 'assets/voice/vosk/settings.json' in names:
                settings = json.loads(archive.read('assets/voice/vosk/settings.json'))
                if not isinstance(settings, dict) or settings.get('diagnostic_only') or settings.get('diagnostic_no_activation'):
                    raise ValueError()
    except (OSError, ValueError, zipfile.BadZipFile, KeyError):
        raise HTTPException(400, 'Invalid or diagnostic APK.') from None


def release_upload_router(feed, token_file):
    """The APK is already signed/verified by CI; phones enforce the installed signer."""
    router = APIRouter(prefix='/companion/v1/releases')
    mutation_lock = threading.Lock()
    token_path = Path(token_file)

    @router.put('/artifact', status_code=201)
    async def upload(request: Request, authorization: str = Header(default=''),
                     x_release_manifest: str = Header(default='')):
        try:
            expected = token_path.read_text(encoding='utf-8').strip()
        except OSError:
            raise HTTPException(503, 'Publication is not configured.') from None
        if len(expected) < 32 or not hmac.compare_digest(authorization.encode(), ('Bearer ' + expected).encode()):
            raise HTTPException(401, 'Publication credential required.')
        release = _manifest(x_release_manifest)
        try:
            length = int(request.headers.get('content-length', release['size']))
        except ValueError:
            raise HTTPException(400, 'Invalid artifact length.') from None
        if length != release['size']:
            raise HTTPException(400, 'Artifact length differs from its manifest.')
        staged = None
        metadata_stage = None
        try:
            digest = hashlib.sha256()
            count = 0
            with tempfile.NamedTemporaryFile(dir=feed.apk.parent, prefix='.companion-upload-', delete=False) as output:
                staged = Path(output.name)
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > release['size'] or count > MAX_APK_BYTES:
                        raise HTTPException(413, 'Artifact exceeds its declared size.')
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if count != release['size'] or digest.hexdigest() != release['sha256']:
                raise HTTPException(400, 'Artifact checksum or length mismatch.')
            _check_archive(staged)
            with mutation_lock:
                current_path = feed.apk.with_suffix('.release.json')
                current = json.loads(current_path.read_text()) if current_path.is_file() else None
                if current and (release['version_code'] < current['version_code']
                        or (release['version_code'] == current['version_code']
                            and release['sha256'] != current['sha256'])):
                    raise HTTPException(409, 'Increment the release version before changing its bytes.')
                if current and release['version_code'] == current['version_code'] and feed.apk.is_file():
                    if hashlib.sha256(feed.apk.read_bytes()).hexdigest() == release['sha256']:
                        return {**feed.publish(release['version_code'], release['sha256']), 'sha256': release['sha256'], 'artifact_changed': False}
                with tempfile.NamedTemporaryFile(dir=feed.apk.parent, prefix='.companion-manifest-', delete=False) as output:
                    metadata_stage = Path(output.name)
                    output.write(json.dumps(release).encode())
                    output.flush()
                    os.fsync(output.fileno())
                # Feed validation rejects any interrupted APK/manifest pair;
                # retrying the same immutable version repairs that pair.
                os.replace(staged, feed.apk)
                os.replace(metadata_stage, current_path)
                result = feed.publish(release['version_code'], release['sha256'])
                return {**result, 'sha256': release['sha256'], 'artifact_changed': True}
        finally:
            if staged:
                staged.unlink(missing_ok=True)
            if metadata_stage:
                metadata_stage.unlink(missing_ok=True)

    return router
