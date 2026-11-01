"""Cyclic, finite training plans independent of weekdays and attendance schedules."""
import calendar
from datetime import date,datetime


def add_months(day,months):
    index=day.year*12+day.month-1+months
    year,month=divmod(index,12);month+=1
    return date(year,month,min(day.day,calendar.monthrange(year,month)[1]))


def cycle_progress(sprint,workouts,today=None):
    today=today or date.today()
    data=sprint['data'];sid=sprint['id'];cycle=data.get('cycle') or []
    completed=sorted([w for w in workouts if w['data'].get('sprint_id')==sid and w['data']['status']=='completed'],
                     key=lambda w:(w['data']['started_at'],w['id']))
    target=data.get('target_sessions') or len(cycle) or len(data.get('scheduled',[])) or 1
    count=len(completed)
    next_template=cycle[count%len(cycle)] if cycle and count<target else None
    return {'sprint_id':sid,'name':data['name'],'phase':data['phase'],'status':data['status'],
            'start':data['start'],'deadline':data['end'],'target_sessions':target,'completed_sessions':count,
            'remaining_sessions':max(0,target-count),'progress':min(1,count/target),'cycle':cycle,
            'position':count%len(cycle) if cycle else None,'next_template_id':next_template,
            'deadline_passed':bool(data['end']<today.isoformat()),
            'can_extend':bool(count<target and data['status'] not in ('cancelled','completed')),
            'target_reached':count>=target}


def next_workout(entities,today=None):
    today=today or date.today()
    workouts=[r for r in entities if r['kind']=='workout' and not r['deleted']]
    sprints=[r for r in entities if r['kind']=='sprint' and not r['deleted'] and r['data']['status'] in ('active','planned')]
    sprints.sort(key=lambda s:(s['data']['status']!='active',s['data']['start'],s['id']))
    for sprint in sprints:
        progress=cycle_progress(sprint,workouts,today)
        if progress['next_template_id']:
            return {'template_id':progress['next_template_id'],'position':progress['position'],
                    'sprint_id':sprint['id'],'sequence_number':progress['completed_sessions']+1,
                    'date':None,
                    'target_sessions':progress['target_sessions'],'deadline':progress['deadline'],
                    'deadline_passed':progress['deadline_passed']}
    return None


def extend(store,identifier,end,base_revision,mutation_id):
    from .models import validate
    from ..relay.store import Conflict,Missing
    from .store import encoded
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT * FROM mutations WHERE id=?',(mutation_id,)).fetchone()
        if old:
            import json
            request=json.loads(old['request'])
            if request['kind']=='sprint' and request['id']==identifier and request['base_revision']==base_revision and request['data']['end']==end.isoformat():
                return json.loads(old['result'])
            raise Conflict('Extension mutation already used')
        row=db.execute("SELECT * FROM entities WHERE kind='sprint' AND id=? AND deleted=0",(identifier,)).fetchone()
        if not row: raise Missing('Sprint not found')
        import json
        data=json.loads(row['data'])
        if end<=date.fromisoformat(data['end']): raise ValueError('Extension must move the deadline later')
        data.setdefault('extensions',[]).append({'from':data['end'],'to':end.isoformat(),'at':datetime.now().astimezone().isoformat()})
        data['end']=end.isoformat()
        return store.mutate([{'mutation_id':mutation_id,'kind':'sprint','id':identifier,'base_revision':base_revision,
                              'data':validate('sprint',data)}],'owner_extension',db)[0]
