"""Lossless, previewable Strong and bodyweight imports; no maximal-load prescriptions."""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .store import encoded
from .models import validate

HEADERS = ['Workout #','Date','Workout Name','Duration (sec)','Exercise Name','Set Order',
           'Weight (kg)','Reps','RPE','Distance (meters)','Seconds','Notes','Workout Notes']


def identity(*parts):
    return uuid5(NAMESPACE_URL,encoded(list(parts))).hex


def number(value, integer=False):
    if value.strip() == '': return None
    try:
        parsed = Decimal(value)
        if not parsed.is_finite() or parsed<0: raise ValueError('Expected finite nonnegative number')
        if integer and parsed!=parsed.to_integral_value(): raise ValueError('Expected integer count')
        return int(parsed) if integer else float(round(parsed,6))
    except InvalidOperation: raise ValueError('Invalid numeric field') from None


def muscle_groups(name):
    """Editable initial catalog tags, not an inference about a user's physique."""
    lower = name.casefold()
    for tokens, muscles in [(['bench','chest','fly'],['chest','triceps']),
                            (['squat','leg press','lunge'],['quadriceps','glutes']),
                            (['deadlift'],['glutes','hamstrings','back']),
                            (['row','pull-up','lat pull'],['back','biceps']),
                            (['overhead','shoulder','lateral raise'],['shoulders']),
                            (['bicep','hammer curl'],['biceps']),
                            (['tricep','skullcrusher'],['triceps']),
                            (['leg curl'],['hamstrings']),(['calf'],['calves']),
                            (['crunch','ab wheel'],['core'])]:
        if any(t in lower for t in tokens): return muscles
    return []


def exercise(name):
    lower = name.casefold()
    equipment = next((word for word in ('dumbbell','barbell','cable','machine','treadmill') if word in lower),'')
    cardio = any(word in lower for word in ('treadmill','running','cycling','rowing machine'))
    convention = 'per_hand' if equipment=='dumbbell' else 'total' if equipment in ('barbell','cable','machine') else 'bodyweight' if 'body' in lower or 'pull-up' in lower or lower=='dip' else 'unknown'
    movement='other'
    for pattern,value in [('running','run'),('walking','walk'),('squat','squat'),('deadlift','hinge'),('lunge','lunge'),
                          ('row','row'),('pulldown','pull'),('pull up','pull'),('pull-up','pull'),('curl','curl'),
                          ('extension','extension'),('pushdown','extension'),('skullcrusher','extension'),('raise','raise'),
                          ('press','press'),('plank','core'),('crunch','core')]:
        if pattern in lower: movement=value;break
    if equipment=='treadmill': equipment='machine'
    if not equipment: equipment='bodyweight' if any(t in lower for t in ('pull up','pull-up','dip','plank','hanging')) else 'other'
    return validate('exercise',dict(name=name,equipment=equipment,movement=movement,muscles=muscle_groups(name),
                                  aliases=[],load_convention=convention,mode='cardio' if cardio else 'strength'))


def strong(raw, timezone='UTC'):
    try: ZoneInfo(timezone)
    except (ZoneInfoNotFoundError,ValueError): raise ValueError('Unknown import timezone') from None
    if len(raw)>32*1024*1024: raise ValueError('Strong export exceeds 32 MiB')
    try: text = raw.decode('utf-8-sig')
    except UnicodeDecodeError: raise ValueError('Strong CSV must be UTF-8') from None
    reader = csv.DictReader(io.StringIO(text,newline=''),delimiter=';')
    if reader.fieldnames != HEADERS: raise ValueError('Expected Strong semicolon export with its 13 original columns')
    workouts, exercises, counts, raw_rows = {}, {}, {}, []
    for index,row in enumerate(reader):
        if None in row or any(v is None for v in row.values()): raise ValueError(f'Malformed Strong row {index+2}')
        raw_rows.append(row)
        try:
            timestamp = datetime.strptime(row['Date'],'%Y-%m-%d %H:%M:%S').isoformat()
            wid = identity('strong-workout',row['Workout #'],timestamp)
            name = row['Exercise Name'].strip()
            if not name: raise ValueError('Exercise name is missing')
            eid = identity('strong-exercise',name.casefold())
            exercises[eid] = exercise(name)
            if wid not in workouts:
                workouts[wid] = dict(name=row['Workout Name'] or 'Imported workout',started_at=timestamp,timezone=timezone,
                    duration_seconds=number(row['Duration (sec)'],True) or 0,status='completed',sets=[],notes=row['Workout Notes'],
                    source={'app':'Strong','workout_number':row['Workout #'],'original_timestamp':row['Date']})
            workout = workouts[wid]
            if (timestamp, row['Workout Name'] or 'Imported workout',number(row['Duration (sec)'],True) or 0) != (
                    workout['started_at'],workout['name'],workout['duration_seconds']):
                raise ValueError('Inconsistent fields for a Strong workout')
            code = row['Set Order']
            kind = {'W':'warmup','D':'drop','F':'failure','Note':'note'}.get(code,'working' if code.isdigit() else 'other')
            occurrence = counts.get((wid,eid,code),0)
            counts[wid,eid,code] = occurrence+1
            workout['sets'].append(dict(id=identity('strong-set',wid,eid,code,occurrence),exercise_id=eid,
                kind=kind,raw_order=code,weight_kg=number(row['Weight (kg)']),reps=number(row['Reps'],True),
                rpe=number(row['RPE']),distance_m=number(row['Distance (meters)']),seconds=number(row['Seconds']),
                notes=row['Notes'],completed=kind!='note'))
        except (ValueError,TypeError) as error: raise ValueError(f'Strong row {index+2}: {error}') from error
    records = [('exercise',key,data) for key,data in exercises.items()]
    records += [('workout',key,validate('workout',data)) for key,data in workouts.items()]
    kinds = {}
    for w in workouts.values():
        for s in w['sets']: kinds[s['kind']] = kinds.get(s['kind'],0)+1
    report = {'format':'strong','rows':len(raw_rows),'workouts':len(workouts),'exercises':len(exercises),
              'set_types':kinds,'timezone':timezone,'dumbbell_weights':'per_hand','warnings':[]}
    if any(s['kind']=='other' for w in workouts.values() for s in w['sets']): report['warnings'].append('Unrecognized set codes preserved as other')
    return records, report


def bodyweight(raw, timezone='UTC'):
    """Canonical weight CSV or Strong's original semicolon Date/Weight export."""
    try: zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError,ValueError): raise ValueError('Unknown import timezone') from None
    if len(raw)>8*1024*1024: raise ValueError('Weight export exceeds 8 MiB')
    try: text = raw.decode('utf-8-sig')
    except UnicodeDecodeError: raise ValueError('Weight CSV must be UTF-8') from None
    header=next(csv.reader(io.StringIO(text),delimiter=';'),[])
    strong_unit={'Weight (kg)':'kg','Weight (lb)':'lb'}.get(header[1] if len(header)==2 else '')
    is_strong=bool(strong_unit and header[0]=='Date')
    reader = csv.DictReader(io.StringIO(text,newline=''),delimiter=';' if is_strong else ',')
    if is_strong:
        reader=({'measured_at':r['Date'],'value':r[header[1]],'unit':strong_unit,
                 'source':'strong_measurements','notes':'Original timezone absent; interpreted in '+timezone}
                for r in reader)
    elif not {'measured_at','value','unit'} <= set(reader.fieldnames or []):
        raise ValueError('Weight CSV needs measured_at,value,unit; optional notes,source')
    records = []
    seen = set()
    for row in reader:
        at = datetime.fromisoformat(row['measured_at'])
        if at.tzinfo is None: at = at.replace(tzinfo=zone)
        value = number(row['value'])
        if row['unit'] not in ('kg','lb') or not value: raise ValueError('Expected positive kg/lb weight')
        if row['unit']=='lb': value *= .45359237
        data = validate('measurement',dict(measured_at=at.isoformat(),kind='bodyweight',value=value,unit='kg',
            notes=row.get('notes',''),source=row.get('source','weight_csv')))
        key = identity('weight',data['measured_at'],round(value,6))
        if key not in seen: records.append(('measurement',key,data));seen.add(key)
    return records, {'format':'bodyweight','measurements':len(records),'timezone':timezone}


def reconcile(store, raw, format='strong', timezone='UTC', commit=False):
    if format not in ('strong','bodyweight'): raise ValueError('Unknown import format')
    digest = hashlib.sha256(raw).hexdigest()
    records, report = (strong if format=='strong' else bodyweight)(raw,timezone)
    report.update(sha256=digest,new=0,existing=0,conflicts=[],committed=False)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute('SELECT report FROM imports WHERE hash=?',(digest,)).fetchone()
        if previous: return {**json.loads(previous['report']),'already_imported':True}
        operations = []
        for kind,key,data in records:
            old = db.execute('SELECT * FROM entities WHERE kind=? AND id=?',(kind,key)).fetchone()
            if old:
                report['existing'] += 1
                # User corrections are never overwritten by another export.
                if old['deleted'] or (kind!='exercise' and encoded(data)!=old['data']):
                    report['conflicts'].append({'kind':kind,'id':key,'reason':'existing record differs; retained'})
                continue
            report['new'] += 1
            operations.append(dict(mutation_id=identity('import',digest,kind,key),kind=kind,id=key,base_revision=0,data=data))
        if commit:
            store.mutate(operations,'import:'+digest,db)
            report['committed'] = True
            db.execute('INSERT INTO imports(hash,report,raw,at,original) VALUES(?,?,?,?,?)',
                       (digest,encoded(report),raw.decode('utf-8-sig'),store.clock(),raw))
    return report
