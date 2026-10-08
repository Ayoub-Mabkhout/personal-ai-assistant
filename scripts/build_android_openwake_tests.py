"""Build private ORT instrumentation fixtures; never publish this diagnostic APK."""
import argparse
import os
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def run(command):subprocess.run([str(v) for v in command],check=True)


def build(sdk,fixtures,signing):
    sdk=Path(sdk);fixtures=Path(fixtures);signing=Path(signing)
    for name in ('input.pcm','reference.json'):
        if not (fixtures/name).is_file():raise ValueError('Missing private parity fixture: '+name)
    tools=sdk/'build-tools/35.0.0';platform=sdk/'platforms/android-35/android.jar'
    workspace=ROOT/'state/android-openwake-tests';workspace.mkdir(parents=True,exist_ok=True)
    classes=workspace/'classes';classes.mkdir(exist_ok=True);dex=workspace/'dex';dex.mkdir(exist_ok=True)
    run([tools/'aapt2.exe','link','-I',platform,'--manifest',ROOT/'tests/android/OpenWakeManifest.xml','-A',fixtures,'-o',workspace/'resources.apk'])
    run(['javac','-encoding','UTF-8','--release','8','-classpath',str(platform)+os.pathsep+str(ROOT/'state/android-build/classes'),
         '-d',classes,ROOT/'tests/android/OpenWakeInstrumentation.java'])
    run([tools/'d8.bat','--lib',platform,'--classpath',ROOT/'state/android-build/classes','--min-api','26','--output',dex,*classes.glob('**/*.class')])
    unsigned=workspace/'unsigned.apk';unsigned.write_bytes((workspace/'resources.apk').read_bytes())
    with zipfile.ZipFile(unsigned,'a') as archive:
        for file in dex.glob('*.dex'):archive.write(file,file.name)
    run([tools/'zipalign.exe','-f','4',unsigned,workspace/'aligned.apk'])
    output=workspace/'openwake-tests.apk'
    run([tools/'apksigner.bat','sign','--ks',signing/'companion.p12','--ks-key-alias','companion','--ks-pass','file:'+str(signing/'password.txt'),
         '--out',output,workspace/'aligned.apk'])
    run([tools/'apksigner.bat','verify',output]);print(output)


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--sdk',type=Path,default=Path.home()/'.personal-assistant/android-sdk')
    cli.add_argument('--fixtures',type=Path,required=True)
    cli.add_argument('--signing',type=Path,default=Path(os.environ['LOCALAPPDATA'])/'PersonalAssistant/secrets/android-signing')
    args=cli.parse_args();build(args.sdk,args.fixtures,args.signing)
