"""Build emulator-only keyguard instrumentation without touching app build outputs."""
import os
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def run(args):subprocess.run([str(x) for x in args],check=True)

def main():
    sdk=Path.home()/'.personal-assistant/android-sdk';tools=sdk/'build-tools/35.0.0';platform=sdk/'platforms/android-35/android.jar'
    signing=Path(os.environ['LOCALAPPDATA'])/'PersonalAssistant/secrets/android-signing'
    work=ROOT/'state/android-keyguard-tests';work.mkdir(parents=True,exist_ok=True)
    classes=work/'classes';classes.mkdir(exist_ok=True);dex=work/'dex';dex.mkdir(exist_ok=True)
    run([tools/'aapt2.exe','link','-I',platform,'--manifest',ROOT/'tests/android/KeyguardManifest.xml','-o',work/'resources.apk'])
    run(['javac','-encoding','UTF-8','--release','8','-classpath',platform,'-d',classes,ROOT/'tests/android/KeyguardInstrumentation.java'])
    run([tools/'d8.bat','--lib',platform,'--min-api','26','--output',dex,*classes.glob('**/*.class')])
    unsigned=work/'unsigned.apk';unsigned.write_bytes((work/'resources.apk').read_bytes())
    with zipfile.ZipFile(unsigned,'a') as archive:
        for file in dex.glob('*.dex'):archive.write(file,file.name)
    run([tools/'zipalign.exe','-f','4',unsigned,work/'aligned.apk']);output=work/'keyguard-tests.apk'
    run([tools/'apksigner.bat','sign','--ks',signing/'companion.p12','--ks-key-alias','companion','--ks-pass','file:'+str(signing/'password.txt'),'--out',output,work/'aligned.apk'])
    run([tools/'apksigner.bat','verify',output]);print(output)

if __name__=='__main__':main()
