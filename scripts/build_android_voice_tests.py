"""Build same-signed Android instrumentation APK from private PCM fixtures."""
import argparse
import os
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def run(args):
    subprocess.run([str(x) for x in args],check=True)

def build(sdk,fixtures,signing):
    sdk=Path(sdk); fixtures=Path(fixtures); signing=Path(signing)
    for name in ('template.pcm','positive.pcm','negative.pcm'):
        if not (fixtures/name).is_file(): raise ValueError(f'Missing private fixture {name}')
    tools=sdk/'build-tools/35.0.0';platform=sdk/'platforms/android-35/android.jar'
    work=ROOT/'state/android-voice-tests';work.mkdir(parents=True,exist_ok=True)
    classes=work/'classes';classes.mkdir(exist_ok=True)
    dex=work/'dex';dex.mkdir(exist_ok=True)
    run([tools/'aapt2.exe','link','-I',platform,'--manifest',ROOT/'tests/android/AndroidManifest.xml','-A',fixtures,'-o',work/'resources.apk'])
    classpath=str(platform)+os.pathsep+str(ROOT/'state/android-build/classes')
    run(['javac','-encoding','UTF-8','--release','8','-classpath',classpath,'-d',classes,ROOT/'tests/android/VoiceInstrumentation.java'])
    run([tools/'d8.bat','--lib',platform,'--classpath',ROOT/'state/android-build/classes','--min-api','26','--output',dex,*classes.glob('**/*.class')])
    unsigned=work/'unsigned.apk';unsigned.write_bytes((work/'resources.apk').read_bytes())
    with zipfile.ZipFile(unsigned,'a') as archive:
        for file in dex.glob('*.dex'):archive.write(file,file.name)
    run([tools/'zipalign.exe','-f','4',unsigned,work/'aligned.apk'])
    output=work/'voice-tests.apk'
    run([tools/'apksigner.bat','sign','--ks',signing/'companion.p12','--ks-key-alias','companion','--ks-pass','file:'+str(signing/'password.txt'),'--out',output,work/'aligned.apk'])
    run([tools/'apksigner.bat','verify',output]);print(output)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk',type=Path,default=Path.home()/'.personal-assistant/android-sdk')
    parser.add_argument('--fixtures',type=Path,required=True)
    parser.add_argument('--signing',type=Path,default=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'PersonalAssistant/secrets/android-signing')
    args=parser.parse_args();build(args.sdk,args.fixtures,args.signing)
