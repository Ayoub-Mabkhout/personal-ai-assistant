"""Exercise/session metrics and explicitly tagged running benchmarks."""
from collections import defaultdict
from datetime import date,timedelta

MILE_M=1609.344


def metrics(rows,today):
    from .analytics import day_of,e1rm,running_rank
    catalog={r['id']:r['data'] for r in rows if r['kind']=='exercise' and not r['deleted']}
    profiles=[r for r in rows if r['kind']=='athlete' and not r['deleted']]
    sex=max(profiles,key=lambda p:p['updated'])['data'].get('sex') if profiles else None
    exercises=defaultdict(lambda:{'e1rm_series':[],'volume_series':[]})
    sessions=[];runs=[];warmups=[]
    for row in rows:
        if row['kind']!='workout' or row['deleted'] or row['data']['status']!='completed': continue
        w=row['data'];day=day_of(w)
        if day>today: continue
        grouped=defaultdict(lambda:{'volume':0.,'e1rm':None,'working_sets':0})
        for s in w['sets']:
            if not s.get('completed'): continue
            eid=s['exercise_id'];ex=catalog.get(eid,{})
            running=ex.get('movement')=='run' or 'running' in ex.get('name','').casefold()
            if running and s.get('distance_m') and s.get('seconds'):
                value={'date':day.isoformat(),'workout_id':row['id'],'exercise_id':eid,'set_id':s['id'],
                    'distance_m':s['distance_m'],'seconds':s['seconds'],'speed_kmh':s['distance_m']/s['seconds']*3.6,
                    'pace_seconds_per_km':s['seconds']/s['distance_m']*1000,'incline_percent':s.get('incline_percent')}
                if s['kind']=='working': runs.append(value)
                else: warmups.append(value)
            if s['kind'] not in ('working','failure','drop'): continue
            group=grouped[eid];group['working_sets']+=1
            group['volume']+=(s.get('weight_kg') or 0)*(s.get('reps') or 0)
            estimate=e1rm(s)
            if estimate is not None: group['e1rm']=max(group['e1rm'] or 0,estimate)
        per_exercise=[]
        for eid,group in grouped.items():
            ex=catalog.get(eid,{})
            point={'date':day.isoformat(),'workout_id':row['id']}
            stats=exercises[eid]
            stats.update(exercise_id=eid,name=ex.get('name',eid),load_convention=ex.get('load_convention','unknown'))
            stats['volume_series'].append({**point,'value':round(group['volume'],3)})
            if group['e1rm'] is not None: stats['e1rm_series'].append({**point,'value':round(group['e1rm'],3)})
            per_exercise.append({'exercise_id':eid,'e1rm_kg':round(group['e1rm'],3) if group['e1rm'] is not None else None,
                                 'volume_kg_reps':round(group['volume'],3),'sets':group['working_sets']})
        total=round(sum(g['volume'] for g in grouped.values()),3)
        sessions.append({'workout_id':row['id'],'date':day.isoformat(),'total_volume':total,'total_volume_kg_reps':total,
                         'exercises':per_exercise,'e1rm_by_exercise':{x['exercise_id']:x['e1rm_kg'] for x in per_exercise}})
    for stats in exercises.values():
        for key in ('e1rm_series','volume_series'): stats[key].sort(key=lambda p:(p['date'],p['workout_id']))
    current=[r for r in runs if today-timedelta(days=28)<=date.fromisoformat(r['date'])<=today]
    flat=lambda r:r.get('incline_percent') in (None,0)
    benchmark=1.5*MILE_M
    observed=[r for r in runs if abs(r['distance_m']-benchmark)<=5 and flat(r)]
    observed=min(observed,key=lambda r:r['seconds'],default=None)
    projected=[r for r in current if 1000<=r['distance_m']<=10000 and flat(r)]
    projected=min(projected,key=lambda r:r['pace_seconds_per_km'],default=None)
    best=lambda values:min(values,key=lambda r:r['pace_seconds_per_km'],default=None)
    return {'exercise_stats':list(exercises.values()),'workout_metrics':sessions,
        'running':{'rank':running_rank(runs,today,sex),'best_working':best(current),'historical_best_working':best(runs),
                   'recent_working':sorted(current,key=lambda r:(r['date'],r['workout_id'])),
                   'warmup_count':len(warmups),'working_count':len(runs),'current_window_days':28,
                   'benchmark_1_5mi':{'distance_m':benchmark,'observed':observed,
                       'projected':{'seconds':projected['seconds']*benchmark/projected['distance_m'],
                                    'date':projected['date'],'method':'Same-pace projection, not an observed performance',
                                    'source_distance_m':projected['distance_m']} if projected else None}},
        'volume_method':'Recorded external load × completed reps; warmups excluded, drop sets included. Per-hand loads remain per hand; unmeasured bodyweight is not guessed.'}
