"""Replay independent synthetic fixtures using a previously frozen wake policy."""
import argparse
import json
from pathlib import Path
import time

import numpy as np
import onnxruntime as ort
from openwakeword.utils import AudioFeatures
from benchmark_sherpa_candidates import make_engine,replay
from train_personal_wake import wav_read,sha,reset_features,RATE


def main(args):
    manifest=json.loads(args.manifest.read_text());out=args.output;out.mkdir(parents=True,exist_ok=True)
    if (out/'evaluation.json').exists():raise ValueError('Preserve prior regression report')
    if args.engine=='sherpa':
        policy=json.loads((args.policy_root/'selection.json').read_text())['selected']
        engine=make_engine(args.model,policy['config'],out)
    else:
        policy=json.loads((args.policy_root/'policy.json').read_text())
        head_path=args.policy_root/'hey_chat_temporal.onnx'
        if sha(head_path)!=policy['model_sha256']:raise ValueError('Changed model')
        options=ort.SessionOptions();options.intra_op_num_threads=2
        head=ort.InferenceSession(str(head_path),sess_options=options,providers=['CPUExecutionProvider'])
        features=AudioFeatures(melspec_model_path=str(args.model/'backbone/melspectrogram.onnx'),
            embedding_model_path=str(args.model/'backbone/embedding_model.onnx'),inference_framework='onnx',ncpu=1)
    (out/'frozen-policy.json').write_text(json.dumps(policy,indent=2))
    rows=[]
    for item in manifest['clips']:
        path=Path(item['path'])
        if item.get('sha256') and sha(path)!=item['sha256']:raise ValueError('Fixture source hash changed')
        pcm=wav_read(path).astype(np.int16);stamp=time.perf_counter()
        if args.engine=='sherpa':events,cost=replay(engine,pcm.astype(np.float32)/32768.)
        else:
            reset_features(features)
            for _ in range(38):features(np.zeros(1280,np.int16))
            padded=np.concatenate([pcm,np.zeros(RATE,np.int16)]);events=[];scores=[]
            for offset in range(0,len(padded),1280):
                block=padded[offset:offset+1280]
                if len(block)<1280:block=np.pad(block,(0,1280-len(block)))
                features(block);score=float(head.run(None,{'input':features.get_features(16)})[0][0,0]);scores.append(score)
                if score>=policy['threshold'] and (not events or (offset+1280)/RATE-events[-1]['activation_seconds']>=3):
                    events.append({'activation_seconds':(offset+1280)/RATE,'probability':score})
            cost=time.perf_counter()-stamp
        rows.append(dict(item,events=events,detected=bool(events),replay_seconds=cost))
    summary={'positives':sum(r['wake_expected'] for r in rows),'detected':sum(r['wake_expected'] and r['detected'] for r in rows),
        'negatives':sum(not r['wake_expected'] for r in rows),'false':sum(not r['wake_expected'] and r['detected'] for r in rows),
        'no_wake_false':sum(r['kind']=='no-wake' and r['detected'] for r in rows),
        'confusable_false':sum(r['kind']=='confusable' and r['detected'] for r in rows)}
    report={'engine':args.engine,'policy':policy,'manifest_sha256':sha(args.manifest),'summary':summary,'samples':rows,
        'diagnostic_only':True,'acceptance_passed':False,'limitations':['Independent provider TTS is synthetic regression, not fresh human field evidence',
            'No threshold selection from these fixtures','One-take keyword end not annotated; timestamps are relative to clip start']}
    (out/'evaluation.json').write_text(json.dumps(report,indent=2));print(json.dumps(summary))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--engine',choices=['sherpa','embedding-temporal'],required=True)
    p.add_argument('--policy-root',type=Path,required=True);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    main(p.parse_args())
