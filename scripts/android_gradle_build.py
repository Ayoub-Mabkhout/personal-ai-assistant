"""Stage portable Android inputs and compile with the pinned official AGP wrapper."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def stage_inputs(work, jars, runtime_files, assets=None, firebase=None, root=ROOT):
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    # Only this task-owned input directory is pruned; model caches and credentials
    # are immutable sources. This also removes old diagnostic assets on rebuild.
    staged = work / 'inputs'
    if staged.exists():
        if not staged.resolve().is_relative_to(work):
            raise ValueError('Android input directory escaped its build workspace.')
        shutil.rmtree(staged)
    staged.mkdir()
    manifest = ET.parse(Path(root) / 'apps/android/AndroidManifest.xml')
    manifest.getroot().attrib.pop('package', None)
    application = manifest.getroot().find('application')
    if application is not None:
        # Gradle derives diagnostic debuggability from the source manifest, then
        # applies it through the build type; the merged source must not hard-code
        # this flag or release lint correctly rejects it.
        application.attrib.pop('{http://schemas.android.com/apk/res/android}debuggable', None)
    ET.register_namespace('android', 'http://schemas.android.com/apk/res/android')
    manifest.write(staged / 'AndroidManifest.xml', encoding='utf-8', xml_declaration=True)
    entries = set()
    for jar in jars:
        digest = hashlib.sha256(Path(jar).read_bytes()).hexdigest()[:12]
        target = staged / 'jars' / f'{digest}-{Path(jar).name}'
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(jar, target)
    for source, entry in runtime_files:
        if entry.startswith('assets/'):
            relative = Path('assets') / entry[7:]
        elif entry.startswith('lib/'):
            relative = Path('jniLibs') / entry[4:]
        else:
            raise ValueError('Unsupported Android runtime file.')
        target = staged / relative
        if not target.resolve().is_relative_to(staged):
            raise ValueError('Runtime asset escaped staging.')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        entries.add(relative.as_posix())
    if assets:
        for source in Path(assets).rglob('*'):
            if source.is_file():
                relative = Path('assets') / source.relative_to(assets)
                if relative.as_posix() in entries:
                    raise ValueError('Duplicate Android asset.')
                target = staged / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    if firebase:
        firebase_resources(Path(firebase), staged / 'res/values/firebase.xml')
    return staged


def firebase_resources(config, output):
    """Official Google-services mapping, without copying account metadata to Git."""
    value = json.loads(config.read_text(encoding='utf-8'))
    clients = [c for c in value.get('client', []) if c.get('client_info', {}).get('android_client_info', {}).get('package_name') == 'com.personalassistant.companion']
    if len(clients) != 1:
        raise ValueError('Firebase configuration must contain this Android application exactly once.')
    project, client = value['project_info'], clients[0]
    keys = client.get('api_key', [])
    if not keys:
        raise ValueError('Firebase Android configuration has no public API key.')
    strings = {'google_app_id': client['client_info']['mobilesdk_app_id'],
               'gcm_defaultSenderId': str(project['project_number']),
               'project_id': project['project_id'],
               'google_api_key': keys[0]['current_key']}
    root = ET.Element('resources', {'xmlns:tools': 'http://schemas.android.com/tools', 'tools:keep': ','.join('@string/'+name for name in strings)})
    for name, value in strings.items():
        ET.SubElement(root, 'string', {'name': name, 'translatable': 'false'}).text = str(value)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output, encoding='utf-8', xml_declaration=True)


def compile_unsigned(sdk, work, jars, runtime_files, assets=None, firebase=None, root=ROOT):
    work = Path(work).resolve()
    staged = stage_inputs(work, jars, runtime_files, assets, firebase, root)
    app = Path(root) / 'apps/android'
    wrapper = app / ('gradlew.bat' if os.name == 'nt' else 'gradlew')
    env = dict(os.environ, ANDROID_HOME=str(Path(sdk).resolve()), ANDROID_SDK_ROOT=str(Path(sdk).resolve()))
    # Execute the official wrapper directly through its supported host shell.
    command = [str(wrapper), '--no-daemon', '--console=plain', '--project-cache-dir', str(work / 'cache'),
               f'-PassistantInputs={staged}', f'-PassistantBuildRoot={work / "gradle"}', 'assembleRelease']
    if os.name != 'nt':
        command.insert(0, 'sh')
    subprocess.run(command, cwd=app, env=env, check=True)
    artifact = work / 'gradle/outputs/apk/release/assistant-companion-release-unsigned.apk'
    if not artifact.is_file():
        candidates = list((work / 'gradle/outputs/apk/release').glob('*-release-unsigned.apk'))
        if len(candidates) != 1:
            raise ValueError('Gradle did not produce the expected unsigned release APK.')
        artifact = candidates[0]
    # Existing standalone native instrumentation builders use this classpath.
    classes = work / 'classes'
    if classes.exists():
        if not classes.resolve().is_relative_to(work):
            raise ValueError('Android classes escaped their build workspace.')
        shutil.rmtree(classes)
    source = work / 'gradle/intermediates/javac/release/compileReleaseJavaWithJavac/classes'
    shutil.copytree(source, classes)
    generated_r = list((work / 'gradle/intermediates/compile_and_runtime_not_namespaced_r_class_jar').rglob('R.jar'))
    if len(generated_r) != 1:
        raise ValueError('Missing Android generated resource classes.')
    with zipfile.ZipFile(generated_r[0]) as archive:
        for name in archive.namelist():
            if name.endswith('.class') and '..' not in Path(name).parts:
                target = classes / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
    return artifact
