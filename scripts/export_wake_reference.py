"""Export private, deterministic streaming vectors for Android ONNX parity tests."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from openwakeword.utils import AudioFeatures
from train_personal_wake import wav_read, reset_features


def export(model_root, clip, output, frontend_root=None, feature_type='embedding'):
    output.mkdir(parents=True,exist_ok=True)
    if feature_type=='logmel-cnn':
        from train_wake_cnn import frontend,raw_windows
        mel_path=(frontend_root or model_root)/'backbone/melspectrogram.onnx'
        head_path=model_root/'hey_chat_logmel_cnn.onnx'
        head=ort.InferenceSession(str(head_path),providers=['CPUExecutionProvider'])
        pcm=np.concatenate([np.zeros(48000,np.int16),wav_read(clip).astype(np.int16),np.zeros(16000,np.int16)])
        (output/'input.pcm').write_bytes(pcm.astype('<i2').tobytes())
        values=raw_windows(pcm,frontend(mel_path),cold=True);frames=[]
        for index,value in enumerate(values):
            score=float(head.run(None,{'input':value[None,None]})[0][0,0])
            frames.append({'index':index,'samples_processed':(index+1)*1280,
                'last_mel_frames':value[-8:].astype(float).tolist(),
                'classifier_input':value.astype(float).tolist(),'probability':score,
                'scoring_enabled':index>=26})
        report={'feature_type':'logmel-cnn','sample_rate':16000,'sample_width':2,'byte_order':'little',
            'frame_samples':1280,'pcm_sha256':hashlib.sha256((output/'input.pcm').read_bytes()).hexdigest(),
            'initial_mel':'196x32 ones','warmup_blocks':26,'first_scored_block_index':26,
            'source_clip_sha256':hashlib.sha256(clip.read_bytes()).hexdigest(),'frames':frames,
            'models':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [head_path,mel_path]}}
        (output/'reference.json').write_text(json.dumps(report,separators=(',',':')),encoding='utf-8')
        print(json.dumps({'output':str(output),'frames':len(frames),'feature_type':'logmel-cnn',
            'max_probability':max(f['probability'] for f in frames[26:])}))
        return
    features=AudioFeatures(melspec_model_path=str(model_root/"backbone/melspectrogram.onnx"),
        embedding_model_path=str(model_root/"backbone/embedding_model.onnx"),inference_framework="onnx",ncpu=1)
    reset_features(features)
    head=ort.InferenceSession(str(model_root/"hey_chat.onnx"),providers=["CPUExecutionProvider"])
    pcm=np.concatenate([np.zeros(48000,np.int16),wav_read(clip).astype(np.int16),np.zeros(16000,np.int16)])
    (output/"input.pcm").write_bytes(pcm.astype("<i2").tobytes())
    frames=[]
    for offset in range(0,len(pcm),1280):
        block=pcm[offset:offset+1280]
        if len(block)<1280:block=np.pad(block,(0,1280-len(block)))
        features(block);vector=features.get_features(16)
        score=float(head.run(None,{"input":vector})[0][0,0])
        frames.append({"index":offset//1280,"samples_processed":offset+1280,
            "last_mel_frames":features.melspectrogram_buffer[-8:].astype(float).tolist(),
            "embedding":features.feature_buffer[-1].astype(float).tolist(),
            "classifier_input":vector[0].astype(float).tolist(),"probability":score})
    report={"sample_rate":16000,"sample_width":2,"byte_order":"little","frame_samples":1280,
        "pcm_sha256":hashlib.sha256((output/"input.pcm").read_bytes()).hexdigest(),
        "initial_mel":"76x32 ones","initial_embeddings":"16x96 zeros","warmup_blocks":26,
        "source_clip_sha256":hashlib.sha256(clip.read_bytes()).hexdigest(),"frames":frames,
        "models":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [model_root/"hey_chat.onnx",*sorted((model_root/"backbone").glob("*.onnx"))]}}
    (output/"reference.json").write_text(json.dumps(report,separators=(",",":")),encoding="utf-8")
    print(json.dumps({"output":str(output),"frames":len(frames),"max_probability":max(f["probability"] for f in frames[26:])}))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root",type=Path,required=True);parser.add_argument("--clip",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument('--frontend-root',type=Path)
    parser.add_argument('--feature-type',choices=['embedding','logmel-cnn'],default='embedding')
    args=parser.parse_args();export(args.model_root,args.clip,args.output,args.frontend_root,args.feature_type)
