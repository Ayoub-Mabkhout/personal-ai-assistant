"""Detector-only PCM gain/stability experiment with development-first selection.

The stored/streamed capture stays raw. Attenuation tests amplitude, not real
distance/SNR or Android audio-source processing. No paid speech or live intents.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import wave

import numpy as np
from vosk import Model,KaldiRecognizer,SetLogLevel
from evaluate_vosk_wake import GRAMMARS,is_wake

GAINS=[1.,2.,3.,4.]
ATTENUATIONS=[1.,.5,.25,.1,.03]


def read(path):
    with wave.open(str(path),'rb') as wav:
        assert (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())==(1,2,16000)
        return np.frombuffer(wav.readframes(wav.getnframes()),'<i2').copy()


def replay(model,pcm,gain,attenuation=1.,continuous=False):
    # Quantize quiet raw capture first, then apply gain only for recognition.
    raw=np.clip(pcm.astype(np.float32)*attenuation,-32768,32767).astype(np.int16)
    amplified=raw.astype(np.float32)*gain
    clipping=int(np.count_nonzero((amplified>32767)|(amplified<-32768)))
    detector=np.clip(amplified,-32768,32767).astype('<i2').tobytes()
    if not continuous:detector=bytes(32000)+detector+bytes(32000)
    lead=0. if continuous else 1.
    rec=KaldiRecognizer(model,16000,json.dumps(GRAMMARS['contrasts-unknown']));rec.SetPartialWords(False)
    events={'40':[],'80':[]};last={'40':-100.,'80':-100.};stable=0;started=time.perf_counter()
    for offset in range(0,len(detector),640):
        frame=detector[offset:offset+640];final=rec.AcceptWaveform(frame)
        obj=json.loads(rec.Result() if final else rec.PartialResult());text=obj.get('text' if final else 'partial','')
        stable=stable+1 if not final and is_wake(text) else 0
        end=(offset+len(frame))/32000-lead
        for key,frames in [('40',2),('80',4)]:
            if stable>=frames and end-last[key]>=3.:events[key].append(end);last[key]=end
    return {'events':events,'clipped_samples':clipping,'sample_count':len(raw),
        'raw_rms':float(np.sqrt(np.mean(raw.astype(np.float64)**2))),
        'processing_seconds':time.perf_counter()-started}


def main(args):
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    if args.regression_only:
        # All precommitted profiles may be compared as regressions, but the dev
        # selection stays immutable. Do not use these results to change policy.
        saved=out/'regression-all-fixed-profiles.json'
        if saved.exists():raise ValueError('Preserve prior regression expansion')
        plan=json.loads((out/'plan.json').read_text());selection=(out/'selection.json').read_bytes()
        SetLogLevel(-1);model=Model(str(args.model));results=[]
        for row in json.loads((args.corpus/'manifest.json').read_text())['clips']:
            if row['kind']!='original':continue
            pcm=read(args.corpus/row['path'])
            for attenuation in plan['attenuations']:
                for gain in plan['gains']:
                    result=replay(model,pcm,gain,attenuation)
                    for stability in plan['stability_ms']:
                        results.append({'id':row['id'],'source_group':row['source_group'],'wake_expected':row['wake_expected'],
                            'attenuation':attenuation,'gain':gain,'stability_ms':stability,
                            'detected':bool(result['events'][str(stability)]),
                            'first_activation_seconds':result['events'][str(stability)][0] if result['events'][str(stability)] else None,
                            'raw_rms':result['raw_rms'],'clipped_samples':result['clipped_samples']})
            print(json.dumps({'stage':'fixed-profile-regression','id':row['id']}),flush=True)
        report={'dev_selection_sha256':hashlib.sha256(selection).hexdigest(),'selection_unchanged':True,
            'profiles_declared_before_regression':True,'samples':results,'acceptance_passed':False}
        saved.write_text(json.dumps(report,indent=2));print(json.dumps({'stage':'regression-complete','cases':len(results)}))
        return
    if (out/'plan.json').exists():raise ValueError('Preserve committed experiment')
    plan=json.loads(args.dev_plan.read_text());rows=[]
    for row in plan['rows']:
        # All eight dev voices: one clean matched tail per voice/prefix.
        if row.get('tail')=='add bananas to my shopping list' and row.get('variant')==0:
            rows.append(row)
    own={'grammar':GRAMMARS['contrasts-unknown'],'gains':GAINS,'attenuations':ATTENUATIONS,'stability_ms':[40,80],
        'dev_plan_sha256':hashlib.sha256(args.dev_plan.read_bytes()).hexdigest(),'dev_rows':rows,
        'selection':'Only profiles adding no ordinary/confusable dev negative triggers to balanced may compete; maximize quiet complete wakes then all complete wakes, prefer lower gain and80ms on ties',
        'personal_used_for_selection':False,'detector_only_gain':True,'limitations':['Amplitude attenuation preserves SNR; not a physical distance test','No Android AudioSource processing reproduced']}
    (out/'plan.json').write_text(json.dumps(own,indent=2));SetLogLevel(-1);model=Model(str(args.model))
    observations=[]
    for index,row in enumerate(rows):
        path=Path(row['path']);pcm=read(path if path.is_absolute() else args.stream_root/path)
        levels=ATTENUATIONS if row['wake_expected'] else [1.,.1,.03]
        for attenuation in levels:
            for gain in GAINS:
                result=replay(model,pcm,gain,attenuation)
                observations.append({'id':row['benchmark_id'],'wake_expected':row['wake_expected'],'wake_end':row['wake_end'],
                    'source_group':row['source_group'],'prefix':row.get('prefix'),'attenuation':attenuation,'gain':gain,**result})
        if index%8==0:print(json.dumps({'stage':'generic-dev','clips':index+1,'observations':len(observations)}),flush=True)
    profiles=[]
    for gain in GAINS:
        for stability in [40,80]:
            selected=[r for r in observations if r['gain']==gain];positive=[];quiet=[];negative=set()
            for row in selected:
                event=row['events'][str(stability)]
                valid=any(row['wake_end']-.08<=e<=row['wake_end']+1.2 for e in event) if row['wake_expected'] else False
                if row['wake_expected']:
                    positive.append(valid)
                    if row['attenuation']<=.25:quiet.append(valid)
                elif event:negative.add(row['id']+':'+str(row['attenuation']))
            profiles.append({'gain':gain,'stability_ms':stability,'complete_wakes':sum(positive),'positive_cases':len(positive),
                'quiet_complete_wakes':sum(quiet),'quiet_cases':len(quiet),'negative_trigger_cases':sorted(negative)})
    baseline=next(p for p in profiles if p['gain']==1 and p['stability_ms']==80)
    for profile in profiles:profile['new_negative_cases']=sorted(set(profile['negative_trigger_cases'])-set(baseline['negative_trigger_cases']))
    eligible=[p for p in profiles if not p['new_negative_cases']]
    selected=max(eligible,key=lambda p:(p['quiet_complete_wakes'],p['complete_wakes'],-p['gain'],p['stability_ms']))
    (out/'selection.json').write_text(json.dumps({'selected':selected,'baseline':baseline,'profiles':profiles},indent=2))
    print(json.dumps({'stage':'policy-frozen','selected':selected,'baseline':baseline}),flush=True)
    # Only balanced and the frozen selected gain/stability run old personal data.
    regressions=[];policies=[baseline] if selected==baseline else [baseline,selected]
    originals=[r for r in json.loads((args.corpus/'manifest.json').read_text())['clips'] if r['kind']=='original']
    for row in originals:
        pcm=read(args.corpus/row['path'])
        for attenuation in ATTENUATIONS:
            for policy in policies:
                result=replay(model,pcm,policy['gain'],attenuation)
                regressions.append({'id':row['id'],'source_group':row['source_group'],'wake_expected':row['wake_expected'],
                    'attenuation':attenuation,'gain':policy['gain'],'stability_ms':policy['stability_ms'],
                    'detected':bool(result['events'][str(policy['stability_ms'])]),**result})
    manifest=json.loads((args.stream_root/'streams.json').read_text());negative=[];sources=[]
    for row in manifest['clips']:
        if row['split']=='natural-test':
            path=Path(row['path']);negative.append(read(path if path.is_absolute() else args.stream_root/path));sources.append(row['source_group'])
    pcm=np.concatenate(negative);continuous=[]
    for gain in GAINS:
        result=replay(model,pcm,gain,continuous=True)
        for stability in [40,80]:
            events=result['events'][str(stability)]
            continuous.append({'gain':gain,'stability_ms':stability,'seconds':len(pcm)/16000,
                'events':events,'false_events_per_hour':len(events)*3600/(len(pcm)/16000),
                'processing_seconds':result['processing_seconds'],'clipped_samples':result['clipped_samples'],'sources':sources})
        print(json.dumps({'stage':'continuous-background','gain':gain,'events40':len(result['events']['40']),
            'events80':len(result['events']['80'])}),flush=True)
    report={'selection':selected,'baseline':baseline,'profiles':profiles,'dev_observations':observations,
        'original_regression':regressions,'continuous_negatives':continuous,'diagnostic_only':True,'acceptance_passed':False,
        'gain_improves_dev_quiet_recall':selected['quiet_complete_wakes']>baseline['quiet_complete_wakes'],
        'limitations':own['limitations']+['Existing personal recordings are inspected regressions','Short read speech does not certify field false-wake rate']}
    (out/'evaluation.json').write_text(json.dumps(report,indent=2));print(json.dumps({'stage':'complete',
        'selected':selected,'gain_improves_dev_quiet_recall':report['gain_improves_dev_quiet_recall'],
        'continuous':[{'gain':r['gain'],'stability_ms':r['stability_ms'],'false_events':len(r['events'])} for r in continuous]}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--dev-plan',type=Path,required=True);p.add_argument('--stream-root',type=Path,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--regression-only',action='store_true',help='Compare all previously committed profiles without changing dev selection')
    main(p.parse_args())
