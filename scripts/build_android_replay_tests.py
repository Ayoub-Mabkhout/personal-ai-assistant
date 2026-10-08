"""Build framework-only runner for the private emulator production-loop diagnostic target."""
import os
from pathlib import Path
import subprocess
import zipfile
ROOT=Path(__file__).resolve().parents[1]

def run(args):subprocess.run([str(item) for item in args],check=True)

def main():
    sdk=Path.home()/'.personal-assistant/android-sdk';tools=sdk/'build-tools/35.0.0';platform=sdk/'platforms/android-35/android.jar'
    signing=Path(os.environ['LOCALAPPDATA'])/'PersonalAssistant/secrets/android-signing';work=ROOT/'state/android-replay-tests';classes=work/'classes';dex=work/'dex';classes.mkdir(parents=True,exist_ok=True);dex.mkdir(exist_ok=True)
    run([tools/'aapt2.exe','link','-I',platform,'--manifest',ROOT/'tests/android/replay/TestManifest.xml','-o',work/'resources.apk'])
    run(['javac','-encoding','UTF-8','--release','8','-classpath',platform,'-d',classes,ROOT/'tests/android/replay/ReplayInstrumentation.java'])
    run([tools/'d8.bat','--lib',platform,'--min-api','26','--output',dex,*classes.glob('**/*.class')])
    unsigned=work/'unsigned.apk';unsigned.write_bytes((work/'resources.apk').read_bytes())
    with zipfile.ZipFile(unsigned,'a') as archive:
        for file in dex.glob('*.dex'):archive.write(file,file.name)
    run([tools/'zipalign.exe','-f','4',unsigned,work/'aligned.apk']);output=work/'replay-tests.apk'
    run([tools/'apksigner.bat','sign','--ks',signing/'companion.p12','--ks-key-alias','companion','--ks-pass','file:'+str(signing/'password.txt'),'--out',output,work/'aligned.apk']);run([tools/'apksigner.bat','verify',output]);print(output)

if __name__=='__main__':main()
