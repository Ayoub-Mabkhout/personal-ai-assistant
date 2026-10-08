"""Prepare an evaluated custom openWakeWord model and pinned Android ORT.

All generated jars, native libraries and model assets remain outside tracked files.
Only prepare a classifier after its independent replay metrics are acceptable.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

from fetch_wake_runtime import download,sha

AAR='onnxruntime-android-1.24.2.aar'
URL='https://repo.maven.apache.org/maven2/com/microsoft/onnxruntime/onnxruntime-android/1.24.2/'+AAR
HASH='bc461499a735653dff285a6a3477d28b9cfd119a09c7753eaf003426b577f223'
BACKBONES={'melspectrogram.onnx':'ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f',
           'embedding_model.onnx':'70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f'}


def prepare(cache,backbone,classifier,settings,abis):
    cache=Path(cache).resolve();cache.mkdir(parents=True,exist_ok=True)
    config=json.loads(Path(settings).read_text(encoding='utf-8'))
    if config.get('schema_version')!=1 or config.get('sample_rate')!=16000 or config.get('hop_samples')!=1280:
        raise ValueError('Unsupported openWakeWord streaming settings.')
    if not 0<float(config.get('threshold',0))<1:raise ValueError('An evaluated classifier threshold is required.')
    feature_type=config.get('feature_type','embedding')
    if feature_type not in ('embedding','logmel-cnn'):raise ValueError('Unsupported classifier feature type.')
    if config.get('diagnostic_no_activation') and not config.get('diagnostic_only'):
        raise ValueError('Disabled activation is only supported for diagnostic models.')
    download(URL,cache/AAR,HASH)
    files=[]
    with zipfile.ZipFile(cache/AAR) as archive:
        jar=cache/'onnxruntime-classes.jar';jar.write_bytes(archive.read('classes.jar'))
        for abi in abis:
            names=[n for n in archive.namelist() if n.startswith('jni/'+abi+'/') and n.endswith('.so')]
            if not names:raise ValueError('ABI not included in pinned ONNX Runtime: '+abi)
            for name in names:
                destination=cache/'native'/abi/Path(name).name
                destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(archive.read(name))
                files.append({'path':str(destination),'entry':'lib/'+abi+'/'+destination.name,'sha256':sha(destination)})
    assets=cache/'assets/voice/openwake';assets.mkdir(parents=True,exist_ok=True)
    selected=['melspectrogram.onnx']+(['embedding_model.onnx'] if feature_type=='embedding' else [])
    for name in selected:
        expected=BACKBONES[name]
        source=Path(backbone)/name
        if sha(source)!=expected:raise ValueError('Frozen feature model checksum mismatch: '+name)
        shutil.copyfile(source,assets/name)
    classifier=Path(classifier)
    if config.get('classifier_sha256')!=sha(classifier):raise ValueError('Classifier differs from evaluated settings.')
    shutil.copyfile(classifier,assets/'classifier.onnx');shutil.copyfile(settings,assets/'settings.json')
    for name in [*selected,'classifier.onnx','settings.json']:
        asset=assets/name;files.append({'path':str(asset),'entry':'assets/voice/openwake/'+asset.name,'sha256':sha(asset)})
    license_dir=cache/'assets/voice/licenses';license_dir.mkdir(parents=True,exist_ok=True)
    sources={'onnxruntime-LICENSE.txt':'https://raw.githubusercontent.com/microsoft/onnxruntime/v1.24.2/LICENSE',
             'openwakeword-LICENSE.txt':'https://raw.githubusercontent.com/dscripka/openWakeWord/v0.6.0/LICENSE',
             'pretrained-models-CC-BY-NC-SA-4.0.txt':'https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.txt'}
    for name,url in sources.items():
        destination=license_dir/name
        if not destination.exists():
            request=urllib.request.Request(url,headers={'User-Agent':'AssistantCompanionBuilder/0.3'})
            with urllib.request.urlopen(request,timeout=30) as response:destination.write_bytes(response.read())
        files.append({'path':str(destination),'entry':'assets/voice/licenses/'+name,'sha256':sha(destination)})
    runtime={'schema_version':1,'onnxruntime_version':'1.24.2','source_urls':[URL],
        'diagnostic_only':bool(config.get('diagnostic_only',False)),
        'aar_sha256':HASH,'jars':[{'path':str(jar),'sha256':sha(jar)}],'files':files}
    output=cache/'runtime.json';output.write_text(json.dumps(runtime,indent=2),encoding='utf-8')
    return {'runtime':str(output),'abis':abis,'handset_tested':False}


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--cache',type=Path,default=Path.home()/'.personal-assistant/android-openwake')
    cli.add_argument('--backbone',type=Path,required=True)
    cli.add_argument('--classifier',type=Path,required=True)
    cli.add_argument('--settings',type=Path,required=True)
    cli.add_argument('--abis',nargs='+',choices=['arm64-v8a','x86_64','armeabi-v7a','x86'],default=['arm64-v8a'])
    args=cli.parse_args();print(json.dumps(prepare(args.cache,args.backbone,args.classifier,args.settings,args.abis)))
