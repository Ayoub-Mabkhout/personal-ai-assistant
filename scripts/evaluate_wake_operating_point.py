"""One declared development-recall policy, then read-only saved-head regression.

Selects the highest threshold achieving the requested complete-wake recall on
development utterances. Personal recordings never participate in selection.
It records the near-confusable tradeoff instead of calling that policy accepted.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import onnxruntime as ort
from train_personal_wake import wav_read,sha,RATE
from train_wake_cnn import frontend,raw_windows


def main(args):
    baseline=json.loads((args.model_root/'evaluation.json').read_text())
    model=args.model_root/'hey_chat_logmel_cnn.onnx'
    if sha(model)!=baseline['model_sha256']:raise ValueError('Selected model hash changed')
    development=baseline['development'];wanted=np.sort([r['desired_max'] for r in development if r['wake_expected'] and r['desired_max'] is not None])
    needed=math.ceil(len(wanted)*args.dev_recall);threshold=float(wanted[-needed])
    policy={'requested_complete_wake_recall':args.dev_recall,'threshold':threshold,'positive_count':len(wanted),
        'positive_detected':int(np.count_nonzero(wanted>=threshold)),
        'selection':'Highest threshold achieving ceil(recall * dev positive utterances); saved development scores only',
        'model_sha256':sha(model),'personal_test_used_for_selection':False}
    # Write the committed policy before any personal audio is read or scored.
    args.output.mkdir(parents=True,exist_ok=True)
    if (args.output/'policy.json').exists():raise ValueError('Policy output exists; preserve the prior evaluation')
    (args.output/'policy.json').write_text(json.dumps(policy,indent=2))
    print(json.dumps({'stage':'development-policy-fixed',**policy}),flush=True)
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    head=ort.InferenceSession(str(model),sess_options=options,providers=['CPUExecutionProvider'])
    mel=frontend(args.stream_root/'backbone/melspectrogram.onnx')
    results=[];cold_results=[]
    for item in json.loads((args.corpus/'manifest.json').read_text())['clips']:
        pcm=np.concatenate([wav_read(args.corpus/item['path']).astype(np.int16),np.zeros(RATE,np.int16)])
        for cold,target in [(False,results),(True,cold_results)]:
            windows=raw_windows(pcm,mel,cold=cold)
            scores=np.asarray([float(head.run(None,{'input':w[None,None]})[0][0,0]) for w in windows])
            if cold:scores[:26]=0
            indices=np.flatnonzero(scores>=threshold)
            target.append(dict(item,max_score=float(scores.max()),detected=bool(len(indices)),
                first_activation_seconds=float((indices[0]+1)*.08) if len(indices) else None))
    def stats(rows):
        return {'positives':sum(r['wake_expected'] for r in rows),'missed':sum(r['wake_expected'] and not r['detected'] for r in rows),
            'negatives':sum(not r['wake_expected'] for r in rows),'false':sum(not r['wake_expected'] and r['detected'] for r in rows)}
    summaries={}
    for split in ['template','held-out-real','synthetic-evaluation']:
        for kind in ['original','synthetic','augmented']:
            rows=[r for r in results if r['split']==split and r['kind']==kind]
            if kind=='original':rows=list({r['source_group']:r for r in rows}.values())
            if rows:summaries[f'{split}:{kind}']=stats(rows)
    natural=[r for r in development if r['kind']=='natural']
    confusable=[r for r in development if r['kind']!='natural' and not r['wake_expected']]
    originals={r['source_group']:r for r in results if r['split']=='held-out-real' and r['kind']=='original'}
    controls=[r for r in results if not r['wake_expected'] and r['source_group'].startswith('original-')]
    gate=all(r['detected'] for r in originals.values() if r['wake_expected']) and not any(r['detected'] for r in controls)
    report={'policy':policy,'diagnostic_only':True,'automated_regression_passed':gate,'acceptance_passed':False,
        'development_natural':{'utterances':len(natural),'seconds':sum(r['duration'] for r in natural),'false_utterances':sum(r['max_score']>=threshold for r in natural)},
        'development_confusable':{'utterances':len(confusable),'false_utterances':sum(r['max_score']>=threshold for r in confusable)},
        'summaries':summaries,'samples':results,'cold_samples':cold_results,
        'limitations':['Threshold frozen before personal inference; no subsequent adjustment',
            'Confusable utterance counts do not define real-world false activations per hour',
            'No blind new field recording or handset/battery acceptance','Original regression corpus previously inspected across experiments']}
    (args.output/'evaluation.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ['samples','cold_samples']},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model-root',type=Path,required=True)
    p.add_argument('--stream-root',type=Path,required=True);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--dev-recall',type=float,default=.9)
    args=p.parse_args()
    if not 0<args.dev_recall<=1:p.error('Development recall must be >0 and <=1')
    main(args)
