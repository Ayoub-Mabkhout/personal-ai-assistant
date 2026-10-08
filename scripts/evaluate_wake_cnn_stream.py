"""Replay an untouched, continuous negative stream without feature resets.

This is a read-only wake-model evaluation. It never dispatches assistant intents.
Natural source boundaries are concatenated, not represented as live field audio.
The chosen classifier and development threshold are immutable inputs.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
import onnxruntime as ort
from train_personal_wake import wav_read,sha,RATE
from train_wake_cnn import frontend


def stream_scores(pcm,mel,head):
    history=np.ones((196,32),np.float32);tail=np.empty(0,np.int16)
    scores=[];timings=[]
    for offset in range(0,len(pcm),1280):
        block=pcm[offset:offset+1280]
        if len(block)<1280:block=np.pad(block,(0,1280-len(block)))
        stamp=time.perf_counter();raw=np.concatenate([tail,block]);spec=mel(raw);tail=raw[-480:]
        history=np.concatenate([history,spec])[-196:]
        probability=float(head.run(None,{'input':history[None,None]})[0][0,0])
        timings.append((time.perf_counter()-stamp)*1000)
        scores.append(0. if offset//1280<26 else probability)
    return np.asarray(scores),np.asarray(timings)


def activations(scores,threshold):
    result=[];last=-100.
    for index,score in enumerate(scores):
        end=(index+1)*.08
        if score>=threshold and end-last>=3.:result.append(end);last=end
    return result


def main(args):
    evaluation=json.loads((args.model_root/'evaluation.json').read_text())
    threshold=evaluation['threshold'];head_path=args.model_root/'hey_chat_logmel_cnn.onnx'
    if sha(head_path)!=evaluation['model_sha256']:raise ValueError('Changed classifier after development selection')
    manifest=json.loads((args.stream_root/'streams.json').read_text())
    rows=[r for r in manifest['clips'] if r['split']=='natural-test']
    clips=[];sources=[];cursor=0
    for row in rows:
        path=Path(row['path']);path=path if path.is_absolute() else args.stream_root/path
        pcm=wav_read(path).astype(np.int16);clips.append(pcm)
        sources.append({'source_group':row['source_group'],'sha256':sha(path),
            'start_seconds':cursor/RATE,'end_seconds':(cursor+len(pcm))/RATE})
        cursor+=len(pcm)
    pcm=np.concatenate(clips)
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    head=ort.InferenceSession(str(head_path),sess_options=options,providers=['CPUExecutionProvider'])
    mel=frontend(args.stream_root/'backbone/melspectrogram.onnx')
    scores,timings=stream_scores(pcm,mel,head);events=activations(scores,threshold)
    report={'feature_type':'logmel-cnn','classifier_sha256':sha(head_path),'threshold':threshold,
        'split':'natural-test','duration_seconds':len(pcm)/RATE,'source_count':len(rows),
        'reset_count':1,'cold_start_suppressed_blocks':26,'first_scored_block_index':26,
        'false_activations':events,'false_activations_per_hour':len(events)*3600/(len(pcm)/RATE),
        'max_probability':float(scores.max()),'sources':sources,
        'frontend_and_head_cpu_latency':{'median_ms':float(np.median(timings)),
            'p95_ms':float(np.percentile(timings,95)),'max_ms':float(timings.max()),
            'hop_ms':80,'handset_measured':False},
        'limitations':['Concatenated read speech, not a street microphone recording',
            'No threshold adjustment from this test','One cold reset; continuous state retained at source boundaries',
            'Short test cannot certify an hours-long false-wake rate']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ['duration_seconds','false_activations_per_hour','max_probability','frontend_and_head_cpu_latency']}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model-root',type=Path,required=True)
    p.add_argument('--stream-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    main(p.parse_args())
