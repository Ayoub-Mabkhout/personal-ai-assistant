"""Build timer instrumentation for an isolated unpaired emulator, never release it."""
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(command):
    subprocess.run(list(map(str, command)), check=True)


def main():
    sdk = Path.home() / '.personal-assistant/android-sdk'
    tools, platform = sdk / 'build-tools/35.0.0', sdk / 'platforms/android-35/android.jar'
    work = ROOT / 'state/timer-tests'
    classes, dex = work / 'classes', work / 'dex'
    classes.mkdir(parents=True, exist_ok=True)
    dex.mkdir(exist_ok=True)
    signing = ROOT / 'state/timer-signing'
    run([tools / 'aapt2.exe', 'link', '-I', platform, '--manifest', ROOT / 'tests/android/TimerManifest.xml', '-o', work / 'resources.apk'])
    run(['javac', '-encoding', 'UTF-8', '--release', '8', '-classpath', str(platform) + os.pathsep + str(ROOT / 'state/timer-build/classes'), '-d', classes, ROOT / 'tests/android/TimerInstrumentation.java'])
    run([tools / 'd8.bat', '--lib', platform, '--classpath', ROOT / 'state/timer-build/classes', '--min-api', '26', '--output', dex, *classes.glob('**/*.class')])
    unsigned = work / 'unsigned.apk'
    unsigned.write_bytes((work / 'resources.apk').read_bytes())
    with zipfile.ZipFile(unsigned, 'a') as archive:
        for file in dex.glob('*.dex'):
            archive.write(file, file.name)
    run([tools / 'zipalign.exe', '-f', '4', unsigned, work / 'aligned.apk'])
    output = work / 'timer-tests.apk'
    run([tools / 'apksigner.bat', 'sign', '--ks', signing / 'companion.p12', '--ks-key-alias', 'companion', '--ks-pass', 'file:' + str(signing / 'password.txt'), '--out', output, work / 'aligned.apk'])
    run([tools / 'apksigner.bat', 'verify', output])
    print(output)


if __name__ == '__main__':
    main()
