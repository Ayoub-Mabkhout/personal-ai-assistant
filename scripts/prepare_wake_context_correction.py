"""Add keyword-only and variable-gap controls without using regression recordings.

Reuses disjoint train/development Piper sources and the three explicit training
wake templates. Existing streams/caches stay immutable. No synthesis API is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from train_personal_wake import RATE,wav_read,wav_write,sha
from wake_training_data import PREFIXES,TAILS,variant,validate_streams


def main(args):
    source=args.source;output=args.output;output.mkdir(parents=True,exist_ok=True)
    if (output/'streams.json').exists():raise ValueError('Corrected manifest already exists; reuse rather than overwrite')
    base=json.loads((source/'streams.json').read_text());rng=np.random.default_rng(args.seed)
    sources={sha(p):p for p in (source/'sources').glob('*.wav')}
    rows=[];added=[]
    for row in base['clips']:
        copied=dict(row)
        if not Path(copied['path']).is_absolute():copied['path']=str((source/copied['path']).resolve())
        digest=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()[:20]
        cached=args.baseline/'mel-cache'/(digest+'.npz')
        if cached.exists():
            copied['precomputed_mel_cache']=str(cached.resolve())
            copied['precomputed_mel_cache_sha256']=sha(cached)
        rows.append(copied)
    voices={}
    for row in base['clips']:
        if row.get('speaker') in base['speaker_ids']:
            key=row['speaker'];v=voices.setdefault(key,{'split':row['split'],'prefixes':{},'tails':{}})
            if row.get('prefix_source_sha256'):v['prefixes'][row['prefix']]=sources[row['prefix_source_sha256']]
            v['tails'][row['tail']]=sources[row['tail_source_sha256']]
    natural={split:[r['path'] for r in base['clips'] if r.get('kind')=='natural' and r['split']==split] for split in ['train','dev']}
    def write_case(group,prefix,positive,tail,split,speaker,prefix_sha,tail_sha,gap,index,kind):
        lead=int(rng.integers(2400,9600));body=np.concatenate([prefix,np.zeros(round(gap*RATE),np.float32),tail])
        values=np.concatenate([np.zeros(lead,np.float32),body,np.zeros(RATE,np.float32)])
        noise=natural[split][int(rng.integers(len(natural[split])))] if natural[split] else None
        rel=f'streams/{group}-{index}.wav';wav_write(output/rel,variant(values,rng,index,noise))
        added.append({'path':rel,'split':split,'source_group':group,'speaker':speaker,
            'wake_expected':positive,'wake_start':lead/RATE if positive else None,
            'wake_end':(lead+len(prefix))/RATE if positive else None,'duration':len(values)/RATE,
            'prefix_source_sha256':prefix_sha,'tail_source_sha256':tail_sha,'gap_seconds':gap,
            'variant':index,'noise_source':noise,'kind':kind,'wav_sha256':sha(output/rel)})
    for speaker,voice in voices.items():
        for prefix_index,text in enumerate(PREFIXES):
            path=voice['prefixes'].get(text);prefix=wav_read(path) if path else np.zeros(len(wav_read(voice['prefixes']['Hey Chat'])))
            for index in range(3):
                write_case(f'isolated-{speaker}-prefix{prefix_index}',prefix,text=='Hey Chat',np.empty(0),voice['split'],speaker,
                    sha(path) if path else None,None,0,index,'isolated-keyword-control')
            for tail_index,tail_text in enumerate(TAILS):
                tail_path=voice['tails'][tail_text];tail=wav_read(tail_path)
                for index,gap in enumerate([.2,.7]):
                    write_case(f'gapped-{speaker}-tail{tail_index}-prefix{prefix_index}',prefix,text=='Hey Chat',tail,voice['split'],speaker,
                        sha(path) if path else None,sha(tail_path),gap,index,'gapped-matched-control')
    for path in sorted((args.corpus/'wake-model/templates').glob('*.wav')):
        values=wav_read(path)
        pieces=[('full',values,True),('first',values[:int(len(values)*.35)],False),
            ('last',values[int(len(values)*.65):],False),('reordered',np.concatenate([values[len(values)//2:],values[:len(values)//2]]),False)]
        for text,prefix,positive in pieces:
            for index in range(12):
                write_case(f'isolated-personal-{path.stem}-{text}',prefix,positive,np.empty(0),'train','personal-training',
                    sha(path),None,0,index,'isolated-personal-training')
    rows.extend(added);validate_streams(rows)
    (output/'backbone').mkdir(exist_ok=True)
    shutil.copy2(source/'backbone/melspectrogram.onnx',output/'backbone/melspectrogram.onnx')
    report={k:v for k,v in base.items() if k!='clips'}
    report.update({'clips':rows,'correction':'Isolated keyword/confusable and variable-tail-gap sources; no regression audio',
        'seed':args.seed,'baseline_manifest_sha256':sha(source/'streams.json'),'added_streams':len(added)})
    (output/'streams.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'streams':len(rows),'added':len(added),'split':{s:sum(r['split']==s for r in added) for s in ['train','dev']}}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--seed',type=int,default=6017)
    main(p.parse_args())
