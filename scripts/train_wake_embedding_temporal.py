"""One bounded regularized temporal head over frozen speech embeddings.

Uses cached streaming features, shared time weights, dropout and development-only
operating policy. Does not train the backbone or use personal command regressions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import onnxruntime as ort
import torch
from torch import nn
from openwakeword.utils import AudioFeatures
from train_personal_wake import reset_features,wav_read,sha,RATE
from wake_training_data import cache_stream_features,validate_streams


class Head(nn.Module):
    def __init__(self,mean,scale):
        super().__init__();self.register_buffer('mean',torch.tensor(mean).reshape(1,1,96));self.register_buffer('scale',torch.tensor(scale).reshape(1,1,96))
        self.layers=nn.Sequential(nn.Conv1d(96,32,3,padding=1),nn.ReLU(),nn.Dropout(.35),
            nn.Conv1d(32,32,3,padding=2,dilation=2),nn.ReLU(),nn.Dropout(.35),
            nn.Conv1d(32,32,3,padding=4,dilation=4),nn.ReLU())
        self.final=nn.Linear(32,1)
    def forward(self,values):
        values=((values-self.mean)/self.scale).transpose(1,2)
        return self.final(self.layers(values).amax(dim=2)).reshape(-1)


def infer(model,x,device):
    model.eval();parts=[]
    with torch.no_grad():
        for start in range(0,len(x),512):parts.append(model(torch.from_numpy(x[start:start+512]).to(device)).cpu().numpy())
    return np.concatenate(parts)


def main(args):
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    if (root/'plan.json').exists():raise ValueError('Experiment already committed')
    torch.set_num_threads(3);torch.manual_seed(7281);rng=np.random.default_rng(7281)
    torch.backends.cudnn.allow_tf32=False;torch.backends.cuda.matmul.allow_tf32=False
    device='cuda' if torch.cuda.is_available() else 'cpu'
    plan={'feature_type':'openwakeword-embedding-temporal','seed':7281,'device':device,'epochs':args.epochs,
        'training_deadline_seconds':args.seconds,'dropout':.35,'weight_decay':.02,'target_dev_recall':.9,
        'selection':'At90%complete-wake dev recall, minimize natural/ordinary-negative errors then confusable errors; no regression used',
        'baseline_manifest_sha256':sha(args.base/'streams.json'),'correction_manifest_sha256':sha(args.context/'streams.json')}
    (root/'plan.json').write_text(json.dumps(plan,indent=2))
    baseline=json.loads((args.base/'streams.json').read_text());corrected=json.loads((args.context/'streams.json').read_text())
    validate_streams(corrected['clips']);base_rows=[r for r in baseline['clips'] if r['split'] in ['train','dev']]
    records=[]
    for row in base_rows:
        digest=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()[:20]
        records.append(dict(row,cache_file=str(args.base/'stream-cache'/(digest+'.npz'))))
    features=AudioFeatures(melspec_model_path=str(args.base/'backbone/melspectrogram.onnx'),
        embedding_model_path=str(args.base/'backbone/embedding_model.onnx'),inference_framework='onnx',ncpu=1)
    # Isolated controls address observed context dependence; gapped tails already
    # have counterparts in the baseline and need not duplicate feature work.
    extra=[r for r in corrected['clips'] if r.get('kind') in ['isolated-keyword-control','isolated-personal-training']]
    _,_,_,_,additional=cache_stream_features(extra,features,args.context,root/'feature-cache',4);records.extend(additional)
    xs=[];ys=[];dev_vectors=[];bounds=[];cursor=0
    for row in records:
        with np.load(row['cache_file']) as cached:vectors=cached['vectors'];labels=cached['labels']
        if row['split']=='train':
            index=np.arange(len(labels));selected=(labels>=0)&((labels==1)|(index%4==0))
            xs.append(vectors[selected]);ys.append(labels[selected])
        else:
            dev_vectors.append(vectors);bounds.append(dict(row,begin=cursor,end=cursor+len(vectors),labels=labels));cursor+=len(vectors)
    x=np.concatenate(xs).astype(np.float32);y=np.concatenate(ys);dev=np.concatenate(dev_vectors).astype(np.float32)
    sample=x[rng.choice(len(x),min(3000,len(x)),replace=False)];mean=sample.mean(axis=(0,1));scale=np.maximum(sample.std(axis=(0,1)),.1)
    model=Head(mean,scale).to(device);optimizer=torch.optim.AdamW(model.parameters(),lr=.0005,weight_decay=.02)
    positive=np.flatnonzero(y==1);negative=np.flatnonzero(y==0);deadline=time.monotonic()+args.seconds
    history=[];best=(-1e9,);selected=None
    print(json.dumps({'stage':'temporal-embedding-training','train_windows':len(x),'dev_windows':len(dev),'parameters':sum(p.numel() for p in model.parameters())}),flush=True)
    for epoch in range(args.epochs):
        if time.monotonic()>deadline:break
        model.train();losses=[]
        for p in np.array_split(rng.permutation(positive),max(1,len(positive)//64)):
            n=rng.choice(negative,len(p)*3);indices=rng.permutation(np.concatenate([p,n]))
            values=torch.from_numpy(x[indices]).to(device);truth=torch.tensor(y[indices],dtype=torch.float32,device=device)
            # Small perturbation in frozen embedding space complements dropout.
            values=values+torch.randn_like(values)*model.scale*.025
            optimizer.zero_grad(set_to_none=True);logits=model(values)
            loss=nn.functional.binary_cross_entropy_with_logits(logits,truth)
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),3);optimizer.step();losses.append(float(loss.detach()))
            if time.monotonic()>deadline:break
        if epoch%2:continue
        logits=infer(model,dev,device);desired=[];natural=[];confusable=[]
        for row in bounds:
            values=logits[row['begin']:row['end']];labels=row['labels']
            if row['wake_expected']:desired.append(float(values[labels==1].max()))
            else:(natural if row.get('kind')=='natural' or row.get('prefix')=='' else confusable).append(float(values.max()))
        desired=np.sort(desired);threshold=float(desired[-int(np.ceil(len(desired)*.9))])
        ordinary_errors=sum(v>=threshold for v in natural);confusable_errors=sum(v>=threshold for v in confusable)
        valid=np.concatenate([b['labels'] for b in bounds])>=0;truth=np.concatenate([b['labels'] for b in bounds])[valid]
        bce=float(np.mean(np.logaddexp(0,logits[valid])-truth*logits[valid]));rank=(-ordinary_errors,-confusable_errors,-bce)
        event={'epoch':epoch+1,'threshold_logit':threshold,'ordinary_errors':ordinary_errors,'confusable_errors':confusable_errors,
            'dev_complete_recall':float(np.mean(desired>=threshold)),'dev_bce':bce,'training_loss':float(np.mean(losses))}
        history.append(event);print(json.dumps(event),flush=True)
        if rank>best:
            best=rank;selected=event;torch.save(model.state_dict(),root/'checkpoint.pt')
        (root/'history.json').write_text(json.dumps(history,indent=2))
    model.load_state_dict(torch.load(root/'checkpoint.pt',map_location=device,weights_only=True));model.eval()
    logits=infer(model,dev,device);temperature=max(1.,float(np.percentile(np.abs(logits),99))/6)
    threshold=float(1/(1+np.exp(-selected['threshold_logit']/temperature)))
    class Export(nn.Module):
        def __init__(self):super().__init__();self.base=model.cpu()
        def forward(self,value):return torch.sigmoid(self.base(value)/temperature).reshape(-1,1)
    wrapper=Export().eval();torch.onnx.export(wrapper,torch.zeros(1,16,96),str(root/'hey_chat_temporal.onnx'),
        input_names=['input'],output_names=['wake_probability'],opset_version=13,dynamo=False)
    head=ort.InferenceSession(str(root/'hey_chat_temporal.onnx'),providers=['CPUExecutionProvider'])
    for value in dev[:8]:
        expected=float(wrapper(torch.from_numpy(value[None])).detach().numpy()[0,0]);actual=float(head.run(None,{'input':value[None]})[0][0,0])
        if abs(expected-actual)>1e-5:raise AssertionError('Temporal head Torch/ONNX parity failed')
    # Freeze policy before reading the personal command corpus.
    policy={'threshold':threshold,'temperature':temperature,'selection':selected,'model_sha256':sha(root/'hey_chat_temporal.onnx')}
    (root/'policy.json').write_text(json.dumps(policy,indent=2));rows=[]
    for item in json.loads((args.corpus/'manifest.json').read_text())['clips']:
        reset_features(features)
        for _ in range(38):features(np.zeros(1280,np.int16))
        pcm=np.concatenate([wav_read(args.corpus/item['path']).astype(np.int16),np.zeros(RATE,np.int16)])
        scores=[]
        for offset in range(0,len(pcm),1280):
            block=pcm[offset:offset+1280]
            if len(block)<1280:block=np.pad(block,(0,1280-len(block)))
            features(block);scores.append(float(head.run(None,{'input':features.get_features(16)})[0][0,0]))
        indices=np.flatnonzero(np.asarray(scores)>=threshold)
        rows.append(dict(item,max_score=float(max(scores)),detected=bool(len(indices)),
            first_activation_seconds=float((indices[0]+1)*.08) if len(indices) else None))
    report={'policy':policy,'samples':rows,'history':history,'diagnostic_only':True,'acceptance_passed':False,
        'feature_type':'openwakeword-embedding-temporal','limitations':['Inspected personal corpus is regression, not blind acceptance',
            'Dropout/shared time weights do not establish field reliability','No handset/battery acceptance']}
    (root/'evaluation.json').write_text(json.dumps(report,indent=2));print(json.dumps({'stage':'complete','policy':policy}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True)
    p.add_argument('--context',type=Path,required=True);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--epochs',type=int,default=40);p.add_argument('--seconds',type=int,default=600)
    main(p.parse_args())
