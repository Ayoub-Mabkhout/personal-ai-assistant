"""Summarize selected wake experiments without changing a model or threshold."""
import argparse
import json
from pathlib import Path
import numpy as np


def counts(rows):
    positive=[r for r in rows if r['wake_expected']];negative=[r for r in rows if not r['wake_expected']]
    def detected(r):return r.get('detected',bool(r.get('activations')))
    return {'positive_count':len(positive),'positive_detected':sum(detected(r) for r in positive),
        'negative_count':len(negative),'negative_triggered':sum(detected(r) for r in negative)}


def main(args):
    report=json.loads((args.model_root/'evaluation.json').read_text())
    streams=json.loads((args.stream_root/'streams.json').read_text());groups={r['source_group']:r for r in streams['clips']}
    summary={k:report[k] for k in ['feature_type','threshold','model_sha256','automated_regression_passed','acceptance_passed','cpu_latency']}
    samples=report['samples'];originals=list({r['source_group']:r for r in samples if r['split']=='held-out-real' and r['kind']=='original'}.values())
    summary['unique_personal_originals']=counts(originals)
    summary['personal_augmentations']=counts([r for r in samples if r['split']=='held-out-real' and r['kind']=='augmented'])
    summary['template_originals']=counts([r for r in samples if r['split']=='template' and r['kind']=='original'])
    summary['natural_test']=counts(report['natural_test'])
    dev=report['development'];summary['development']=counts(dev);strata={}
    summary['development_complete_wakes']={'positive_count':sum(r['wake_expected'] for r in dev),
        'positive_detected':sum(r['wake_expected'] and r['desired_max'] is not None and r['desired_max']>=report['threshold'] for r in dev)}
    for name,lo,hi in [('under_0.6',0,.6),('0.6_to_0.9',.6,.9),('0.9_to_1.27',.9,1.27),('at_least_1.27',1.27,100)]:
        selected=[r for r in dev if r['wake_expected'] and lo<=groups[r['source_group']]['wake_end']-groups[r['source_group']]['wake_start']<hi]
        strata[name]={'positive_count':len(selected),'positive_detected':sum(r['desired_max'] is not None and r['desired_max']>=report['threshold'] for r in selected)}
    summary['development_wake_duration_seconds']=strata
    wanted=np.asarray([r['desired_max'] for r in dev if r['wake_expected'] and r['desired_max'] is not None])
    operating=[]
    for recall in [.5,.8,.9,.95]:
        threshold=float(np.quantile(wanted,1-recall))
        operating.append({'target_development_recall':recall,'diagnostic_threshold':threshold,
            'actual_development_recall':float(np.mean(wanted>=threshold)),
            'all_unwanted_streams':sum(r['unwanted_max'] is not None and r['unwanted_max']>=threshold for r in dev),
            'natural_negative_streams_triggered':sum(r['max_score']>=threshold for r in dev if r['kind']=='natural'),
            'matched_negative_streams_triggered':sum(r['max_score']>=threshold for r in dev if r['kind']!='natural' and not r['wake_expected'])})
    summary['diagnostic_development_operating_points']=operating
    summary['top_development_unwanted']=[{'source_group':r['source_group'],'kind':r['kind'],
        'prefix':groups[r['source_group']].get('prefix'),'duration':r['duration'],'unwanted_max':r['unwanted_max']}
        for r in sorted([r for r in dev if r['unwanted_max'] is not None],key=lambda r:r['unwanted_max'],reverse=True)[:8]]
    if args.output:args.output.write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model-root',type=Path,required=True)
    p.add_argument('--stream-root',type=Path,required=True);p.add_argument('--output',type=Path)
    main(p.parse_args())
