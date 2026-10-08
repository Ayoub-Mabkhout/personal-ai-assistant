"""Measure frozen-head streaming latency and untouched continuous speech negatives."""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import onnxruntime as ort
from openwakeword.utils import AudioFeatures
from train_personal_wake import RATE,reset_features,wav_read,sha


def main(args):
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    if (root/'evaluation.json').exists():raise ValueError('Preserve prior experiment')
    policy=json.loads((args.policy_root/'policy.json').read_text());path=args.policy_root/'hey_chat_temporal.onnx'
    if sha(path)!=policy['model_sha256']:raise ValueError('Model changed')
    opts=ort.SessionOptions();opts.intra_op_num_threads=2;opts.inter_op_num_threads=1
    head=ort.InferenceSession(str(path),sess_options=opts,providers=['CPUExecutionProvider'])
    manifest=json.loads((args.base/'streams.json').read_text());dev=[]
    # Original complete development streams use existing frozen feature caches.
    for row in manifest['clips']:
        if row['split']!='dev':continue
        digest=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()[:20]
        with np.load(args.base/'stream-cache'/(digest+'.npz')) as saved:vectors=saved['vectors'];times=saved['times']
        scores=np.asarray([float(head.run(None,{'input':v[None].astype(np.float32)})[0][0,0]) for v in vectors])
        events=[];last=-100.
        for t,s in zip(times,scores):
            if s>=policy['threshold'] and t-last>=3:events.append(float(t));last=float(t)
        dev.append({'source_group':row['source_group'],'wake_expected':row['wake_expected'],'kind':row.get('kind','matched-synthetic'),
            'prefix':row.get('prefix'),'wake_end':row['wake_end'],'duration':row['duration'],'events':events})
    latencies=[]
    for row in dev:
        if row['wake_expected']:
            valid=[t-row['wake_end'] for t in row['events'] if row['wake_end']-.08<=t<=row['wake_end']+1.2]
            if valid:latencies.append(valid[0])
    features=AudioFeatures(melspec_model_path=str(args.base/'backbone/melspectrogram.onnx'),
        embedding_model_path=str(args.base/'backbone/embedding_model.onnx'),inference_framework='onnx',ncpu=1)
    natural=[]
    for row in manifest['clips']:
        if row['split']=='natural-test':
            p=Path(row['path']);natural.append(wav_read(p if p.is_absolute() else args.base/p).astype(np.int16))
    pcm=np.concatenate(natural);reset_features(features);events=[];last=-100.;timings=[]
    for offset in range(0,len(pcm),1280):
        block=pcm[offset:offset+1280]
        if len(block)<1280:block=np.pad(block,(0,1280-len(block)))
        stamp=time.perf_counter();features(block);score=float(head.run(None,{'input':features.get_features(16)})[0][0,0]);timings.append((time.perf_counter()-stamp)*1000)
        end=(offset+1280)/RATE
        if offset//1280>=26 and score>=policy['threshold'] and end-last>=3:events.append(end);last=end
    report={'policy':policy,'development':dev,'decision_latency_seconds':{'count':len(latencies),
        'median':float(np.median(latencies)) if latencies else None,'p95':float(np.percentile(latencies,95)) if latencies else None},
        'natural_test_continuous':{'seconds':len(pcm)/RATE,'reset_count':1,'false_events':events,
            'false_events_per_hour':len(events)*3600/(len(pcm)/RATE)},
        'frontend_and_head_cpu_ms':{'median':float(np.median(timings)),'p95':float(np.percentile(timings,95)),'hop_ms':80},
        'diagnostic_only':True,'acceptance_passed':False,'limitations':['Inspected regression; no new human field acceptance',
            'Natural read speech, not a street microphone','Host CPU timing, not handset timing']}
    (root/'evaluation.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='development'}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--policy-root',type=Path,required=True)
    p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    main(p.parse_args())
