"""Commit a small generic-development Sherpa grid before private regression.

Measures decision time, not just token timestamps. No intents or network APIs.
The old personal corpus is an inspected regression, never calibration input.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import sentencepiece as spm
import sherpa_onnx
from train_personal_wake import wav_read,sha,RATE


def candidate_id(config):
    return hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()[:12]


def make_engine(model,config,folder):
    tokens=spm.SentencePieceProcessor(model_file=str(model/'bpe.model')).encode('HEY CHAT',out_type=str)
    keyword=folder/(candidate_id(config)+'.keywords.txt')
    keyword.write_text(' '.join(tokens)+f" :{config['score']} #{config['threshold']} @HEY_CHAT\n",encoding='utf-8')
    suffix='epoch-12-avg-2-chunk-16-left-64'+('.int8.onnx' if config['precision']=='int8' else '.onnx')
    return sherpa_onnx.KeywordSpotter(**{part:str(model/(part+'-'+suffix)) for part in ['encoder','decoder','joiner']},
        tokens=str(model/'tokens.txt'),keywords_file=str(keyword),num_threads=1,
        keywords_score=config['score'],keywords_threshold=config['threshold'],
        num_trailing_blanks=config['trailing_blanks'],max_active_paths=config['max_active_paths'])


def replay(kws,pcm,continuous=False):
    if not continuous:pcm=np.concatenate([np.zeros(RATE,np.float32),pcm,np.zeros(RATE,np.float32)])
    lead=0 if continuous else 1.;stream=kws.create_stream();events=[];started=time.perf_counter()
    for offset in range(0,len(pcm),320):
        stream.accept_waveform(RATE,pcm[offset:offset+320])
        while kws.is_ready(stream):
            kws.decode_stream(stream);result=kws.keyword_spotter.get_result(stream)
            if result.keyword.strip():
                events.append({'activation_seconds':(offset+320)/RATE-lead,
                    'token_timestamps':[float(t-lead) for t in result.timestamps]})
                kws.reset_stream(stream)
    return events,time.perf_counter()-started


def evaluate(model,config,rows,pcm,output):
    kws=make_engine(model,config,output);results=[];latencies=[];positives=0;detected=0
    false={'natural':0,'no_wake':0,'confusable':0,'post_wake':0};elapsed=0.
    for row in rows:
        events,cost=replay(kws,pcm[row['benchmark_id']]);elapsed+=cost
        expected=row['wake_expected'];valid=[]
        if expected:
            positives+=1;end=row['wake_end']
            valid=[e for e in events if end-.08<=e['activation_seconds']<=end+1.2]
            if valid:detected+=1;latencies.append(valid[0]['activation_seconds']-end)
            false['post_wake']+=int(any(e['activation_seconds']<end-.08 or e['activation_seconds']>end+1.2 for e in events))
        elif events:
            false['natural' if row.get('kind')=='natural' else 'no_wake' if row.get('prefix')=='' else 'confusable']+=1
        results.append({'benchmark_id':row['benchmark_id'],'source_group':row['source_group'],
            'wake_expected':expected,'wake_end':row.get('wake_end'),'events':events,'complete_wake_detected':bool(valid)})
    return {'candidate_id':candidate_id(config),'config':config,'positives':positives,'complete_wakes_detected':detected,
        'recall':detected/max(1,positives),'false_streams':false,'decision_latency_seconds':{
            'median':float(np.median(latencies)) if latencies else None,'p95':float(np.percentile(latencies,95)) if latencies else None},
        'replay_seconds':elapsed,'samples':results}


def grid():
    configs=[{'precision':p,'score':s,'threshold':t,'trailing_blanks':1,'max_active_paths':4}
        for p in ['int8','float32'] for s in [1.5,2.5,3.5] for t in [.08,.2]]
    configs.extend({'precision':p,'score':2.5,'threshold':t,'trailing_blanks':2,'max_active_paths':4}
        for p in ['int8','float32'] for t in [.08,.2])
    configs.extend({'precision':p,'score':2.5,'threshold':.2,'trailing_blanks':1,'max_active_paths':8} for p in ['int8','float32'])
    configs.append({'precision':'int8','score':2.,'threshold':.1,'trailing_blanks':1,'max_active_paths':4})
    return configs


def main(args):
    output=args.output;output.mkdir(parents=True,exist_ok=True)
    if (output/'plan.json').exists():raise ValueError('Output already committed; choose a new experiment directory')
    manifest=json.loads((args.stream_root/'streams.json').read_text());rows=[];natural_seconds=0.
    for row in manifest['clips']:
        if row['split']!='dev':continue
        # All eight development voices; two command tails and clean/noisy variants.
        matched=row.get('kind','matched-synthetic')=='matched-synthetic' and row.get('tail') in [
            'add bananas to my shopping list','set an alarm for seven thirty tomorrow morning'] and row.get('variant') in [0,1]
        isolated=row.get('kind')=='isolated-keyword-control' and row.get('variant')==0
        natural=row.get('kind')=='natural' and natural_seconds<120
        if not (matched or isolated or natural):continue
        if natural:natural_seconds+=row['duration']
        rows.append(dict(row,benchmark_id=f'dev-{len(rows):04d}'))
    configs=grid();plan={'sherpa_version':sherpa_onnx.__version__,'configs':configs,'rows':rows,
        'stream_manifest_sha256':sha(args.stream_root/'streams.json'),'model_files':{p.name:sha(p) for p in args.model.glob('*.onnx')},
        'selection':'Prefer >=90% complete-wake dev recall and no natural/no-wake dev errors, then confusable errors, then latency; otherwise highest recall after excluding natural/no-wake errors',
        'personal_regression_used_for_selection':False,'latency_reference':'Activation time minus annotated wake end,80ms crop tolerance'}
    (output/'plan.json').write_text(json.dumps(plan,indent=2))
    pcm={}
    for row in rows:
        path=Path(row['path']);path=path if path.is_absolute() else args.stream_root/path
        pcm[row['benchmark_id']]=wav_read(path)/32768.
    print(json.dumps({'stage':'grid-committed','candidates':len(configs),'dev_streams':len(rows),'natural_seconds':natural_seconds}),flush=True)
    results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks=[pool.submit(evaluate,args.model,c,rows,pcm,output) for c in configs]
        for task in as_completed(tasks):
            result=task.result();results.append(result)
            (output/(result['candidate_id']+'.json')).write_text(json.dumps(result,indent=2))
            print(json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)
    def rank(row):
        f=row['false_streams'];clean=f['natural']==0 and f['no_wake']==0
        sufficient=clean and row['recall']>=.9
        return (sufficient,clean,-f['confusable'] if sufficient else row['recall'],row['recall'],
            -(row['decision_latency_seconds']['p95'] or 100))
    selected=max(results,key=rank)
    summary={'selected':{k:v for k,v in selected.items() if k!='samples'},
        'grid':[{k:v for k,v in r.items() if k!='samples'} for r in results],'diagnostic_only':True,'acceptance_passed':False}
    (output/'selection.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({'stage':'selection-frozen','selected':summary['selected']}),flush=True)
    # One evaluation of selected settings only; no scans on the old recordings.
    kws=make_engine(args.model,selected['config'],output);regression=[]
    for item in json.loads((args.corpus/'manifest.json').read_text())['clips']:
        events,cost=replay(kws,wav_read(args.corpus/item['path'])/32768.)
        regression.append(dict(item,events=events,detected=bool(events),replay_seconds=cost))
    natural=[r for r in manifest['clips'] if r['split']=='natural-test'];negative=[]
    for row in natural:
        path=Path(row['path']);path=path if path.is_absolute() else args.stream_root/path
        negative.append(wav_read(path)/32768.)
    continuous=np.concatenate(negative);events,cost=replay(kws,continuous,continuous=True)
    report={'selection':summary['selected'],'samples':regression,'natural_continuous':{'duration_seconds':len(continuous)/RATE,
        'false_events':events,'false_events_per_hour':len(events)*3600/(len(continuous)/RATE),'replay_seconds':cost},
        'diagnostic_only':True,'acceptance_passed':False,'limitations':['Existing personal set is an inspected regression, not fresh blind acceptance',
            'Natural read speech is not a street recording','No handset or battery proof','Parameters frozen before regression replay']}
    (output/'regression.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'stage':'complete','natural_false_events':len(events),'selected':selected['config']}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--stream-root',type=Path,required=True);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--workers',type=int,default=3)
    main(p.parse_args())
