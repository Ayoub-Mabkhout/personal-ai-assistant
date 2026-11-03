// Past sessions with corrections, per-exercise trends with records and rank, and the history import, as on Android's WorkoutHistory.
import {el,icon,iconButton,button,page,confirmDialog,toast,clock,label,pair,stat,card,num,HUE,alpha,cssColor,plural} from './core.js';
import * as store from './store.js';
import * as units from './units.js';
import {api} from './api.js';
import {tile,exerciseHue,sessionHue,setTag,crest,tierIndex,tierColor} from './art.js';
import {calendar,months} from './calendar.js';
import {chart,epochDay} from './chart.js';
import * as sprints from './sprints.js';
import * as live from './live.js';
import {nav} from './nav.js';

const WEEKDAY={weekday:'short'};
const dateOf=iso=>new Date(iso+'T12:00:00Z');
/** Working-set load × reps. Warm-ups don't count; dumbbell loads are per hand, as logged. */
export function volume(w){let v=0;for(const x of w.sets||[]){if(x.kind==='warmup'||x.kind==='note'||x.completed===false)continue;v+=(x.weight_kg||0)*(x.reps||0)}return v}
const metres=w=>(w.sets||[]).reduce((m,x)=>m+(x.distance_m||0),0);
const hardSets=w=>(w.sets||[]).filter(x=>x.kind!=='warmup').length;
/** Time and load, or time and distance for a session with no lifting. */
function result(w){const load=volume(w),m=metres(w);return Math.round((w.duration_seconds||0)/60)+' min'+(load>0?' · '+units.total(load):m>0?' · '+units.distance(m):'')}
export function line(x){
  if(x.distance_m!=null)return units.distance(x.distance_m,x.exercise_id)+' · '+clock(x.seconds);
  return (x.weight_kg!=null?units.load(x.weight_kg,x.exercise_id)+' × ':'')+(x.reps??0)+(x.rir!=null?' · '+num(x.rir)+' RIR':'');
}
export function sessionStats(w){
  const load=volume(w),m=metres(w),hard=hardSets(w);
  return el('div',{class:'stats'},stat(clock(w.duration_seconds||0),'time'),stat(load>0?units.total(load):m>0?units.distance(m):'–',load>0?'lifted':m>0?'distance':'lifted'),stat(String(hard),hard===1?'hard set':'hard sets'));
}

const autoBriefs=()=>!!store.athlete().auto_coach_briefs;
export function briefState(status){return {writing:'Your coach is writing…',waiting:'Queued for when your coach is back.',failed:"Your coach couldn't write this.",unavailable:'Coach offline.'}[status]||'Your coach will write this soon.'}
/** One workout's brief, for the end screen and History; null when a session never had one. */
export function workoutBrief(id,history){
  const b=(store.overview().workout_briefs||{})[id];if(!b&&history)return null;
  const ready=b?.state==='ready',text=ready?b.text:b?briefState(b.state):autoBriefs()?"Your coach gets this when you're back online.":'Automatic briefs are off.';
  const box=el('div',{class:'brief'+(ready?' ready':''),attrs:{role:'status'}},icon('sparkle'),el('p',{text}));
  if(!ready&&!b&&!autoBriefs()){box.classList.add('tappable');box.onclick=()=>nav.profile()}
  return box;
}
function winValue(x){switch(x.metric){case 'pace':return units.pace(x.value);case 'estimated_max':return units.load(x.value,x.exercise_id)+' max';case 'most_reps':return x.reps+' reps';default:return units.load(x.weight_kg,x.exercise_id)+' × '+x.reps}}
/** What a session achieved; null when it set nothing new. */
export function workoutWins(id){
  const list=(store.overview().workout_wins||{})[id];if(!list?.length)return null;
  return el('div',{class:'card wins'},...list.map(x=>{const record=x.kind==='record',overall=x.kind==='overall',t=tierIndex(x.tier),tint=record?'var(--amber)':tierColor(t);
    const lead=record?tile(x.exercise_id,40):crest(t,false,40);
    const kind=el('small',{text:record?(x.scope==='all_time'?'New record':'Best in 28 days'):x.previous_tier==null?'Ranked':'Rank up'});kind.style.color=tint;
    const value=el('strong',{class:'win-value',text:record?winValue(x):x.tier});if(!record)value.style.color=tint;
    return el('div',{class:'win'},lead,el('div',{class:'grow'},kind,el('strong',{text:overall?'Overall':x.name})),value)}));
}

function readHistory(){
  const byMonth=new Map(),counts=new Map();
  for(const r of store.workouts()){const st=r.data.status;if(['active','paused','draft'].includes(st))continue;const day=store.day(r.data);if(!day)continue;const m=day.slice(0,7);
    if(!byMonth.has(m))byMonth.set(m,[]);byMonth.get(m).push(r);if(st==='completed')counts.set(m,(counts.get(m)||0)+1)}
  return {byMonth,counts};
}
const monthAdd=(m,n)=>{const [y,mo]=m.split('-').map(Number),d=new Date(Date.UTC(y,mo-1+n,1));return d.toISOString().slice(0,7)};

/** One month at a time: a bar for every month, the calendar in session colours, then a dated card per session. */
export function open(view='workouts'){
  const p=page('History',{actions:[iconButton('download','Import history',imports,'',HUE.teal)]});
  const tabs=el('div',{class:'segmented',attrs:{role:'tablist'}});const body=el('div');
  const tab=(name,key)=>{const b=el('button',{type:'button',class:'seg'+(view===key?' on':''),text:name,attrs:{role:'tab','aria-selected':String(view===key)}});b.onclick=()=>{view=key;tabs.querySelectorAll('.seg').forEach(x=>{x.classList.toggle('on',x===b);x.setAttribute('aria-selected',String(x===b))});paint()};return b};
  tabs.append(tab('Workouts','workouts'),tab('Sprints','sprints'));p.body.append(tabs,body);
  let at=null;
  function paint(){body.replaceChildren();if(view==='sprints'){body.append(nav.sprintList());return}workoutsView()}
  function workoutsView(){
    const {byMonth,counts}=readHistory();
    if(!byMonth.size){body.append(el('p',{class:'empty',text:'No sessions yet.'}));return}
    const first=[...byMonth.keys()].sort()[0],now=store.today().slice(0,7),all=[];for(let m=first;m<=now;m=monthAdd(m,1))all.push(m);
    if(!at||!all.includes(at))at=[...byMonth.keys()].sort().pop();
    const turn=way=>{const i=all.indexOf(at)+way;if(i>=0&&i<all.length){at=all[i];paint()}};
    const list=byMonth.get(at)||[];let done=0,load=0,secs=0;const days=new Map();
    for(const r of list){const d=r.data,day=store.day(d),finished=d.status==='completed';if(finished){done++;load+=volume(d);secs+=d.duration_seconds||0}
      const h=finished?sessionHue(d):null,old=days.get(day);days.set(day,!old||!old.length?(h?[h]:[]):h?[old[0],h]:old)}
    const [y,mo]=at.split('-').map(Number);
    const title=new Date(Date.UTC(y,mo-1,1)).toLocaleDateString(undefined,{month:'long',year:'numeric',timeZone:'UTC'});
    const bands=sprints.bands();
    const first_=at+'-01',last_=at+'-31',key=el('div',{class:'cal-key'});
    for(const r of sprints.inOrder()){const x=r.data;if(x.start>last_||(x.end||x.start)<first_)continue;const dot=el('span',{class:'key-dot'});dot.style.background=cssColor(sprints.hue(r.id));
      const k=el('button',{type:'button',class:'key-item'},dot,el('span',{text:x.name}),el('small',{text:sprints.span(x)}));k.onclick=()=>nav.sprint(r.id);key.append(k)}
    body.append(months(all,counts,at,m=>{at=m;paint()}),
      el('div',{class:'month-head'},el('h3',{class:'month-title',text:title}),iconButton('back','Earlier month',()=>turn(-1)),iconButton('arrow','Later month',()=>turn(1))),
      el('div',{class:'stats'},stat(String(done),done===1?'workout':'workouts'),stat(load>0?units.total(load):'–','lifted'),stat(secs>=3600?Math.round(secs/3600)+' h':Math.round(secs/60)+' min','training')),
      el('div',{class:'card cal-card'},calendar({year:y,month:mo-1,days,bands,today:store.today(),onSwipe:turn,onTap:day=>{const hit=list.find(r=>store.day(r.data)===day);if(hit)session(hit.id,paint)}}),key.childNodes.length?key:null),
      el('div',{class:'sessions'},...list.map(r=>sessionCard(r,paint))));
  }
  paint();
}
/** A session is a date block in its colour, its name and what it came to, and the movements it held. */
function sessionCard(r,after){
  const d=r.data,day=store.day(d),finished=d.status==='completed',h=finished?sessionHue(d):'var(--muted)';
  const date=el('span',{class:'date-block'},el('strong',{text:String(+day.slice(8))}),el('small',{text:dateOf(day).toLocaleDateString(undefined,{...WEEKDAY,timeZone:'UTC'})}));
  date.style.color=cssColor(h);date.style.background=alpha(h,.16);
  const moves=[...new Set((d.sets||[]).map(s=>s.exercise_id))].slice(0,3);
  const c=el('button',{type:'button',class:'session-card'},date,el('span',{class:'grow'},el('strong',{text:d.name}),el('small',{text:finished?result(d):'Rest day'})),el('span',{class:'mini-tiles'},...moves.map(m=>tile(m,30))));
  c.onclick=()=>session(r.id,after);return c;
}

/** The session as it happened: its numbers, wins, the coach's brief, then each exercise. Tap a set to correct it. */
export function session(id,after){
  const found=store.data('workout',id);if(!found)return;
  const p=page(found.name,{actions:[iconButton('pencil','Edit workout',()=>edit(id,null)),
    iconButton('trash','Delete workout',async()=>{if(await confirmDialog('Delete this workout?','It leaves your history, records and ranks.','Delete','Keep',true)){store.deleteEntity('workout',id);p.close();nav.refresh()}},'',HUE.red)],onclose:()=>after?.()});
  const unsubscribe=store.onChange(()=>{if(!p.closed)paint()});const close=p.root.addEventListener.bind(p.root);void close;
  function edit(wid,focus){const original=store.data('workout',wid);if(!original)return;const ed=live.open(live.editDraft(wid,original),{afterSave:()=>{const s=store.data('workout',wid);if(s)p.heading.textContent=s.name;paint();after?.()}});if(focus)requestAnimationFrame(()=>ed.focus(focus))}
  function paint(){
    const d=store.data('workout',id);if(!d){unsubscribe();return}p.body.replaceChildren();const day=store.day(d),finished=d.status==='completed',h=finished?sessionHue(d):'var(--muted)';
    const when=el('p',{class:'session-date',text:dateOf(day).toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'UTC'})});when.style.color=cssColor(h);p.body.append(when);
    if(finished)p.body.append(sessionStats(d));if(d.skip_reason)p.body.append(el('p',{class:'hint',text:d.skip_reason}));
    const won=workoutWins(id);if(won)p.body.append(won);const brief=workoutBrief(id,true);if(brief)p.body.append(brief);
    const groups=new Map();for(const s of d.sets||[]){if(!groups.has(s.exercise_id))groups.set(s.exercise_id,[]);groups.get(s.exercise_id).push(s)}
    for(const [eid,sets] of groups){let n=0;const head=el('button',{type:'button',class:'ex-open'},tile(eid,36),el('strong',{text:store.exerciseName(eid)}));head.querySelector('strong').style.color=exerciseHue(store.data('exercise',eid));head.onclick=()=>nav.exercise(eid);
      p.body.append(el('div',{class:'card'},head,...sets.map(x=>{const kind=['note','other'].includes(x.kind)?'working':x.kind;if(kind==='working')n++;
        const row=el('button',{type:'button',class:'set-line',attrs:{'aria-label':'Edit this workout'}},setTag(kind,n),el('span',{text:line(x)}));row.onclick=()=>edit(id,eid);return row})))}
    if(d.notes)p.body.append(el('p',{class:'hint',text:d.notes}));for(const ch of d.session_changes||[])p.body.append(el('p',{class:'hint small',text:ch.reason||ch.note||''}));
  }
  paint();
}

/** Trend with the break left visible, recent form apart from all-time bests, and the percentile if this lift has a rank. */
export function exercise(id){
  const o=store.overview(),run=store.cardio(id),info=store.data('exercise',id),h=exerciseHue(info);
  const p=page(store.exerciseName(id));
  const r=(o.lift_ranks||[]).find(x=>x.exercise_id===id&&x.status==='ranked');
  if(r){const t=tierIndex(r.tier),name=el('strong',{class:'rank-name',text:r.tier});name.style.color=tierColor(t);
    p.body.append(el('div',{class:'card rank-card'},el('div',{class:'rank-head'},crest(t,false,46),name),
      r.percentile!=null?el('p',{class:'percentile',text:'Stronger than about '+r.percentile+'% of lifters'}):null,
      el('p',{class:'hint',text:"Among Strength Level's logged lifters, by your sex and bodyweight. Not the general population."}),
      r.next_tier?el('p',{class:'hint',text:nextStep(r)}):null))}
  const points=[],volumes=[],recent=[];let top=0;
  for(const row of [...store.workouts()].reverse()){const d=row.data;if(d.status!=='completed')continue;let best=0,sum=0,bestSet=null;
    for(const x of d.sets||[]){if(x.exercise_id!==id||x.completed===false)continue;if(run&&x.kind!=='working')continue;if(x.kind!=='warmup'&&x.kind!=='note')sum+=(x.weight_kg||0)*(x.reps||0);
      const v=x.distance_m!=null&&x.seconds>0?x.distance_m/x.seconds*3.6:store.e1rm(x);if(v>best){best=v;bestSet=x}}
    const day=store.day(d);if(best>0&&day){points.push([epochDay(day),run?units.speedValue(best):units.loadValue(best)]);if(sum>0)volumes.push([epochDay(day),units.loadValue(sum)]);top=Math.max(top,best);recent.push([day,bestSet])}}
  const unit=run?units.speedLabel():units.loadLabel();
  const trend=card(el('h3',{class:'card-title',text:run?'Speed':'Estimated max'}));
  if(points.length<2)trend.append(el('p',{class:'hint',text:'Log this a couple more times to see a trend.'}));
  else{const c=chart({height:200,gap:45,reference:run?units.speedValue(top):units.loadValue(top),format:v=>num(v)+' '+unit,label:(run?'Speed':'Estimated max')+' over time'});c.line(points,h,2,run?'Speed':'Estimated');trend.append(c.framed())}
  p.body.append(trend);
  if(volumes.length>1){const c=chart({height:170,gap:45,format:v=>Math.round(v).toLocaleString(),label:'Volume per session'});c.line(volumes,'var(--aurora-3)',2,'Volume');p.body.append(card(el('h3',{class:'card-title',text:'Volume per session'}),c.framed()))}
  const rec=(o.exercise_records||[]).find(x=>x.exercise_id===id);
  if(rec){const block=(title,x)=>[el('p',{class:'label',text:title}),...recordRows(x,id)];p.body.append(card(el('h3',{class:'card-title',text:'Records'}),...block('Last 28 days',rec.recent),...block('All-time',rec.historical)))}
  if(recent.length){p.body.append(label('Recent sessions'));for(const [day,set] of recent.slice(-8).reverse())p.body.append(pair(dateOf(day).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}),line(set)))}
}
function recordRows(x,id){
  if(!x)return [el('p',{class:'hint',text:'Nothing yet'})];const out=[];
  if(x.best_load)out.push(pair('Heaviest',units.load(x.best_load.weight_kg,id)+' × '+x.best_load.reps));
  if(x.best_reps)out.push(pair('Most reps',(x.best_reps.weight_kg?units.load(x.best_reps.weight_kg,id)+' × ':'')+x.best_reps.reps));
  if(x.best_volume)out.push(pair('Best set',units.load(x.best_volume.weight_kg,id)+' × '+x.best_volume.reps));
  return out.length?out:[el('p',{class:'hint',text:'Nothing yet'})];
}
/** What the next division takes: a max for barbell lifts, bodyweight reps for pull-ups and push-ups. */
export function nextStep(r){return r.estimated_reps!=null?Math.round(r.estimated_reps)+' reps at bodyweight · '+Math.ceil(r.next_reps)+' for '+r.next_tier:'Estimated max '+units.load(r.estimated_1rm_kg)+' · '+units.load(r.next_e1rm_kg)+' for '+r.next_tier}

/** Preview first; nothing is added until the owner confirms the counts. Imports are idempotent on the server. */
function imports(){
  const p=page('Import history');const file=el('input',{type:'file',accept:'.csv,text/csv',class:'visually-hidden',attrs:{'aria-label':'Choose a CSV export'}});
  const kind=el('select',{class:'field',attrs:{'aria-label':'Format'}},el('option',{value:'strong',text:'Strong workouts (CSV)'}),el('option',{value:'weight',text:'Weight history (CSV)'}));
  const out=el('div');
  p.body.append(el('p',{class:'hint',text:'Choose an export. You see what it adds before anything changes.'}),kind,button('Choose file','btn primary wide',()=>file.click()),file,out);
  file.onchange=async()=>{const f=file.files[0];if(!f)return;const zone=Intl.DateTimeFormat().resolvedOptions().timeZone;out.replaceChildren(el('p',{class:'hint',text:'Reading…'}));
    try{const body=await f.arrayBuffer(),path=`imports/${kind.value}?timezone=${encodeURIComponent(zone)}`;const preview=await api(path,{method:'POST',body,raw:true,type:'text/csv'});
      out.replaceChildren(card(el('h3',{class:'card-title',text:'This import adds'}),...Object.entries(preview.counts||preview.summary||{}).map(([k,v])=>pair(k.replace(/_/g,' '),String(v)))),
        button('Import','btn primary wide',async()=>{try{await api(path+'&commit=true',{method:'POST',body,raw:true,type:'text/csv'});toast('Imported');await store.sync();p.close();nav.refresh()}catch(e){toast(e.message||"Couldn't import")}}))}
    catch(e){out.replaceChildren(el('p',{class:'hint warn',text:e.message==='offline'?'Connect to import.':(e.message||"Couldn't read that file.")}))}};
}
