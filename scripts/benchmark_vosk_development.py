"""Evaluate a predeclared contrast grammar on annotated dev and continuous negatives."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time
import wave

from vosk import Model,KaldiRecognizer,SetLogLevel
from evaluate_vosk_wake import GRAMMARS,run_clip,is_wake


def source_pcm(path):
    with wave.open(str(path),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000):raise ValueError('Expected PCM16 mono16k')
        return wav.readframes(wav.getnframes())


def main(args):
    output=args.output;output.mkdir(parents=True,exist_ok=True)
    if (output/'plan.json').exists():raise ValueError('Preserve committed experiment')
    plan=json.loads(args.sherpa_plan.read_text());grammar=GRAMMARS['contrasts-unknown']
    own={'grammar':grammar,'partial_words':False,'stable_audio_ms':80,'frame_samples':320,
        'sherpa_dev_plan_sha256':hashlib.sha256(args.sherpa_plan.read_bytes()).hexdigest(),
        'policy_changed_from_personal_results':False,'acceptance_passed':False}
    (output/'plan.json').write_text(json.dumps(own,indent=2));SetLogLevel(-1)
    stamp=time.perf_counter();model=Model(str(args.model));load_seconds=time.perf_counter()-stamp
    rows=[];latencies=[];pos=0;detected=0;false={'natural':0,'no_wake':0,'confusable':0};premature=0
    for index,row in enumerate(plan['rows']):
        path=Path(row['path']);path=path if path.is_absolute() else args.stream_root/path
        result=run_clip(model,path,grammar,False);trigger=result['stable_80ms_partial_wake_seconds']
        valid=False
        if row['wake_expected']:
            pos+=1
            if trigger is not None:
                delta=trigger-row['wake_end'];valid=-.08<=delta<=1.2
                if valid:detected+=1;latencies.append(delta)
                elif delta<-.08:premature+=1
        elif trigger is not None:false['natural' if row.get('kind')=='natural' else 'no_wake' if row.get('prefix')=='' else 'confusable']+=1
        rows.append({'source_group':row['source_group'],'wake_expected':row['wake_expected'],'wake_end':row['wake_end'],
            'complete_wake_detected':valid,'activation_seconds':trigger,'frame_p95_ms':result['frame_p95_ms']})
        if index%50==0:print(json.dumps({'stage':'vosk-development','completed':index+1}),flush=True)
    manifest=json.loads((args.stream_root/'streams.json').read_text());natural=[];natural_sources=[]
    for row in manifest['clips']:
        if row['split']=='natural-test':
            path=Path(row['path']);natural.append(source_pcm(path if path.is_absolute() else args.stream_root/path))
            natural_sources.append({'source_group':row['source_group'],'source_sha256':row.get('source_sha256'),
                'wav_sha256':row.get('wav_sha256'),'duration':row['duration']})
    pcm=b''.join(natural);rec=KaldiRecognizer(model,16000,json.dumps(grammar));rec.SetWords(True);rec.SetPartialWords(False)
    events=[];stable=0;last=-100.;timings=[];stamp=time.perf_counter()
    for offset in range(0,len(pcm),640):
        frame=pcm[offset:offset+640];start=time.perf_counter();final=rec.AcceptWaveform(frame)
        value=json.loads(rec.Result() if final else rec.PartialResult());timings.append((time.perf_counter()-start)*1000)
        text=value.get('text' if final else 'partial','')
        stable=stable+1 if not final and is_wake(text) else 0
        at=(offset+len(frame))/32000
        if stable>=4 and at-last>=3:events.append(at);last=at
    continuous_seconds=len(pcm)/32000;processing=time.perf_counter()-stamp
    report={'policy':own,'model_load_seconds':load_seconds,'development':{'positive_count':pos,'complete_wakes_detected':detected,
        'false_streams':false,'premature_positive_streams':premature,'latency_seconds':{'median':statistics.median(latencies) if latencies else None,
            'p95':sorted(latencies)[int(.95*len(latencies))] if latencies else None},'samples':rows},
        'continuous_natural_test':{'duration_seconds':continuous_seconds,'reset_count':1,'false_events':events,
            'pcm_sha256':hashlib.sha256(pcm).hexdigest(),'sources':natural_sources,
            'false_events_per_hour':len(events)*3600/continuous_seconds,'processing_seconds':processing,
            'frame_p95_ms':sorted(timings)[int(.95*len(timings))],'frame_max_ms':max(timings)},
        'diagnostic_only':True,'acceptance_passed':False,'limitations':['Read speech, not hours of actual phone noise',
            '80ms stable uncommitted hypotheses can retract','Fixed policy; no threshold or grammar edits during evaluation',
            'Host CPU timing, no handset acceptance']}
    (output/'evaluation.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='development'}))
    print(json.dumps({k:v for k,v in report['development'].items() if k!='samples'}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--stream-root',type=Path,required=True);p.add_argument('--sherpa-plan',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);main(p.parse_args())
