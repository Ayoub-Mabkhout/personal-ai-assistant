"""Build emulator-only production-loop diagnostic target, always barred from publication."""
import argparse
import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import build_android_companion as builder

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pcm', type=Path, required=True, help='Private mono PCM16/16kHz fixture; not published')
    parser.add_argument('--wake-runtime', type=Path, required=True)
    parser.add_argument('--release-optimizations',action='store_true',help='Exercise actual release R8 optimization without debuggable; still always diagnostic and non-publishable')
    parser.add_argument('--reuse-staged',action='store_true',help='Reuse an existing diagnostic source snapshot while main UI sources are changing')
    args = parser.parse_args()
    work = ROOT / 'state/android-replay-target'
    app = work / 'apps/android'
    app.mkdir(parents=True, exist_ok=True)
    if not args.reuse_staged:shutil.copytree(ROOT / 'apps/android', app, dirs_exist_ok=True)
    elif not (app/'AndroidManifest.xml').is_file():raise ValueError('Missing diagnostic source snapshot')
    shutil.copyfile(ROOT / 'tests/android/replay/ReplayVoiceService.java', app / 'src/com/personalassistant/companion/ReplayVoiceService.java')
    ns = '{http://schemas.android.com/apk/res/android}'
    ET.register_namespace('android', ns[1:-1])
    manifest = ET.parse(app / 'AndroidManifest.xml')
    application = manifest.getroot().find('application')
    application.set(ns+'label', 'Assistant replay DIAGNOSTIC')
    application.set(ns+'debuggable', 'false' if args.release_optimizations else 'true')
    if args.reuse_staged and not any(entry.attrib.get(ns+'name')=='personalassistant.diagnostic_only' and entry.attrib.get(ns+'value')=='true' for entry in application.findall('meta-data')):raise ValueError('Source snapshot is not diagnostic')
    if not any(entry.attrib.get(ns+'name')=='.ReplayVoiceService' for entry in application.findall('service')):ET.SubElement(application, 'service', {ns+'name': '.ReplayVoiceService', ns+'exported': 'false', ns+'foregroundServiceType': 'microphone'})
    if not any(entry.attrib.get(ns+'name')=='personalassistant.diagnostic_only' for entry in application.findall('meta-data')):ET.SubElement(application, 'meta-data', {ns+'name': 'personalassistant.diagnostic_only', ns+'value': 'true'})
    manifest.write(app / 'AndroidManifest.xml', encoding='utf-8', xml_declaration=True)
    assets = work / 'fixtures/replay'
    assets.mkdir(parents=True, exist_ok=True)
    if args.pcm.resolve()!=(assets/'input.pcm').resolve():shutil.copyfile(args.pcm, assets / 'input.pcm')
    output = ROOT / 'state/exports/assistant-companion-replay-DIAGNOSTIC.apk'
    builder.ROOT = work
    signing = Path(os.environ['LOCALAPPDATA']) / 'PersonalAssistant/secrets/android-signing'
    info = builder.build(Path.home()/'.personal-assistant/android-sdk', output, signing, args.wake_runtime, assets.parent)
    release = output.with_suffix('.release.json')
    metadata = json.loads(release.read_text())
    metadata['diagnostic_only'] = True
    metadata['contains_private_audio_fixture'] = True
    release.write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(info))


if __name__ == '__main__':
    main()
