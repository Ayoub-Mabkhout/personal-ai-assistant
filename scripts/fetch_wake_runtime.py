"""Prepare pinned Sherpa Android dependencies outside the public checkout.

Use --model-dir and --keywords after evaluating the wake model. No API key is
required. The builder consumes the generated runtime.json without Gradle.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile


AAR='sherpa-onnx-static-link-onnxruntime-1.13.8.aar'
AAR_URL='https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.13.8/'+AAR
AAR_HASH='b22c3fc1b6a45666d28892bb2f7694beeb77a8362d7ebd77c1a5431ec9435471'
KOTLIN='kotlin-stdlib-1.9.25.jar'
KOTLIN_URL='https://repo.maven.apache.org/maven2/org/jetbrains/kotlin/kotlin-stdlib/1.9.25/'+KOTLIN
KOTLIN_HASH='f9cdcdbff1f5de85380ae526977e683726c2aa42db1ed6e6e50ae89e496e95fd'


def sha(file):
    return hashlib.sha256(Path(file).read_bytes()).hexdigest()


def download(url,destination,expected):
    destination=Path(destination)
    if destination.is_file() and sha(destination)==expected:return
    partial=destination.with_suffix(destination.suffix+'.part')
    try:
        with urllib.request.urlopen(url,timeout=45) as response,partial.open('wb') as out:
            shutil.copyfileobj(response,out)
        if sha(partial)!=expected:raise ValueError('Dependency checksum mismatch: '+destination.name)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def prepare(cache,model_dir,keywords,abis):
    cache=Path(cache).resolve();cache.mkdir(parents=True,exist_ok=True)
    download(AAR_URL,cache/AAR,AAR_HASH)
    download(KOTLIN_URL,cache/KOTLIN,KOTLIN_HASH)
    libraries=[];files=[]
    with zipfile.ZipFile(cache/AAR) as archive:
        classes=cache/'sherpa-classes.jar';classes.write_bytes(archive.read('classes.jar'));libraries.append(classes)
        for abi in abis:
            names=[n for n in archive.namelist() if n.startswith('jni/'+abi+'/') and n.endswith('.so')]
            if not names:raise ValueError('Unsupported ABI in pinned Sherpa AAR: '+abi)
            for name in names:
                destination=cache/'native'/abi/Path(name).name
                destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(archive.read(name))
                files.append({'path':str(destination),'entry':'lib/'+abi+'/'+destination.name,'sha256':sha(destination)})
    libraries.append(cache/KOTLIN)
    assets=cache/'assets/voice/sherpa';assets.mkdir(parents=True,exist_ok=True)
    for name in ('encoder','decoder','joiner'):
        candidates=list(Path(model_dir).glob(name+'-*.onnx'))
        # Prefer the lower-latency chunk8 export and int8 where supplied. Decode
        # weights may only be fp32; all three files must use the same chunk size.
        chunk='chunk-8-' if any('chunk-8-' in file.name for file in candidates) else 'chunk-16-'
        candidates=[file for file in candidates if chunk in file.name]
        candidates.sort(key=lambda file:(not file.name.endswith('.int8.onnx'),file.name))
        if not candidates:raise ValueError('Model file missing: '+name)
        source=candidates[0]
        destination=assets/(name+'.onnx');shutil.copyfile(source,destination)
    shutil.copyfile(Path(model_dir)/'tokens.txt',assets/'tokens.txt')
    shutil.copyfile(keywords,assets/'keywords.txt')
    for asset in assets.iterdir():
        files.append({'path':str(asset),'entry':'assets/voice/sherpa/'+asset.name,'sha256':sha(asset)})
    license_dir=cache/'assets/voice/licenses';license_dir.mkdir(parents=True,exist_ok=True)
    license_sources={'sherpa-onnx-LICENSE.txt':'https://raw.githubusercontent.com/k2-fsa/sherpa-onnx/v1.13.8/LICENSE',
        'onnxruntime-LICENSE.txt':'https://raw.githubusercontent.com/microsoft/onnxruntime/v1.24.2/LICENSE',
        'kotlin-LICENSE.txt':'https://raw.githubusercontent.com/JetBrains/kotlin/v1.9.25/license/LICENSE.txt'}
    for filename,url in license_sources.items():
        destination=license_dir/filename
        if not destination.exists():
            with urllib.request.urlopen(url,timeout=30) as response:destination.write_bytes(response.read())
        files.append({'path':str(destination),'entry':'assets/voice/licenses/'+filename,'sha256':sha(destination)})
    runtime={'schema_version':1,'sherpa_version':'1.13.8','model':Path(model_dir).name,
        'source_urls':[AAR_URL,KOTLIN_URL],'aar_sha256':AAR_HASH,
        'jars':[{'path':str(file),'sha256':sha(file)} for file in libraries],'files':files}
    output=cache/'runtime.json';output.write_text(json.dumps(runtime,indent=2),encoding='utf-8')
    return {'runtime':str(output),'abis':abis,'files':len(files),'handset_tested':False}


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--cache',type=Path,default=Path.home()/'.personal-assistant/android-wake')
    cli.add_argument('--model-dir',type=Path,required=True)
    cli.add_argument('--keywords',type=Path,required=True)
    cli.add_argument('--abis',nargs='+',choices=['arm64-v8a','x86_64','armeabi-v7a','x86'],default=['arm64-v8a'])
    args=cli.parse_args();print(json.dumps(prepare(args.cache,args.model_dir,args.keywords,args.abis)))
