"""Replay energy endpointing with measured wakes and explicit background scenarios.

No recognition/API work: reads previously frozen wake results. Speech-end reference
is an energy-envelope estimate, not manually annotated phoneme ground truth.
"""
import argparse
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import wave

import numpy as np

GATES={'old':{'minimum':450.,'ratio':2.8,'initial':150.,'ambient_minimum':100.},
       'new':{'minimum':80.,'ratio':2.,'initial':40.,'ambient_minimum':20.}}


def read(path):
    with wave.open(str(path),'rb') as wav:
        assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())==(1,2,16000)
        return np.frombuffer(wav.readframes(wav.getnframes()),'<i2').copy()


def rms_frames(pcm):
    pcm=np.pad(pcm,(0,(-len(pcm))%320)).astype(np.float64).reshape(-1,320)
    return np.sqrt(np.mean(pcm**2,axis=1))


def endpoint(levels,trigger_frame,settings):
    floor=settings['initial'];ambient=deque();voiced=6400;quiet=0;elapsed=0;count=0
    for frame,rms in enumerate(levels):
        speech=rms>max(settings['minimum'],floor*settings['ratio'])
        if frame<=trigger_frame:
            ambient.append(float(rms))
            if len(ambient)>150:ambient.popleft()
            if len(ambient)>=20 and len(ambient)%5==0:
                sorted_levels=sorted(ambient);floor=max(settings['ambient_minimum'],sorted_levels[len(ambient)//5])
            elif not speech:floor=.995*floor+.005*rms
            continue
        elapsed+=320
        if speech:voiced+=320;quiet=0;count+=1
        else:quiet+=320
        if (voiced>=6400 and quiet>=19200) or elapsed>=480000:
            return {'endpoint_frame':frame,'seconds_after_trigger':elapsed/16000,'reason':'maximum_duration' if elapsed>=480000 else 'silence',
                'frozen_noise_floor':float(floor),'speech_frames':count,'observed_frames':elapsed//320}
    return {'endpoint_frame':None,'seconds_after_trigger':None,'reason':'insufficient_flush','frozen_noise_floor':float(floor),
        'speech_frames':count,'observed_frames':elapsed//320}


def main(args):
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    if (out/'evaluation.json').exists():raise ValueError('Preserve prior gate report')
    manifest=json.loads((args.corpus/'manifest.json').read_text());wake=json.loads(args.wake_report.read_text())['samples']
    rows=[]
    for item in manifest['clips']:
        if item['kind']!='original' or not item['wake_expected']:continue
        pcm=read(args.corpus/item['path']);levels=rms_frames(pcm)
        noise=float(np.percentile(levels,20));threshold=max(100.,noise*2.5)
        active=np.flatnonzero(levels>threshold);reference_end=float((active[-1]+1)*.02) if len(active) else len(pcm)/16000
        for attenuation in [1.,.5,.25,.1,.03]:
            for gain in [1.,2.]:
                record=next(r for r in wake if r['id']==item['id'] and r['attenuation']==attenuation and r['gain']==gain and r['stability_ms']==80)
                if not record['detected']:
                    rows.append({'id':item['id'],'source_group':item['source_group'],'attenuation':attenuation,'detector_gain':gain,'wake_detected':False});continue
                raw=(pcm.astype(np.float32)*attenuation).astype(np.int16)
                padded=np.concatenate([np.zeros(16000,np.int16),raw,np.zeros(64000,np.int16)])
                trigger=int(round((record['first_activation_seconds']+1)/.02))-1
                result={'id':item['id'],'source_group':item['source_group'],'attenuation':attenuation,'detector_gain':gain,
                    'wake_detected':True,'activation_seconds':record['first_activation_seconds'],'reference_speech_end':reference_end,'gates':{}}
                for name,settings in GATES.items():
                    gate=endpoint(rms_frames(padded),trigger,settings)
                    if gate['endpoint_frame'] is not None:
                        gate['endpoint_clip_seconds']=(gate['endpoint_frame']+1)*.02-1
                        gate['estimated_missing_tail_seconds']=max(0.,reference_end-gate['endpoint_clip_seconds'])
                        gate['estimated_tail_clipped']=gate['estimated_missing_tail_seconds']>.08
                    result['gates'][name]=gate
                rows.append(result)
    if args.tts_manifest and args.vosk_clip_report:
        external=json.loads(args.tts_manifest.read_text())['clips']
        recognized=json.loads(args.vosk_clip_report.read_text())['grammars']['contrasts-unknown']['clips']
        triggers={r['id']:r['stable_80ms_partial_wake_seconds'] for r in recognized}
        for item in external:
            if item['kind']!='one-take' or triggers.get(item['id']) is None:continue
            pcm=read(Path(item['path']));levels=rms_frames(pcm)
            active=np.flatnonzero(levels>max(100.,float(np.percentile(levels,20))*2.5))
            reference_end=float((active[-1]+1)*.02) if len(active) else len(pcm)/16000
            trigger_seconds=triggers[item['id']];trigger=int(round((trigger_seconds+1)/.02))-1
            for attenuation in [1.,.5,.25,.1,.03]:
                raw=(pcm.astype(np.float32)*attenuation).astype(np.int16)
                levels=rms_frames(np.concatenate([np.zeros(16000,np.int16),raw,np.zeros(64000,np.int16)]))
                result={'id':item['id'],'source_group':item['source_group'],'dataset':'synthetic-one-take',
                    'attenuation':attenuation,'detector_gain':1.,'wake_detected':True,
                    'activation_seconds':trigger_seconds,'wake_timing_assumed_from_normal_volume':True,
                    'reference_speech_end':reference_end,'gates':{}}
                for name,settings in GATES.items():
                    gate=endpoint(levels,trigger,settings)
                    if gate['endpoint_frame'] is not None:
                        gate['endpoint_clip_seconds']=(gate['endpoint_frame']+1)*.02-1
                        gate['estimated_missing_tail_seconds']=max(0.,reference_end-gate['endpoint_clip_seconds'])
                        gate['estimated_tail_clipped']=gate['estimated_missing_tail_seconds']>.08
                    result['gates'][name]=gate
                rows.append(result)
    rng=np.random.default_rng(9229);background=[]
    # Stable broadband noise, with stationary-room warmup and sudden-after-wake
    # variants. These are explicit synthetic stress tests, not field recordings.
    for target in [0.,30.,60.,100.,300.,600.]:
        noise=rng.normal(size=33*16000);noise*=target/max(np.sqrt(np.mean(noise**2)),1e-9)
        for scenario in ['stationary','starts_after_wake']:
            pcm=np.clip(noise,-32768,32767).astype(np.int16)
            if scenario=='starts_after_wake':pcm[:3*16000]=0
            result={'scenario':scenario,'noise_rms':target,'gates':{}}
            for name,settings in GATES.items():result['gates'][name]=endpoint(rms_frames(pcm),149,settings)
            background.append(result)
    # A representative real licensed speech source checks behavior on voices;
    # read speech may correctly keep an energy gate open and is not silent noise.
    source=json.loads(args.background_manifest.read_text());natural=[r for r in source['clips'] if r['split']=='natural-test'][:8]
    voice=np.concatenate([read(Path(r['path'])) for r in natural])[:33*16000]
    for attenuation in [1.,.1,.03]:
        levels=rms_frames((voice.astype(np.float32)*attenuation).astype(np.int16))
        background.append({'scenario':'continuous_read_speech','attenuation':attenuation,
            'gates':{name:endpoint(levels,149,settings) for name,settings in GATES.items()}})
    summaries=[]
    for dataset in ['original','synthetic-one-take']:
      for gain in [1.,2.]:
        for attenuation in [1.,.5,.25,.1,.03]:
            selected=list({r['source_group']:r for r in rows if r.get('dataset','original')==dataset and r['detector_gain']==gain and r['attenuation']==attenuation}.values())
            if not selected:continue
            summaries.append({'dataset':dataset,'gain':gain,'attenuation':attenuation,'unique_positive_families':len(selected),
                'missing_wakes':sum(not r['wake_detected'] for r in selected),
                'gate_clipped_tails':{name:sum(r['wake_detected'] and r['gates'][name].get('estimated_tail_clipped',False) for r in selected) for name in GATES}})
    report={'settings':GATES,'wake_seed_voiced_samples':6400,'silence_samples':19200,'maximum_samples':480000,
        'source_hashes':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [args.corpus/'manifest.json',
            args.wake_report,args.background_manifest,*([args.tts_manifest,args.vosk_clip_report] if args.tts_manifest and args.vosk_clip_report else [])]},
        'originals':rows,'summaries':summaries,'background':background,'diagnostic_only':True,'acceptance_passed':False,
        'limitations':['Speech end is estimated from full-amplitude envelope, not manually annotated',
            'Uniform attenuation preserves SNR and does not reproduce Android processing','Read speech can correctly keep capture active',
            'Synthetic stationary noise is not a handset/street recording','Live sockets use separate server endpointing']}
    (out/'evaluation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'summaries':summaries,'background':[{'scenario':row['scenario'],
        'noise_rms':row.get('noise_rms'),'attenuation':row.get('attenuation'),
        'seconds_after_trigger':{key:value['seconds_after_trigger'] for key,value in row['gates'].items()}} for row in background]}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--wake-report',type=Path,required=True);p.add_argument('--background-manifest',type=Path,required=True)
    p.add_argument('--tts-manifest',type=Path);p.add_argument('--vosk-clip-report',type=Path)
    p.add_argument('--output',type=Path,required=True);main(p.parse_args())
