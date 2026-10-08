"""Train a local GPU temporal wake CNN on annotated raw streaming log-mel.

Reuses the matched streams/speaker partitions from train_personal_wake --streaming.
All checkpoint and threshold decisions use development streams, never personal
regression/test recordings. Outputs remain experimental until handset validation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import zipfile

os.environ.setdefault('OMP_NUM_THREADS','4')
import numpy as np
import onnxruntime as ort
from wake_training_data import window_label,validate_streams
from train_personal_wake import wav_read,sha,RATE

MEL_FRAMES=196


def frontend(path):
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
    def mel(values):
        return np.squeeze(session.run(None,{'input':values.astype(np.float32)[None]})[0]).astype(np.float32)/10+2
    return mel


def raw_windows(pcm,mel,cold=False):
    """Exactly reproduce production overlap; model sees only preceding audio."""
    history=np.ones((MEL_FRAMES,32),np.float32) if cold else np.tile(mel(np.zeros(1760,np.int16)),(25,1))[-MEL_FRAMES:]
    tail=np.empty(0,np.int16) if cold else np.zeros(480,np.int16)
    windows=[]
    for offset in range(0,len(pcm),1280):
        block=pcm[offset:offset+1280]
        if len(block)<1280:block=np.pad(block,(0,1280-len(block)))
        values=np.concatenate([tail,block]);spec=mel(values);tail=values[-480:]
        history=np.concatenate([history,spec])[-MEL_FRAMES:]
        windows.append(history.copy())
    return np.asarray(windows,np.float32)


def cache_mels(rows,root,cache,mel):
    cache.mkdir(parents=True,exist_ok=True);records=[]
    for index,row in enumerate(rows):
        digest=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()[:20];path=cache/(digest+'.npz')
        # A corrected manifest can retain an immutable cache from its baseline.
        # Hash/path provenance is preserved in the new stream manifest.
        if row.get('precomputed_mel_cache'):
            path=Path(row['precomputed_mel_cache'])
            if not path.is_file():raise ValueError('Baseline cache unavailable')
            if row.get('precomputed_mel_cache_sha256') and sha(path)!=row['precomputed_mel_cache_sha256']:
                raise ValueError('Baseline cache hash changed')
        if path.exists():
            try:
                with np.load(path) as existing:existing['labels']
            except (ValueError,EOFError,zipfile.BadZipFile):
                if row.get('precomputed_mel_cache'):raise ValueError('Immutable baseline cache is corrupt')
                path.unlink()
        if not path.exists():
            source=Path(row['path']) if Path(row['path']).is_absolute() else root/row['path']
            pcm=np.concatenate([wav_read(source).astype(np.int16),np.zeros(RATE,np.int16)])
            values=raw_windows(pcm,mel);times=np.arange(1,len(values)+1,dtype=np.float32)*.08
            labels=np.asarray([window_label(float(t),row['wake_start'],row['wake_end']) for t in times],np.int8)
            temporary=path.with_suffix('.part')
            with temporary.open('wb') as target:np.savez_compressed(target,mel=values,times=times,labels=labels)
            temporary.replace(path)
        records.append(dict(row,mel_cache=str(path.resolve())))
        if index%100==0:print(json.dumps({'stage':'raw-mel-cache','utterances':index+1}),flush=True)
    return records


def matrix(records,root):
    """Disk-backed matrices retain full dev streams and bound training negatives."""
    index=[];bounds=[]
    for row in records:
        if row['split'] not in ['train','dev']:continue
        data=np.load(row['mel_cache']);labels=data['labels'];selected=[]
        for frame,label in enumerate(labels):
            if row['split']=='train' and (label<0 or (label==0 and frame%4)):continue
            selected.append(frame)
        begin=len(index);index.extend((row,frame,int(labels[frame])) for frame in selected)
        bounds.append({'begin':begin,'end':len(index),'labels':labels[selected],
                      'wake_expected':row['wake_expected'],'split':row['split'],'source_group':row['source_group'],
                      'kind':row.get('kind','matched-synthetic'),'duration':row['duration']})
    x=np.lib.format.open_memmap(root/'mel-matrix.npy',mode='w+',dtype=np.float32,shape=(len(index),1,MEL_FRAMES,32))
    y=np.empty(len(index),np.int8);splits=np.empty(len(index),dtype='U16');cursor=0
    for row in records:
        if row['split'] not in ['train','dev']:continue
        data=np.load(row['mel_cache']);labels=data['labels'];frames=np.arange(len(labels))
        selected=(labels>=0)&((labels==1)|(frames%4==0)) if row['split']=='train' else np.ones(len(labels),bool)
        values=data['mel'][selected];n=len(values);x[cursor:cursor+n,0]=values;y[cursor:cursor+n]=labels[selected];splits[cursor:cursor+n]=row['split'];cursor+=n
    x.flush();np.savez(root/'mel-labels.npz',y=y,split=splits)
    return x,y,splits,bounds


def calibrate(logits,bounds):
    wanted=[];unwanted=[];details=[]
    for row in bounds:
        values=logits[row['begin']:row['end']];labels=row['labels']
        a=float(values[labels==1].max()) if np.any(labels==1) else None
        b=float(values[labels==0].max()) if np.any(labels==0) else None
        if row['wake_expected']:wanted.append(a if a is not None else -100.)
        if b is not None:unwanted.append(b)
        details.append({key:row[key] for key in ['source_group','wake_expected','kind','duration']} | {'desired_logit':a,'unwanted_logit':b})
    threshold=max(unwanted)+.05
    return threshold,float(np.mean(np.asarray(wanted)>=threshold)),details


def create_model(torch,mean,scale,dilations=(2,4,8)):
    nn=torch.nn
    class TemporalCNN(nn.Module):
        def __init__(self):
            super().__init__();self.register_buffer('mean',torch.tensor(mean).reshape(1,1,1,32));self.register_buffer('scale',torch.tensor(scale).reshape(1,1,1,32))
            self.spectral=nn.Sequential(
                nn.Conv2d(1,16,(3,3),padding=(1,1),stride=(1,2)),nn.BatchNorm2d(16),nn.ReLU(),
                nn.Conv2d(16,32,(5,3),padding=(2,1),stride=(2,2)),nn.BatchNorm2d(32),nn.ReLU(),
                nn.Conv2d(32,48,(5,3),padding=(2,1),stride=(2,2)),nn.BatchNorm2d(48),nn.ReLU())
            self.temporal=nn.Sequential(
                nn.Conv1d(192,64,5,padding=2*dilations[0],dilation=dilations[0]),nn.BatchNorm1d(64),nn.ReLU(),
                nn.Conv1d(64,64,5,padding=2*dilations[1],dilation=dilations[1]),nn.BatchNorm1d(64),nn.ReLU(),
                nn.Conv1d(64,64,5,padding=2*dilations[2],dilation=dilations[2]),nn.BatchNorm1d(64),nn.ReLU(),nn.Dropout(.15))
            self.classifier=nn.Linear(64,1)
        def forward(self,value):
            value=(value-self.mean)/self.scale;value=self.spectral(value)
            value=value.permute(0,1,3,2).reshape(value.shape[0],192,value.shape[2])
            value=self.temporal(value).amax(dim=2);return self.classifier(value).reshape(-1)
    return TemporalCNN()


def infer(torch,model,x,indices,device,batch=256):
    model.eval();result=np.empty(len(indices),np.float32)
    with torch.no_grad():
        for start in range(0,len(indices),batch):
            selected=indices[start:start+batch];values=torch.from_numpy(np.asarray(x[selected])).to(device)
            result[start:start+len(selected)]=model(values).float().cpu().numpy()
    return result


def fit(args,x,y,splits,bounds,root):
    import torch
    torch.set_num_threads(4);torch.manual_seed(args.seed);np_rng=np.random.default_rng(args.seed)
    # Match ONNX float32 convolution; TF32's reduced mantissa can alter near-
    # threshold probabilities even though the classifier weights are identical.
    torch.backends.cudnn.allow_tf32=False;torch.backends.cuda.matmul.allow_tf32=False
    device='cuda' if torch.cuda.is_available() else 'cpu'
    if args.require_cuda and device!='cuda':raise RuntimeError('CUDA unavailable; no unbounded CPU fallback')
    train=np.flatnonzero(splits=='train');dev=np.flatnonzero(splits=='dev');positive=train[y[train]==1];negative=train[y[train]==0]
    # Statistics come only from training data. Random sample bounds working RAM.
    sample=np.asarray(x[np_rng.choice(train,size=min(2000,len(train)),replace=False)])
    mean=sample.mean(axis=(0,1,2));scale=np.maximum(sample.std(axis=(0,1,2)),.1)
    model=create_model(torch,mean,scale,args.temporal_dilations).to(device);optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.003)
    scaler=torch.amp.GradScaler('cuda',enabled=device=='cuda');deadline=time.monotonic()+args.max_train_seconds
    dev_bounds=[];cursor=0
    for row in bounds:
        if row['split']=='dev':dev_bounds.append(dict(row,begin=cursor,end=cursor+row['end']-row['begin']));cursor=dev_bounds[-1]['end']
    history=[];best_score=(-1.,-1.);hard=negative;best_path=root/'checkpoint.pt'
    print(json.dumps({'stage':'cnn-training','device':device,'positive_windows':len(positive),'negative_windows':len(negative),'dev_windows':len(dev)}),flush=True)
    for epoch in range(0 if args.evaluate_only else args.epochs):
        if time.monotonic()>deadline:break
        if epoch%5==0 and epoch:
            scores=infer(torch,model,x,negative,device);hard=negative[np.argsort(scores)[-max(1,len(negative)//10):]]
        model.train();total_loss=0.;steps=0
        for p in np.array_split(np_rng.permutation(positive),max(1,len(positive)//32)):
            n=np.concatenate([np_rng.choice(hard,size=len(p)),np_rng.choice(negative,size=2*len(p))]);selected=np_rng.permutation(np.concatenate([p,n]))
            values=torch.from_numpy(np.asarray(x[selected])).to(device);targets=torch.tensor(y[selected],device=device,dtype=torch.float32)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device,dtype=torch.float16,enabled=device=='cuda'):
                logits=model(values);loss=torch.nn.functional.binary_cross_entropy_with_logits(logits.float(),targets,
                    weight=torch.where(targets>.5,1.,2.))
            scaler.scale(loss).backward();scaler.unscale_(optimizer);torch.nn.utils.clip_grad_norm_(model.parameters(),5.)
            scaler.step(optimizer);scaler.update();total_loss+=float(loss);steps+=1
            if time.monotonic()>deadline:break
        if epoch%2==0 or epoch+1==args.epochs:
            logits=infer(torch,model,x,dev,device);threshold,recall,details=calibrate(logits,dev_bounds)
            valid=y[dev]>=0;truth=y[dev][valid];loss=float(np.mean(np.logaddexp(0,logits[valid])-truth*logits[valid]))
            event={'epoch':epoch+1,'dev_recall':recall,'logit_threshold':threshold,'dev_loss':loss,'training_loss':total_loss/max(steps,1)};history.append(event);print(json.dumps(event),flush=True)
            if (recall,-loss)>best_score:
                best_score=(recall,-loss);torch.save(model.state_dict(),best_path)
                (root/'dev-calibration.json').write_text(json.dumps({'threshold_logit':threshold,'recall':recall,'samples':details},indent=2))
    if history:(root/'training-history.json').write_text(json.dumps(history,indent=2))
    elif (root/'training-history.json').exists():history=json.loads((root/'training-history.json').read_text())
    model.load_state_dict(torch.load(best_path,map_location=device,weights_only=True));model.eval()
    logits=infer(torch,model,x,dev,device);threshold,recall,details=calibrate(logits,dev_bounds)
    # Temperature is selected only to keep output probabilities numerically
    # resolvable. It does not change ranking or hide overlap between classes.
    temperature=max(1.,float(np.percentile(np.abs(logits),99))/8.)
    probability_threshold=float(1/(1+np.exp(-threshold/temperature)))
    nn=torch.nn
    class Export(nn.Module):
        def __init__(self,base):super().__init__();self.base=base
        def forward(self,value):return torch.sigmoid(self.base(value)/temperature).reshape(-1,1)
    wrapper=Export(model).to('cpu').eval();example=torch.zeros(1,1,MEL_FRAMES,32)
    torch.onnx.export(wrapper,example,str(root/'hey_chat_logmel_cnn.onnx'),input_names=['input'],output_names=['wake_probability'],opset_version=13,dynamo=False)
    session=ort.InferenceSession(str(root/'hey_chat_logmel_cnn.onnx'),providers=['CPUExecutionProvider'])
    for index in dev[:8]:
        value=np.asarray(x[index:index+1]);expected=float(wrapper(torch.from_numpy(value)).detach().numpy()[0,0]);actual=float(session.run(None,{'input':value})[0][0,0])
        if abs(actual-expected)>1e-4:raise AssertionError('CNN Torch/ONNX export mismatch')
    return session,probability_threshold,temperature,history,details,wrapper.to(device).eval(),device


def probabilities(session,windows,gpu_model=None,device=None):
    if gpu_model is None:return np.asarray([float(session.run(None,{'input':v[None,None]})[0][0,0]) for v in windows])
    import torch
    scores=[]
    with torch.no_grad():
        for offset in range(0,len(windows),128):
            values=torch.from_numpy(windows[offset:offset+128,None]).to(device)
            scores.extend(gpu_model(values).float().cpu().numpy().reshape(-1).tolist())
    result=np.asarray(scores)
    # Check the actual exported CPU graph at the strongest predicted window.
    index=int(result.argmax());actual=float(session.run(None,{'input':windows[index:index+1,None]})[0][0,0])
    if abs(actual-result[index])>1e-4:raise AssertionError(f'GPU/CPU ONNX probability mismatch: CPU={actual}, GPU={result[index]}')
    return result


def evaluate_rows(session,records,threshold,gpu_model=None,device=None):
    output=[]
    for row in records:
        data=np.load(row['mel_cache']);scores=probabilities(session,data['mel'],gpu_model,device)
        labels=data['labels'];times=data['times'];active=[];last=-100.
        for p,end in zip(scores,times):
            if p>=threshold and end-last>=3.:active.append(float(end));last=float(end)
        output.append({key:row[key] for key in ['source_group','split','wake_expected','duration']} | {'kind':row.get('kind','matched-synthetic'),
            'desired_max':float(scores[labels==1].max()) if any(labels==1) else None,'unwanted_max':float(scores[labels==0].max()) if any(labels==0) else None,
            'max_score':float(scores.max()),'activations':active})
    return output


def main(args):
    started=time.monotonic();root=args.output;root.mkdir(parents=True,exist_ok=True)
    source=args.stream_root;manifest=json.loads((source/'streams.json').read_text());validate_streams(manifest['clips'])
    mel_path=source/'backbone/melspectrogram.onnx';mel=frontend(mel_path)
    learning=[r for r in manifest['clips'] if r['split'] in ['train','dev']]
    records=cache_mels(learning,source,root/'mel-cache',mel);x,y,splits,bounds=matrix(records,root)
    session,threshold,temperature,history,dev_details,gpu_model,device=fit(args,x,y,splits,bounds,root)
    development=evaluate_rows(session,[r for r in records if r['split']=='dev'],threshold,gpu_model,device)
    natural=cache_mels([r for r in manifest['clips'] if r['split']=='natural-test'],source,root/'mel-cache',mel)
    natural_test=evaluate_rows(session,natural,threshold,gpu_model,device)
    regression=[];cold_regression=[]
    for item in json.loads((args.corpus/'manifest.json').read_text())['clips']:
        pcm=np.concatenate([wav_read(args.corpus/item['path']).astype(np.int16),np.zeros(RATE,np.int16)])
        windows=raw_windows(pcm,mel);scores=probabilities(session,windows,gpu_model,device)
        indices=np.flatnonzero(scores>=threshold)
        regression.append(dict(item,max_score=float(scores.max()),detected=bool(len(indices)),first_activation_seconds=float((indices[0]+1)*.08) if len(indices) else None))
        cold=raw_windows(pcm,mel,cold=True);cold_scores=probabilities(session,cold,gpu_model,device)
        # First26blocks suppressed, first score block27(index26).
        cold_scores[:26]=0;indices=np.flatnonzero(cold_scores>=threshold)
        cold_regression.append(dict(item,max_score=float(cold_scores.max()),detected=bool(len(indices)),first_activation_seconds=float((indices[0]+1)*.08) if len(indices) else None))
    # CPU timing is a host bound, not a claim about S22 power/latency.
    timing_options=ort.SessionOptions();timing_options.intra_op_num_threads=2;timing_options.inter_op_num_threads=1
    timing_session=ort.InferenceSession(str(root/'hey_chat_logmel_cnn.onnx'),sess_options=timing_options,providers=['CPUExecutionProvider'])
    sample=np.asarray(x[0:1]);timings=[]
    for index in range(110):
        stamp=time.perf_counter();timing_session.run(None,{'input':sample});elapsed=(time.perf_counter()-stamp)*1000
        if index>=10:timings.append(elapsed)
    cpu_latency={'median_ms':float(np.median(timings)),'p95_ms':float(np.percentile(timings,95)),'max_ms':float(max(timings)),
                 'intra_op_threads':2,'hop_ms':80,'handset_measured':False}
    originals={r['source_group']:r for r in regression if r['split']=='held-out-real' and r['kind']=='original'}
    controls=[r for r in regression if not r['wake_expected'] and r['source_group'].startswith('original-')]
    regression_gate=all(r['detected'] for r in originals.values() if r['wake_expected']) and not any(r['detected'] for r in controls)
    report={'feature_type':'logmel-cnn','experimental':True,'acceptance_passed':False,'threshold':threshold,'temperature':temperature,
        'elapsed_seconds':round(time.monotonic()-started,2),'history':history,'dev_calibration':dev_details,
        'temporal_dilations':args.temporal_dilations,
        'development':development,'natural_test':natural_test,'samples':regression,'cold_samples':cold_regression,
        'automated_regression_passed':regression_gate,'cpu_latency':cpu_latency,'model_sha256':sha(root/'hey_chat_logmel_cnn.onnx'),
        'frontend_sha256':sha(mel_path),'input_shape':[1,1,MEL_FRAMES,32],'stream_manifest_sha256':sha(source/'streams.json'),
        'limitations':['Real regression sources never used for training or threshold choice','Natural speech test is read audio, not street/music/wind',
            'No S22 microphone/locked-screen/battery acceptance','Repeatedly inspected regression suite requires new blind field trials']}
    (root/'evaluation.json').write_text(json.dumps(report,indent=2));print(json.dumps({'stage':'cnn-complete','threshold':threshold,'temperature':temperature,'elapsed_seconds':report['elapsed_seconds']}),flush=True)
    for split in ['template','held-out-real','synthetic-evaluation']:
        for kind in ['original','synthetic','augmented']:
            rows=[r for r in regression if r['split']==split and r['kind']==kind]
            if kind=='original':rows=list({r['source_group']:r for r in rows}.values())
            if rows:print(json.dumps({'split':split,'kind':kind,'positives':sum(r['wake_expected'] for r in rows),'missed':sum(r['wake_expected'] and not r['detected'] for r in rows),
                'negatives':sum(not r['wake_expected'] for r in rows),'false':sum(not r['wake_expected'] and r['detected'] for r in rows)}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stream-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--corpus',type=Path,required=True)
    parser.add_argument('--epochs',type=int,default=60);parser.add_argument('--seed',type=int,default=5301)
    parser.add_argument('--max-train-seconds',type=int,default=1800);parser.add_argument('--require-cuda',action='store_true')
    parser.add_argument('--evaluate-only',action='store_true',help='Reuse saved selected checkpoint; never train or change selection')
    parser.add_argument('--temporal-dilations',type=lambda s:tuple(int(x) for x in s.split(',')),default=(2,4,8))
    main(parser.parse_args())
