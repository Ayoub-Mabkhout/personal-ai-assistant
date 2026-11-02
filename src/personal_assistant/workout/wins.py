"""What each finished session achieved: records against earlier sessions, and rank steps."""
from datetime import timedelta
from statistics import mean
from .analytics import BENCHMARKS,RANK_WINDOW,TIERS,bodyweight_reps,run_score,day_of,e1rm,rank,rank_reps,rep_lift,session_bodyweight

WINDOW=timedelta(days=28)
METRICS=('estimated_max','heaviest','set_volume','most_reps','pace')


def tier_of(score): return next(name for floor,name in reversed(TIERS) if score>=floor)


def best_sets(sets, catalog):
    """A session's best numbers per exercise, from hard work only: warm-ups and drops set no records."""
    found={}
    for s in sets:
        if not s.get('completed'): continue
        eid=s['exercise_id'];best=found.setdefault(eid,{})
        if s.get('distance_m') and s.get('seconds'):
            if s.get('kind')=='working' and s['distance_m']>=1000:
                pace=s['seconds']/s['distance_m']*1000
                if pace<best.get('pace',{'value':1e9})['value']: best['pace']={'value':pace,'distance_m':s['distance_m'],'seconds':s['seconds']}
            continue
        if s.get('kind') not in ('working','failure') or not s.get('reps'): continue
        if not s.get('weight_kg'):
            if s['reps']>best.get('most_reps',{'value':0})['value']: best['most_reps']={'value':s['reps'],'reps':s['reps']}
            continue
        fact={'weight_kg':s['weight_kg'],'reps':s['reps']}
        estimate=e1rm(s)
        for metric,value in (('estimated_max',estimate),('heaviest',s['weight_kg']),('set_volume',s['weight_kg']*s['reps'])):
            if value and value>best.get(metric,{'value':0})['value']: best[metric]={**fact,'value':round(value,2)}
    return {eid:best for eid,best in found.items() if best}


def better(metric, value, prior): return value<prior if metric=='pace' else value>prior


def session_wins(rows, limit=40, target=None):
    """A single pass through history, so an edited or deleted session changes what later ones achieved."""
    grouped={'exercise':{},'measurement':[],'athlete':[],'workout':[]}
    for r in rows:
        if r['deleted'] or r['kind'] not in grouped: continue
        if r['kind']=='exercise': grouped['exercise'][r['id']]=r['data']
        elif r['kind']=='workout':
            if r['data']['status']=='completed': grouped['workout'].append(r)
        else: grouped[r['kind']].append(r if r['kind']=='athlete' else r['data'])
    catalog=grouped['exercise']
    sex=max(grouped['athlete'],key=lambda p:p['updated'])['data'].get('sex') if grouped['athlete'] else None
    workouts=sorted(grouped['workout'],key=lambda r:(r['data']['started_at'],r['id']))
    alltime,dated,scores,out,paces={}, {}, {}, {}, []
    def standing(day):
        """The best recent rank on each lift, by the same six-month rule as the Ranks page."""
        current={}
        for eid,history in scores.items():
            live=[s for d,s in history if day-RANK_WINDOW<=d<=day]
            if live: current[eid]=max(live)
        return current
    for row in workouts:
        data=row['data'];day=day_of(data);wins=[];best=best_sets(data['sets'],catalog)
        before=standing(day)
        for eid,facts in best.items():
            name=catalog.get(eid,{}).get('name',eid);prior=alltime.get(eid,{});recent=[f for d,f in dated.get(eid,[]) if day-WINDOW<=d<day]
            record=None
            for metric in METRICS:
                if metric in facts and metric in prior and better(metric,facts[metric]['value'],prior[metric]):
                    record={'scope':'all_time','metric':metric,'previous':prior[metric],**facts[metric]};break
            if not record and recent:
                for metric in METRICS:
                    earlier=[f[metric]['value'] for f in recent if metric in f]
                    if metric in facts and earlier and better(metric,facts[metric]['value'],min(earlier) if metric=='pace' else max(earlier)):
                        record={'scope':'recent','metric':metric,'previous':min(earlier) if metric=='pace' else max(earlier),**facts[metric]};break
            if record: wins.append({'kind':'record','exercise_id':eid,'name':name,**record})
            for metric,fact in facts.items():
                if metric not in prior or better(metric,fact['value'],prior[metric]): alltime.setdefault(eid,{})[metric]=fact['value']
            dated.setdefault(eid,[]).append((day,facts))
        bodyweight=session_bodyweight(data,day,grouped['measurement'])
        for s in data['sets']:
            name=catalog.get(s['exercise_id'],{}).get('name','')
            estimate=e1rm(s,True);lift=rep_lift(name);reps=bodyweight_reps(s,bodyweight) if lift else None
            result={}
            if reps: result=rank_reps(lift,reps,bodyweight,sex)
            elif estimate and bodyweight and name.casefold() in BENCHMARKS: result=rank(name,estimate,bodyweight,sex)
            if result.get('status')=='ranked': scores.setdefault(s['exercise_id'],[]).append((day,result['score']))
        held=[s for d,s in paces if day-RANK_WINDOW<=d<=day]
        for s in data['sets']:
            if s.get('completed') and s.get('kind')=='working' and s.get('distance_m') and s.get('seconds'):
                placed=run_score({'distance_m':s['distance_m'],'seconds':s['seconds'],'incline_percent':s.get('incline_percent')},sex)
                if placed:
                    old=max(held,default=None)
                    if placed['score']>(old if old is not None else -1) and tier_of(placed['score'])!=(tier_of(old) if old is not None else None):
                        wins.append({'kind':'rank','exercise_id':s['exercise_id'],'name':'Running','tier':tier_of(placed['score']),'score':placed['score'],'previous_tier':tier_of(old) if old is not None else None})
                    held.append(placed['score']);paces.append((day,placed['score']))
        after=standing(day)
        for eid,score in after.items():
            old=before.get(eid)
            if tier_of(score)!=(tier_of(old) if old is not None else None) and score>(old if old is not None else -1):
                wins.append({'kind':'rank','exercise_id':eid,'name':catalog[eid]['name'],'tier':tier_of(score),'score':score,
                             'previous_tier':tier_of(old) if old is not None else None})
        if after:
            total,was=round(mean(after.values())),round(mean(before.values())) if before else None
            if tier_of(total)!=(tier_of(was) if was is not None else None) and (was is None or total>was):
                wins.append({'kind':'overall','tier':tier_of(total),'score':total,'previous_tier':tier_of(was) if was is not None else None})
        if wins and 'companion' in data.get('source',{}): out[row['id']]=wins
    if target is not None: return out.get(target,[])
    keep=[r['id'] for r in workouts if r['id'] in out][-limit:]
    return {identifier:out[identifier] for identifier in keep}


def describe(win):
    """One plain line for the coach to acknowledge."""
    if win['kind']=='overall': return f"Overall rank reached {win['tier']}"
    if win['kind']=='rank': return f"{win['name']} reached {win['tier']}"
    label={'estimated_max':'estimated max','heaviest':'heaviest set','set_volume':'best set','most_reps':'most reps','pace':'fastest pace'}[win['metric']]
    amount=(f"{round(win['value'])} s/km" if win['metric']=='pace' else f"{win['reps']}" if win['metric']=='most_reps' else
            f"{win['weight_kg']:g} kg × {win['reps']}" if win['metric']!='estimated_max' else f"{win['value']:g} kg")
    return f"{win['name']}: {'all-time' if win['scope']=='all_time' else 'best in 28 days,'} {label} {amount}"
