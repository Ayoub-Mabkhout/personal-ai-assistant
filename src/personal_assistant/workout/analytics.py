"""Recomputable progress, sprint evidence and explicitly app-specific ranks."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from zoneinfo import ZoneInfo

# Small factual ratio tables, verified 2026-11-01. These are not percentile curves.
BENCHMARKS = {
    'bench press (barbell)': ('bench-press', [.50,1.,1.25,1.50,2.], [.30,.50,.75,1.10,1.45]),
    'squat (barbell)': ('squat', [.75,1.25,1.75,2.25,2.75], [.50,.75,1.25,1.75,2.25]),
    'deadlift (barbell)': ('deadlift', [1.,1.50,2.,2.50,3.25], [.75,1.,1.50,2.,2.50]),
    'overhead press (barbell)': ('shoulder-press', [.35,.55,.80,1.05,1.35], [.20,.35,.50,.70,.95]),
}
TIERS = [(0,'Wood'),(200,'Bronze'),(300,'Silver'),(400,'Gold'),(500,'Platinum'),
         (600,'Diamond'),(700,'Champion'),(800,'Titan'),(900,'Olympian')]
METHOD = {'version':'strength-ratios-2026-11-01-v1','cohort':'self-selected Strength Level users',
          'method':'Epley for 2–10 reps; tested single unchanged. Linear score interpolation through published bodyweight-ratio levels at 200/400/600/800/1000.',
          'limitations':'App-specific score, not Liftoff score or a demographic percentile. No age/height adjustment; self-reported lifts; approximate 1RM. Only four named barbell lifts supported.'}


def e1rm(item, hard_only=False):
    if not item.get('completed') or item.get('kind') not in ('working','failure'): return None
    weight, reps = item.get('weight_kg'), item.get('reps')
    if not weight or not reps or not 1<=reps<=10: return None
    hard = (item.get('kind')=='failure' or (item.get('rir') is not None and item['rir']<=2)
            or (item.get('rpe') is not None and item['rpe']>=8))
    if hard_only and not hard: return None
    return weight if reps==1 else weight*(1+reps/30)


def rank(name, estimate, bodyweight, sex):
    source = BENCHMARKS.get(name.casefold())
    if not source: return {'status':'unsupported_exercise'}
    if sex not in ('male','female') or not bodyweight: return {'status':'needs_bodyweight_and_sex'}
    slug, male, female = source
    levels = male if sex=='male' else female
    ratio = estimate/bodyweight
    anchors = [(0.,0),*zip(levels,[200,400,600,800,1000])]
    score = 1000.
    for (x,a),(y,b) in zip(anchors,anchors[1:]):
        if ratio<=y:
            score = a+(ratio-x)/(y-x)*(b-a)
            break
    score = max(0,min(1000,score))
    floor, tier = next(t for t in reversed(TIERS) if score>=t[0])
    following = next(((n,t) for n,t in TIERS if n>score),None)
    target = None
    if following:
        next_score = following[0]
        for (x,a),(y,b) in zip(anchors,anchors[1:]):
            if a<=next_score<=b:
                target = bodyweight*(x+(y-x)*(next_score-a)/(b-a));break
    return {'status':'ranked','score':round(score),'tier':tier,'floor':floor,
            'next_tier':following[1] if following else None,'next_e1rm_kg':round(target,2) if target else None,
            'progress':round((score-floor)/((following[0]-floor) if following else (1000-floor)),3),
            'estimated_1rm_kg':round(estimate,2),'bodyweight_kg':bodyweight, 'sex':sex,
            'source_url':f'https://strengthlevel.com/strength-standards/{slug}/kg',**METHOD}


def day_of(workout):
    at = datetime.fromisoformat(workout['started_at'])
    return at.astimezone(ZoneInfo(workout['timezone'])).date() if at.tzinfo else at.date()


def weight_trend(points, today):
    by_day = defaultdict(list)
    raw = []
    for item in points:
        if item['kind']!='bodyweight': continue
        day = datetime.fromisoformat(item['measured_at']).date()
        if day>today: continue
        by_day[day].append(item['value'])
        raw.append({'measured_at':item['measured_at'],'kg':item['value']})
    days = {d:mean(values) for d,values in by_day.items()}
    series = []
    for day in sorted(days):
        out = {'date':day.isoformat(),'kg':round(days[day],3)}
        for window,minimum in ((7,3),(14,5)):
            values = [v for d,v in days.items() if day-timedelta(days=window-1)<=d<=day]
            out[f'average_{window}d'] = round(mean(values),3) if len(values)>=minimum else None
            out[f'count_{window}d'] = len(values)
        series.append(out)
    latest = series[-1] if series else None
    return {'raw':sorted(raw,key=lambda p:p['measured_at']),'daily':series,'latest':latest,
            'stale':bool(latest and date.fromisoformat(latest['date'])<today-timedelta(days=7)),
            'method':'Daily mean, then unweighted observed-day rolling mean; minimum 3/7 or 5/14 observed days. Missing days are not filled.'}


def overview(store, today=None):
    today = today or datetime.now(timezone.utc).date()
    all_items = store.export()['entities']
    grouped = defaultdict(list)
    for item in all_items:
        if not item['deleted']: grouped[item['kind']].append(item)
    catalog = {r['id']:r['data'] for r in grouped['exercise']}
    profiles = grouped['athlete']
    athlete = profiles[-1]['data'] if profiles else {}
    workouts = sorted(grouped['workout'],key=lambda r:(r['data']['started_at'],r['id']))
    completed = [r for r in workouts if r['data']['status']=='completed' and day_of(r['data'])<=today]
    records, recent, candidates, cardio = {}, {}, {}, []
    measurements = [r['data'] for r in grouped['measurement']]
    for w in completed:
        data = w['data']; day = day_of(data)
        bodyweight = data.get('bodyweight_kg')
        if not bodyweight:
            # Use measured bodyweight no more than 14 days before that performance.
            eligible = [m for m in measurements if m['kind']=='bodyweight'
                        and day-timedelta(days=14)<=datetime.fromisoformat(m['measured_at']).date()<=day]
            if eligible: bodyweight = max(eligible,key=lambda m:m['measured_at'])['value']
        for item in data['sets']:
            eid = item['exercise_id']; ex = catalog.get(eid,{'name':eid,'muscles':[]})
            estimated = e1rm(item)
            if estimated:
                value = {'workout_id':w['id'],'date':day.isoformat(),'set_id':item['id'],
                         'weight_kg':item['weight_kg'],'reps':item['reps'],'estimated_1rm_kg':round(estimated,2),
                         'effort_confirmed':e1rm(item,True) is not None}
                if eid not in records or estimated>records[eid]['estimated_1rm_kg']: records[eid]=value
                if today-timedelta(days=28)<=day:
                    if eid not in recent or estimated>recent[eid]['estimated_1rm_kg']: recent[eid]=value
                    if e1rm(item,True) and bodyweight:
                        result = rank(ex['name'],estimated,bodyweight,athlete.get('sex'))
                        if result['status']=='ranked' and (eid not in candidates or result['score']>candidates[eid]['score']):
                            candidates[eid]={**result,'exercise_id':eid,'name':ex['name'],'muscles':ex['muscles'],'date':day.isoformat()}
            if item.get('completed') and item.get('distance_m') and item.get('seconds'):
                cardio.append({'exercise_id':eid,'date':day.isoformat(),'distance_m':item['distance_m'],
                               'seconds':item['seconds'],'incline_percent':item.get('incline_percent'),
                               'elevation_gain_m':item.get('elevation_gain_m'),'speed_kmh':round(item['distance_m']/item['seconds']*3.6,2),
                               'pace_seconds_per_km':round(item['seconds']/item['distance_m']*1000,1)})
    personal = [{'exercise_id':eid,'name':catalog.get(eid,{}).get('name',eid),'historical_best':value,
                 'recent_best':recent.get(eid),'comeback_ratio':round(recent[eid]['estimated_1rm_kg']/value['estimated_1rm_kg'],3) if eid in recent else None}
                for eid,value in records.items()]
    sprints = []
    for item in grouped['sprint']:
        sprint = item['data']
        within = [w for w in workouts if w['data'].get('sprint_id')==item['id'] and sprint['start']<=day_of(w['data']).isoformat()<=sprint['end']]
        done = [w for w in within if w['data']['status']=='completed']
        adjusted = [w for w in within if w['data']['status']=='skipped' and w['data']['recovery_adjusted']]
        planned = len(sprint['scheduled'])
        denominator = max(0,planned-len(adjusted))
        sprints.append({'id':item['id'],'name':sprint['name'],'phase':sprint['phase'],'status':sprint['status'],
            'planned':planned,'completed':len(done),'recovery_adjusted_skips':len(adjusted),
            'adherence':min(1,len(done)/denominator) if denominator else None,
            'average_duration_seconds':round(mean(w['data']['duration_seconds'] for w in done)) if done else None,
            'success_criteria':sprint['success_criteria'],'interpretation':'Evidence only; specialist reviews goals and proposes next sprint.'})
    muscle_ranks = {}
    for item in candidates.values():
        for muscle in item['muscles']:
            muscle_ranks.setdefault(muscle,[]).append(item['score'])
    achievements = []
    if completed: achievements.append({'id':'first_logged_workout','label':'First logged workout','value':len(completed)})
    for milestone in (10,25,50,100,200):
        if len(completed)>=milestone: achievements.append({'id':f'workouts_{milestone}','label':f'{milestone} workouts recorded','value':milestone})
    cardio_records={}
    for item in cardio:
        key=(item['exercise_id'],item['distance_m'],item['incline_percent'],item['elevation_gain_m'])
        if key not in cardio_records or item['seconds']<cardio_records[key]['seconds']: cardio_records[key]=item
    return {'schema_version':1,'as_of':today.isoformat(),'completed_workouts':len(completed),'exercise_count':len(catalog),
        'personal_records':personal,'ranks':list(candidates.values()),'ranking_method':METHOD,
        'aggregate_score':round(mean(v['score'] for v in candidates.values())) if candidates else None,
        'rank_coverage':{'ranked_lifts':len(candidates),'supported_lifts':len(BENCHMARKS),'window_days':28},
        'muscle_scores':{k:round(mean(v)) for k,v in muscle_ranks.items()},'achievements':achievements,
        'cardio':cardio,'cardio_personal_records':list(cardio_records.values()),
        'bodyweight':weight_trend(measurements,today),'sprints':sprints,'trainer':store.status(),
        'active_workouts':[r for r in workouts if r['data']['status'] in ('active','paused')],
        'latest_workouts':list(reversed(workouts[-10:]))}
