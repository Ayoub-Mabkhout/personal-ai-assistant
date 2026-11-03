// Sprints, templates, the exercise picker and one-day changes, as on Android's WorkoutPlan. The coach plans; manual setup stays available.
import {el,icon,iconButton,button,page,confirmDialog,promptDialog,choiceDialog,toast,uid,label,pair,stat,card,row,HUE,cssColor,alpha,haptic,num,clock,plural} from './core.js';
import * as store from './store.js';
import * as units from './units.js';
import {api} from './api.js';
import {tile,exerciseHue,group,setTag} from './art.js';
import * as sprints from './sprints.js';
import {planSets,iso} from './live.js';
import {nav} from './nav.js';
import * as settings from './settings.js';

const PHASES=['Strength','Hypertrophy','Fat loss','Endurance','Maintenance','Deload'];
const chapterOf=id=>(store.overview().sprint_history||[]).find(x=>x.id===id);
const evidence=id=>(store.overview().sprints||[]).find(x=>x.id===id);
export function summary(t){const ex=t?.exercises||[];if(!ex.length)return '';const s=ex.reduce((n,p)=>n+(p.estimated_seconds!=null?p.estimated_seconds:(p.sets||1)*(45+(p.rest_seconds??120))+60),0);return plural(ex.length,'exercise')+' · about '+Math.round(s/60)+' min'}
const templateRows=()=>store.rows('template').sort((a,b)=>a.data.name.localeCompare(b.data.name));
const progressBar=f=>{const t=el('div',{class:'progress',attrs:{role:'progressbar','aria-valuemin':'0','aria-valuemax':'100','aria-valuenow':String(Math.round(f*100))}},el('span'));t.firstChild.style.transform=`scaleX(${Math.max(0,Math.min(1,f))})`;return t};
export {progressBar};
export function change(kind,reason,date){return {id:uid(),at:iso(Date.now(),Intl.DateTimeFormat().resolvedOptions().timeZone),kind,reason,...(date?{original_date:date}:{})}}

function stats(h,d){const done=h?.completed||0,target=d.target_sessions||0,load=h?.volume_kg_reps||0,records=h?.records||0,ranks=h?.rank_ups||0;
  return el('div',{class:'stats four'},stat(done+(target?'/'+target:''),'workouts'),stat(load>0?units.total(load):'–','lifted'),stat(String(records),records===1?'record':'records'),stat(String(ranks),ranks===1?'rank up':'rank ups'))}
/** The coach's review of a sprint, or where it stands; null before the sprint ends. */
function review(h){if(!h?.ended)return null;const b=h.brief,state=b?.state||'',ready=state==='ready';
  return el('div',{class:'brief'+(ready?' ready':'')},icon('sparkle'),el('p',{text:ready?b.text:state==='writing'?"Your coach is writing this sprint's review…":state==='failed'?"Your coach couldn't write this review.":'Queued for when your coach is back.'}))}

/** Past, current and planned sprints as chapters, newest first, each in the colour it has on the calendar. */
export function sprintList(){
  const box=el('div',{class:'stack'}),now=store.sprint();
  if(now)box.append(sprintCard(now));
  box.append(button(now?'Plan the next sprint with your coach':'Set up a sprint with your coach','btn primary wide',()=>nav.coach({purpose:'plan_sprint'},null,'Plan my next sprint from my progress and goals, and name it.')),
    button('Set up manually','btn ghost wide',()=>edit(null)));
  const past=sprints.inOrder().reverse().filter(r=>r.id!==now?.id);if(past.length)box.append(label('Chapters'));
  for(const r of past)box.append(chapter(r));
  return box;
}
function chapter(r){
  const d=r.data,h=chapterOf(r.id),dot=el('span',{class:'key-dot'});dot.style.background=cssColor(sprints.hue(r.id));
  const c=el('button',{type:'button',class:'card chapter'},el('div',{class:'chapter-head'},dot,el('strong',{text:d.name})),el('small',{text:sprints.span(d)+' · '+d.phase}),stats(h,d),review(h));
  c.onclick=()=>sprint(r.id);return c;
}
function sprintCard(r){
  const id=r.id,d=r.data,ev=evidence(id),done=(d.cycle||[]).length?store.sprintCompleted(id):ev?.completed||0,target=d.target_sessions||0;
  const c=card(el('h3',{class:'card-title big',text:d.name}),el('p',{class:'hint',text:d.phase+' · until '+sprints.fmt(d.end,false)}));
  if(target){c.append(el('p',{class:'strong-line',text:done+' of '+target+' workouts'}),progressBar(done/target))}
  if((d.cycle||[]).length){c.append(label('Workout cycle'));d.cycle.forEach((tid,i)=>{const t=store.data('template',tid);if(t)c.append(row((i+1)+' · '+t.name,summary(t),()=>template(tid)))})}
  if(target&&done<target&&sprints.daysUntil(d.end)<=14){c.append(el('p',{class:'hint',text:"There's still "+plural(target-done,'workout')+' to go. Extending just gives you more time.'}),button('Extend by a month','btn quiet',()=>extend(r)))}
  c.append(el('div',{class:'row2'},button('Details','btn ghost',()=>sprint(id)),button('Edit','btn ghost',()=>edit(id))));
  return c;
}
async function extend(r){const end=new Date(Date.parse(r.data.end+'T00:00:00Z'));end.setUTCMonth(end.getUTCMonth()+1);
  try{await api(`sprints/${encodeURIComponent(r.id)}/extend`,{body:{end:end.toISOString().slice(0,10),base_revision:store.revision('sprint',r.id),mutation_id:uid()}});await store.sync();toast('Extended to '+sprints.fmt(end.toISOString().slice(0,10)));nav.refresh()}
  catch(e){toast(e.message==='offline'?'Connect to extend the sprint.':e.message||"Couldn't extend")}}

/** Evidence, the coach's reading and the proposal stay separate; applying a next sprint happens in Coach, with approval. */
export function sprint(id){
  const p=page(store.data('sprint',id)?.name||'Sprint');
  function paint(){const d=store.data('sprint',id);if(!d)return;p.body.replaceChildren();const h=chapterOf(id);
    p.body.append(el('p',{class:'hint',text:d.phase+' · '+sprints.span(d)}),stats(h,d));const rv=review(h);if(rv)p.body.append(rv);
    if(d.goals?.length)p.body.append(card(el('h3',{class:'card-title',text:'Goals'}),...d.goals.map(g=>el('p',{class:'bullet',text:g}))));
    if(d.success_criteria?.length)p.body.append(card(el('h3',{class:'card-title',text:'Success criteria'}),...d.success_criteria.map(g=>el('p',{class:'bullet',text:g}))));
    if(d.cycle?.length)p.body.append(card(el('h3',{class:'card-title',text:'Workout cycle'}),...d.cycle.map((t,i)=>pair(String(i+1),store.data('template',t)?.name||'Session'))));
    if(settings.scheduledSprints()||store.overview().scheduled_sprints)p.body.append(slots(id,d));
    if(d.retrospective)p.body.append(card(el('h3',{class:'card-title',text:'Review'}),el('p',{text:d.retrospective})));
    p.body.append(button('Ask coach to review this sprint','btn quiet wide',()=>nav.coach({purpose:'sprint_review',sprint_id:id},null,'Review '+d.name+': evidence, your reading, and a proposed next sprint for my approval.')),
      button('Edit sprint','btn quiet wide',()=>edit(id)),
      d.status==='active'?button('Mark complete','btn ghost wide',()=>{store.putEntity('sprint',id,{...d,status:'completed'});p.close();nav.refresh()}):null)}
  paint();
}

/** Dated time slots for the scheduled-workout mode: each has a start time with its offset and the session it holds. */
function slots(id,d){
  const list=(d.scheduled||[]).filter(x=>x.starts_at).sort((a,b)=>String(a.starts_at).localeCompare(String(b.starts_at)));
  const c=card(el('div',{class:'card-head'},el('h3',{class:'card-title',text:'Scheduled sessions'}),iconButton('plus','Add a time slot',()=>slotEditor(id,null),'',HUE.teal)));
  if(!list.length)c.append(el('p',{class:'hint',text:'Add times to get a reminder before each session.'}));
  for(const s of list){const at=new Date(s.starts_at),t=store.data('template',s.template_id);
    c.append(row(at.toLocaleDateString(undefined,{weekday:'short',day:'numeric',month:'short'})+' · '+at.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}),t?.name||'Session',()=>slotEditor(id,s.id),el('span',{class:'slot-dot',style:{background:cssColor(HUE.teal)}})))}
  return c;
}
async function slotEditor(id,slotId){
  const d=store.data('sprint',id);if(!d)return;const old=(d.scheduled||[]).find(s=>s.id===slotId);
  const cycle=[...new Set([...(d.cycle||[]),...templateRows().map(r=>r.id)])].filter(t=>store.data('template',t));const names=cycle.map(t=>store.data('template',t).name);
  if(old){const i=await choiceDialog('Time slot',['Change it','Delete slot']);if(i==null)return;if(i===1){store.putEntity('sprint',id,{...d,scheduled:(d.scheduled||[]).filter(s=>s.id!==slotId)});nav.refresh();return}}
  const local=old?new Date(old.starts_at):null,pad=n=>String(n).padStart(2,'0');
  const r=await promptDialog(old?'Edit time slot':'New time slot',[
    {name:'date',label:'Date',type:'date',value:old?old.date:store.today()},
    {name:'time',label:'Start time',type:'time',value:local?pad(local.getHours())+':'+pad(local.getMinutes()):'18:00'}],old?'Save':'Add');
  if(!r||!r.date||!r.time)return;
  let template=old?.template_id||cycle[0]||null;
  if(cycle.length>1){const i=await choiceDialog('Which session?',names);if(i==null)return;template=cycle[i]}
  if(!template){toast('Add a workout to the cycle first');return}
  const [y,m,day]=r.date.split('-').map(Number),[hh,mm]=r.time.split(':').map(Number),when=new Date(y,m-1,day,hh,mm);
  if(r.date<d.start||r.date>d.end){toast('Pick a date inside the sprint');return}
  const slot={...(old||{}),id:old?.id||uid(),date:r.date,starts_at:iso(when.getTime(),Intl.DateTimeFormat().resolvedOptions().timeZone),template_id:template};
  const next=(d.scheduled||[]).filter(s=>s.id!==slot.id);next.push(slot);
  store.putEntity('sprint',id,{...d,scheduled:next});nav.refresh();
}

/** Manual setup: focus, dates and the ordered workouts that repeat until the target is reached. Four months by default. */
export function edit(id){
  const found=id?store.data('sprint',id):null,d=found?structuredClone(found):{status:'active'};
  const start=d.start||store.today(),end0=new Date(Date.parse(start+'T00:00:00Z'));end0.setUTCMonth(end0.getUTCMonth()+4);
  const p=page(id?'Edit sprint':'Set up a sprint');
  const field=(lbl,value,type='text')=>{const i=el('input',{class:'field',type,value:value??'',attrs:{'aria-label':lbl,placeholder:lbl}});return [el('label',{class:'field-label'},el('span',{text:lbl}),i),i]};
  const [nameL,name]=field('Name',d.name),[startL,startI]=field('Start',start,'date'),[endL,endI]=field('End',d.end||end0.toISOString().slice(0,10),'date'),[targetL,target]=field('Target workouts',d.target_sessions||12,'number');
  const phase=el('select',{class:'field',attrs:{'aria-label':'Focus'}},...PHASES.map(x=>el('option',{value:x,text:x,selected:x===(d.phase||PHASES[0])})));
  const goals=el('textarea',{class:'field',rows:3,placeholder:'Success criteria, one per line',value:(d.success_criteria||[]).join('\n'),attrs:{'aria-label':'Success criteria'}});
  const cycle=[...(d.cycle||[])],rows=el('div',{class:'stack'});
  const paint=()=>{rows.replaceChildren(...cycle.map((t,i)=>row((i+1)+' · '+(store.data('template',t)?.name||'Removed template'),'Tap to remove',()=>{cycle.splice(i,1);paint()})))};paint();
  p.body.append(nameL,el('label',{class:'field-label'},el('span',{text:'Focus'}),phase),el('div',{class:'row2'},startL,endL),targetL,goals,label('Workout cycle'),rows,
    button('Add a workout','btn quiet wide',async()=>{const list=templateRows();if(!list.length){toast('Create a template first');return}const i=await choiceDialog('Add to the cycle',list.map(r=>r.data.name));if(i!=null){cycle.push(list[i].id);paint()}}),
    button('Save sprint','btn primary wide',()=>{
      const title=name.value.trim(),first=startI.value,last=endI.value,goal=parseInt(target.value,10);
      if(!title||!first||!last||last<first||!(goal>0)){toast('Check the name, dates and target');return}
      Object.assign(d,{name:title,phase:phase.value,start:first,end:last,target_sessions:goal,cycle,success_criteria:goals.value.split('\n').map(x=>x.trim()).filter(Boolean)});
      store.putEntity('sprint',id||uid(),d);p.close();nav.refresh()}));
}

/** Each template is a card with its exercises drawn out, ready to start. */
export function templates(){
  const p=page('Templates',{actions:[iconButton('plus','New template',()=>template(null),'',HUE.teal)]});
  const paint=()=>{p.body.replaceChildren();const list=templateRows();if(!list.length)p.body.append(el('p',{class:'empty',text:'No templates yet.'}));
    for(const r of list){const d=r.data;p.body.append(card(el('h3',{class:'card-title',text:d.name}),el('p',{class:'hint',text:summary(d)}),
      el('div',{class:'tile-row'},...(d.exercises||[]).slice(0,5).map(x=>tile(x.exercise_id,44))),
      el('div',{class:'row2'},button('Start','btn primary',()=>{p.close();nav.begin(d.name,r.id,null,null,null)}),button('Edit','btn ghost',()=>template(r.id)))))}};
  paint();const off=store.onChange(()=>{if(p.closed)off();else paint()});
}
export function template(id){
  const found=id?store.data('template',id):null,d=found?structuredClone(found):{name:'',exercises:[]};
  const p=page(id?'Edit template':'New template');
  const name=el('input',{class:'field',value:d.name,placeholder:'Name',attrs:{'aria-label':'Template name'}}),rows=el('div',{class:'stack'});
  const paint=()=>rows.replaceChildren(...d.exercises.map((x,i)=>planRow(x,()=>prescription(d.exercises,i,paint))));paint();
  p.body.append(name,rows,button(el('span',{},icon('plus'),'Add exercise'),'btn quiet wide',()=>nav.pick(e=>{d.exercises.push({exercise_id:e,sets:1,min_reps:8,max_reps:12,rest_seconds:120});paint();prescription(d.exercises,d.exercises.length-1,paint)})),
    button('Save template','btn primary wide',()=>{const t=name.value.trim();if(!t){toast('Enter a name');name.focus();return}d.name=t;store.putEntity('template',id||uid(),d);p.close();nav.refresh()}),
    id?button('Start workout','btn quiet wide',()=>{p.close();nav.begin(d.name,id,null,null,null)}):null,
    id?button('Delete template','btn ghost danger-text wide',async()=>{if(await confirmDialog('Delete this template?','Sprints that use it skip it.','Delete','Keep',true)){store.deleteEntity('template',id);p.close();nav.refresh()}}):null);
}
/** An exercise in a template, drawn with its sets so warm-ups and hard sets read at a glance. */
function planRow(x,open){let n=0;const marks=el('span',{class:'marks'},...planSets(x).slice(0,9).map(q=>{const k=q.kind||'working';if(k==='working')n++;return setTag(k,n)}));
  const r=el('button',{type:'button',class:'plan-row'},tile(x.exercise_id,44),el('span',{class:'grow'},el('strong',{text:store.exerciseName(x.exercise_id)}),marks,x.superset?el('small',{text:'Superset '+x.superset}):null),icon('arrow','chev'));r.onclick=open;return r}
/** The exercise's sets, edited the way they are logged: tap a number to change its type, swipe or tap × to delete. */
function prescription(list,index,after){
  const x=list[index],id=x.exercise_id,run=store.cardio(id),plan=structuredClone(planSets(x));let rest=x.rest_seconds??120;
  const p=page(store.exerciseName(id),{actions:[iconButton('trash','Remove exercise',()=>{list.splice(index,1);p.onclose=null;p.close();after()},'',HUE.red)],onclose:()=>{commit(x,plan,rest);after()}});
  const rows=el('div',{class:'stack'});
  const cell=(value,lbl,mode,set)=>{const v=el('input',{class:'set-input',value:value??'',attrs:{'aria-label':lbl,inputmode:mode}});v.onfocus=()=>v.select();v.oninput=()=>{const n=v.value.trim()===''?null:Number(v.value.replace(',','.'));set(Number.isFinite(n)?n:null)};return v};
  const paint=()=>{let n=0;rows.replaceChildren(el('div',{class:'set-cols plan'+(run?' run':'')},el('span',{text:'Set'}),el('span',{text:run?units.distanceLabel(id):units.loadLabel(id)}),el('span',{text:run?'Time':'Reps'}),run?null:el('span',{text:'RIR'}),el('span')),
    ...plan.map((q,i)=>{const k=q.kind||'working';if(k==='working')n++;const tag=setTag(k,n);tag.setAttribute('role','button');tag.tabIndex=0;tag.onclick=()=>{const o=['working','warmup','drop','failure'];q.kind=o[(o.indexOf(k)+1)%4];haptic();paint()};
      const cells=run?[cell(q.distance_m!=null?units.distanceNumber(q.distance_m,id):'','Distance','decimal',v=>{if(v==null)delete q.distance_m;else q.distance_m=units.distanceIn(v,id)}),cell(q.seconds!=null?clock(q.seconds):'','Time','numeric',v=>{if(v==null)delete q.seconds;else q.seconds=v*60})]
        :[cell(q.weight_kg!=null?units.loadNumber(q.weight_kg,id):'','Weight','decimal',v=>{if(v==null)delete q.weight_kg;else q.weight_kg=units.loadIn(v,id)}),cell(q.reps,'Reps','numeric',v=>{if(v==null)delete q.reps;else q.reps=Math.round(v)}),cell(q.rir,'Reps in reserve','decimal',v=>{if(v==null)delete q.rir;else q.rir=v})];
      return el('div',{class:'set-row plan'+(run?' run':'')},tag,...cells,iconButton('x-circle','Delete set',()=>{plan.splice(i,1);paint()},'set-check'))}))};
  paint();
  const restI=el('input',{class:'field',type:'number',value:rest,attrs:{'aria-label':'Rest seconds',inputmode:'numeric'}});restI.oninput=()=>{rest=Math.max(0,parseInt(restI.value,10)||0)};
  const sup=el('input',{class:'field',value:x.superset||'',placeholder:'Superset label, such as A',attrs:{'aria-label':'Superset label'}});sup.oninput=()=>{x.superset=sup.value.trim().slice(0,40)};
  p.body.append(rows,button(el('span',{},icon('plus'),'Add set'),'btn ghost wide',()=>{const last=plan[plan.length-1];plan.push(last?{...last,kind:last.kind==='warmup'?'working':last.kind}:{kind:'working'});paint()}),
    el('label',{class:'field-label'},el('span',{text:'Rest between sets (seconds)'}),restI),el('label',{class:'field-label'},el('span',{text:'Superset'}),sup));
}
/** The plain fields follow the set plan, so summaries and older clients stay right. */
function commit(p,plan,rest){p.set_plan=plan;p.rest_seconds=rest;const hard=plan.filter(q=>q.kind!=='warmup');p.sets=Math.max(1,hard.length);const reps=hard.map(q=>q.reps).filter(r=>r>0);
  if(reps.length){p.min_reps=Math.min(...reps);p.max_reps=Math.max(...reps)}const load=hard.find(q=>q.weight_kg!=null);if(load)p.weight_kg=load.weight_kg;const first=plan[0];if(first?.distance_m>0)p.distance_m=first.distance_m}
/** After a session that differed: the template takes this session's exercises and set counts. Prescribed loads are kept. */
export async function saveStructure(id,template,used){
  if(!await confirmDialog('Update the template?',"Future sessions from this template will use today's exercises and sets. Past sessions don't change.",'Update template','Keep it'))return;
  const t=structuredClone(template);t.exercises=used.map(u=>{const old=(template.exercises||[]).find(x=>x.exercise_id===u.eid);const p=old?structuredClone(old):{exercise_id:u.eid,min_reps:8,max_reps:12,rest_seconds:u.rest??120};
    p.set_plan=u.sets.map(s=>{const q={kind:s.kind||'working'};if(s.reps!=null)q.reps=s.reps;if(s.weight!=null)q.weight_kg=s.weight;if(s.rir!=null)q.rir=s.rir;if(s.distance!=null)q.distance_m=s.distance;if(s.seconds!=null)q.seconds=Math.round(s.seconds);return q});
    p.sets=Math.max(1,p.set_plan.filter(q=>q.kind!=='warmup').length);if(u.group)p.superset=u.group.slice(0,40);else delete p.superset;return p});
  store.putEntity('template',id,t);toast('Template updated');
}
export const differs=(template,used)=>{const ex=template.exercises||[];return ex.length!==used.length||ex.some((x,i)=>x.exercise_id!==used[i].eid||planSets(x).length!==used[i].sets.length)};

/** The catalog as a picture grid: filter by movement or search, or have the coach create what's missing. */
export function pick(chosen,{title='Choose exercise'}={}){
  const p=page(title);const all=store.rows('exercise').sort((a,b)=>a.data.name.localeCompare(b.data.name,undefined,{sensitivity:'base'}));
  const search=el('input',{class:'field',type:'search',placeholder:'Search exercises',attrs:{'aria-label':'Search exercises',enterkeyhint:'search'}});
  const groups=['All','Push','Pull','Legs and hips','Core','Cardio','Other'];let filter='All';
  const chips=el('div',{class:'chips',attrs:{role:'tablist'}}),grid=el('div',{class:'pick-grid'});
  const paint=()=>{const q=search.value.trim().toLowerCase();chips.replaceChildren(...groups.map(g=>{const b=el('button',{type:'button',class:'chip'+(g===filter?' on':''),text:g,attrs:{role:'tab','aria-selected':String(g===filter)}});b.onclick=()=>{filter=g;paint()};return b}));
    const list=all.filter(r=>(filter==='All'||group(r.data)===filter||(filter==='Other'&&!groups.includes(group(r.data))))&&(!q||r.data.name.toLowerCase().includes(q)||(r.data.aliases||[]).some(a=>a.toLowerCase().includes(q))));
    grid.replaceChildren(...list.map(r=>{const b=el('button',{type:'button',class:'pick'},tile(r.data,56),el('span',{text:r.data.name}));b.onclick=()=>{p.close();chosen(r.id)};return b}));
    if(!list.length)grid.append(el('p',{class:'empty',text:'Nothing matches.'}))};
  search.oninput=paint;paint();
  p.body.append(search,chips,grid,el('div',{class:'row2'},
    button('New exercise','btn quiet',async()=>{const r=await promptDialog('New exercise',[{name:'name',label:'Exercise name',value:search.value.trim()}],'Add');if(!r?.name)return;
      const cardio=await confirmDialog('What kind?','A timed distance, such as a run, logs distance and time.','Timed distance','Sets and reps');const id=uid();store.putEntity('exercise',id,{name:r.name,mode:cardio?'cardio':'strength'});p.close();chosen(id)}),
    button(el('span',{},icon('sparkle'),'Ask coach'),'btn quiet',()=>{p.close();nav.coach({},null,'Create an exercise for '+(search.value.trim()||'…')+' with its illustration.')})));
  setTimeout(()=>search.focus({preventScroll:true}),80);
}

/** Today only: another sprint day, edited exercises, a shorter session, or rest. The sprint plan stays and the change goes to the review. */
export function changeToday(next){
  const p=page("Change today's workout"),sid=next.sprint?.id||null,date=next.date,current=next.template_id,t=store.data('template',current),name=t?.name||'Session';
  p.body.append(label('Swap with another session'));const seen=new Set();
  for(const tid of next.sprint?.data.cycle||[]){if(tid===current||seen.has(tid))continue;seen.add(tid);const x=store.data('template',tid);if(!x)continue;
    p.body.append(row(x.name,summary(x),()=>{p.close();nav.begin(x.name,tid,sid,date,change('swap_day','Swapped '+name+' for '+x.name,date),false,next.scheduled_session_id)}))}
  p.body.append(label('Or'),row('Edit exercises for today','Starts the session; change anything as you go',()=>{p.close();nav.begin(name,current,sid,date,change('edit_exercises',"Chose to edit today's exercises",date),false,next.scheduled_session_id)}),
    row('Shorter session','Keeps the first half of the exercises',()=>{p.close();nav.begin(name,current,sid,date,change('shorter','Shortened the session',date),true,next.scheduled_session_id)}),
    row('Rest today','The cycle waits for you',async()=>{const r=await promptDialog('Rest today?',[{name:'why',label:'Why, such as still sore',value:''}],'Rest');if(!r)return;const reason=r.why||'Rest day';
      store.putEntity('workout',uid(),{name,started_at:iso(Date.now(),Intl.DateTimeFormat().resolvedOptions().timeZone),timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,status:'skipped',recovery_adjusted:true,skip_reason:reason,template_id:current,...(sid?{sprint_id:sid}:{}),session_changes:[change('rest_move',reason,date)],source:{companion:{scheduled_date:date,client:'train-web',...(next.scheduled_session_id?{scheduled_session_id:next.scheduled_session_id}:{})}}});
      p.close();nav.refresh()}));
}
