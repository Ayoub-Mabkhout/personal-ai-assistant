"""Build and sign the native companion with pinned Gradle/AGP and SDK dependencies."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import re
import subprocess
import zipfile
import hashlib
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def run(command):
    if str(command[0])=='keytool' and not shutil.which('keytool'):
        info=subprocess.run(['java','-XshowSettings:properties','-version'],capture_output=True,text=True,check=True)
        java_home=re.search(r'java.home\s*=\s*(.+)',info.stderr).group(1).strip()
        command=[Path(java_home)/'bin'/('keytool.exe' if os.name=='nt' else 'keytool'),*command[1:]]
    subprocess.run([str(x) for x in command],check=True)


def runtime_dependencies(path):
    if path is None:return [],[]
    runtime=json.loads(Path(path).read_text(encoding='utf-8'))
    if runtime.get('schema_version')!=1:raise ValueError('Unknown Android wake runtime schema.')
    jars=[];files=[];entries=set()
    for item in runtime['jars']:
        file=Path(item['path']).resolve()
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Android runtime jar checksum mismatch.')
        jars.append(file)
    for item in runtime['files']:
        file=Path(item['path']).resolve();entry=item['entry']
        if (not entry.startswith(('lib/','assets/voice/')) or '..' in entry.split('/') or '\\' in entry or entry in entries):
            raise ValueError('Invalid Android runtime archive path.')
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Android runtime asset checksum mismatch.')
        entries.add(entry);files.append((file,entry))
    return jars,files


def recompress_apk(source,target):
    """Deflate ordinary entries at level 9; native code/resource tables stay raw.

    zipalign runs afterward, then the APK is signed. Model bytes are unchanged
    when extracted and retain the runtime's per-file checksum guarantees.
    """
    with zipfile.ZipFile(source) as original,zipfile.ZipFile(target,'w') as result:
        for entry in original.infolist():
            if entry.filename.startswith('lib/') or entry.filename=='resources.arsc':
                method=zipfile.ZIP_STORED
            else:
                method=zipfile.ZIP_DEFLATED
            result.writestr(entry,original.read(entry.filename),compress_type=method,compresslevel=9)
    return target


def build(sdk,output,signing,wake_runtime=None,assets=None,firebase_config=None,workspace=None,require_existing_signing=False):
    sdk=Path(sdk).resolve();output=Path(output).resolve();signing=Path(signing).resolve()
    tools=sdk/'build-tools/35.0.0';platform=sdk/'platforms/android-35/android.jar'
    key=signing/'companion.p12';password=signing/'password.txt'
    strict_signing=require_existing_signing or os.environ.get('CI','').lower()=='true'
    if strict_signing and (not key.is_file() or not password.is_file() or not password.read_text(encoding='utf-8').strip()):raise ValueError('Release CI requires the existing signing key and password file; it must never create a new identity.')
    if key.is_file() and not password.is_file():raise ValueError('The existing signing identity needs its protected password file.')
    if not platform.is_file():raise ValueError('Install platforms;android-35 and build-tools;35.0.0 with the Android SDK manager.')
    output.parent.mkdir(parents=True,exist_ok=True)
    workspace=Path(workspace).resolve() if workspace else ROOT/'state/android-build';workspace.mkdir(parents=True,exist_ok=True)
    app=ROOT/'apps/android'
    jars,runtime_files=runtime_dependencies(wake_runtime)
    from android_gradle_build import compile_unsigned
    unsigned=compile_unsigned(sdk,workspace,jars,runtime_files,assets,firebase_config,root=ROOT)
    unsigned=recompress_apk(unsigned,workspace/'recompressed.apk')
    aligned=workspace/'aligned.apk'
    zipalign=tools/('zipalign.exe' if os.name=='nt' else 'zipalign');apksigner=tools/('apksigner.bat' if os.name=='nt' else 'apksigner')
    run([zipalign,'-P','16','-f','4',unsigned,aligned])
    signing.mkdir(parents=True,exist_ok=True);key=signing/'companion.p12';password=signing/'password.txt'
    if not key.exists():
        if not password.exists():password.write_text(secrets.token_urlsafe(32),encoding='utf-8')
        run(['keytool','-genkeypair','-keystore',key,'-storetype','PKCS12','-alias','companion','-keyalg','RSA','-keysize','3072',
             '-validity','10000','-dname','CN=Personal Assistant Companion','-storepass:file',password])
    run([apksigner,'sign','--ks',key,'--ks-key-alias','companion','--ks-pass','file:'+str(password),
         '--out',output,aligned])
    run([apksigner,'verify','--verbose',output])
    manifest=ET.parse(app/'AndroidManifest.xml').getroot();namespace='{http://schemas.android.com/apk/res/android}'
    release={'package_name':manifest.attrib['package'],'version_code':int(manifest.attrib[namespace+'versionCode']),
             'version_name':manifest.attrib[namespace+'versionName'],'min_sdk':26,
             'size':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
    if assets or (wake_runtime and json.loads(Path(wake_runtime).read_text(encoding='utf-8')).get('diagnostic_only')):
        release['diagnostic_only']=True
    if assets:release['contains_private_audio_fixture']=True
    release['native_push_configured']=bool(firebase_config)
    output.with_suffix('.release.json').write_text(json.dumps(release,indent=2),encoding='utf-8')
    return {'apk':str(output),'size':output.stat().st_size,'signed':True,'handset_tested':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk',type=Path,default=Path.home()/'.personal-assistant/android-sdk')
    parser.add_argument('--output',type=Path,default=ROOT/'state/exports/assistant-companion.apk')
    parser.add_argument('--signing',type=Path,default=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'PersonalAssistant/secrets/android-signing')
    parser.add_argument('--wake-runtime',type=Path,help='Optional pinned AAR/JNI/model runtime.json generated by fetch_wake_runtime.py')
    parser.add_argument('--assets',type=Path,help='Optional private voice fixture/template assets directory (no credentials)')
    parser.add_argument('--firebase-config',type=Path,default=Path(os.environ['ASSISTANT_FIREBASE_CONFIG']) if os.environ.get('ASSISTANT_FIREBASE_CONFIG') else None,help='External google-services.json for native push; never tracked')
    parser.add_argument('--workspace',type=Path,help='Optional isolated build state directory')
    parser.add_argument('--require-existing-signing',action='store_true',help='Fail instead of generating a new signing identity (always enforced in CI)')
    args=parser.parse_args();print(json.dumps(build(args.sdk,args.output,args.signing,args.wake_runtime,args.assets,args.firebase_config,args.workspace,args.require_existing_signing)))
