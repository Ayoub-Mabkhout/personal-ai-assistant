// The live session and the past-workout editor, ported from Android's WorkoutLive. Every entry saves to the on-device draft and
// every clock is arithmetic on saved instants, so a closed tab or a dead signal loses nothing. Unticked sets are left out on finish.
import {el,icon,iconButton,button,page,confirmDialog,promptDialog,toast,haptic,clock,uid,HUE,cssColor,alpha,num} from './core.js';
import * as store from './store.js';
import * as units from './units.js';
import {tile,exerciseHue,setTag} from './art.js';
import {nav} from './nav.js';

/** An ISO instant with the offset of the workout's own time zone. */
export function iso(ms,zone){
  const p=Object.fromEntries(new Intl.DateTimeFormat('en-US',{timeZone:zone||'UTC',hourCycle:'h23',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).formatToParts(new Date(ms)).map(x=>[x.type,x.value]));
  const off=Math.round((Date.UTC(+p.year,p.month-1,+p.day,+p.hour,+p.minute,+p.second)-Math.floor(ms/1000)*1000)/60000),a=Math.abs(off);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}${off<0?'-':'+'}${String(a/60|0).padStart(2,'0')}:${String(a%60).padStart(2,'0')}`;
}
const zone=()=>Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';

export function blank(name,template,sprint,date,slot){return {workout_id:uid(),scheduled_session_id:slot||null,name,started_ms:Date.now(),timezone:zone(),template_id:template||null,sprint_id:sprint||null,scheduled_date:date||'',paused_ms:0,paused_total:0,notes:'',changes:[],exercises:[]}}
/** The sets a prescription expands to: its own set plan, or the counted sets at its target. */
export function planSets(p){
  if(p.set_plan?.length)return p.set_plan;const run=store.cardio(p.exercise_id),out=[];
  for(let i=0;i<Math.max(1,p.sets||1);i++){const q={kind:run?'warmup':'working'};
    if(run){if(p.distance_m>0)q.distance_m=p.distance_m;if(p.distance_m>0&&p.speed_kmh>0)q.seconds=Math.round(p.distance_m/(p.speed_kmh/3.6))}
    else{if(p.weight_kg!=null)q.weight_kg=p.weight_kg;if(p.min_reps>0)q.reps=p.min_reps;if(p.rir!=null)q.rir=p.rir}out.push(q)}
  return out;
}
/** One planned exercise. Prescribed loads win, then this sprint's last session; an old record is never a prefill. */
export function planned(p,sprint){
  const id=p.exercise_id,run=store.cardio(id),rest=p.rest_seconds??120;
  let earlier=[];if(sprint)for(const w of store.workouts()){const x=w.data;if(x.sprint_id!==sprint||x.status!=='completed')continue;earlier=(x.sets||[]).filter(s=>s.exercise_id===id&&s.kind==='working');if(earlier.length)break}
  const plan=planSets(p);let hard=0;
  const sets=plan.map(q=>{const kind=q.kind||'working',set={id:uid(),kind,done:false};
    if(run){if(q.distance_m>0)set.distance=q.distance_m;if(q.seconds>0)set.seconds=q.seconds}
    else{const last=!earlier.length||kind==='warmup'?null:earlier[Math.min(hard,earlier.length-1)];if(kind!=='warmup')hard++;const w=q.weight_kg==null?(last?.weight_kg||0):q.weight_kg;if(w>0)set.weight=w;if(q.reps>0)set.reps=q.reps;if(q.rir!=null)set.rir=q.rir}
    return set});
  const estimate=p.estimated_seconds!=null?p.estimated_seconds:run&&p.distance_m>0&&p.speed_kmh>0?Math.round(p.distance_m/(p.speed_kmh/3.6)):plan.length*(45+rest)+60;
  return {eid:id,rest,note:p.notes||'',group:p.superset||'',started_ms:0,ended_ms:0,planned:estimate,sets};
}
export function fromTemplate(name,template,sprint,date,slot){
  const d=blank(name,template,sprint,date,slot),t=template?store.data('template',template):null;
  for(const p of t?.exercises||[])d.exercises.push(planned(p,sprint));if(d.exercises.length)d.exercises[0].started_ms=d.started_ms;return d;
}

const FIELDS=[['weight','weight_kg'],['reps','reps'],['rir','rir'],['distance','distance_m'],['seconds','seconds']];
/** A past workout opened for correction; untouched source fields survive the save. */
export function editDraft(id,original){
  const zoneName=original.timezone||'UTC',when=Date.parse(original.started_at)||Date.now();
  const extras=original.source?.companion?.exercises||{};const groups=new Map();
  for(const s of original.sets||[]){let ex=groups.get(s.exercise_id);
    if(!ex){const saved=extras[s.exercise_id];ex={eid:s.exercise_id,rest:saved?.rest??120,note:saved?.note||'',group:saved?.group||'',started_ms:0,ended_ms:0,planned:0,sets:[]};groups.set(s.exercise_id,ex)}
    const row={id:s.id,kind:s.kind||'working',done:s.completed!==false};for(const [a,b] of FIELDS)if(s[b]!=null)row[a]=s[b];ex.sets.push(row)}
  const exercises=[...groups.values()];
  return {workout_id:id,edit_original:structuredClone(original),name:original.name,started_ms:when,timezone:zoneName,paused_ms:when+(original.duration_seconds||0)*1000,paused_total:0,
    template_id:original.template_id??null,sprint_id:original.sprint_id??null,notes:original.notes||'',changes:structuredClone(original.session_changes||[]),
    scheduled_date:original.source?.companion?.scheduled_date||'',exercises,edit_order:exercises.flatMap(e=>e.sets.map(s=>s.id))};
}
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function savedEdit(d){
  const original=d.edit_original,out=structuredClone(original),old=new Map((original.sets||[]).map(s=>[s.id,s])),shown=new Set((original.sets||[]).map(s=>s.exercise_id));
  const companion={...(out.source?.companion||{})},extras={...(companion.exercises||{})},flat=[],order=[],changed=new Map(),kept=new Set();
  for(const ex of d.exercises){kept.add(ex.eid);
    for(const row of ex.sets){const s=old.has(row.id)?structuredClone(old.get(row.id)):{};Object.assign(s,{id:row.id,exercise_id:ex.eid,kind:row.kind||'working',completed:!!row.done});
      for(const [a,b] of FIELDS){if(row[a]!=null)s[b]=row[a];else delete s[b]}flat.push(s);order.push(row.id);changed.set(row.id,s)}
    extras[ex.eid]={...(extras[ex.eid]||{}),note:ex.note||'',rest:ex.rest??120,group:ex.group||''}}
  // An imported superset keeps its interleaved order when only values changed.
  const sets=same(order,d.edit_order)?(original.sets||[]).map(s=>changed.get(s.id)):flat;
  for(const e of shown)if(!kept.has(e))delete extras[e];
  companion.exercises=extras;out.source={...(out.source||{}),companion};
  out.blocks=(original.blocks||[]).filter(b=>!b.exercise_id||kept.has(b.exercise_id)||!shown.has(b.exercise_id));
  return {...out,name:d.name,notes:d.notes,sets,session_changes:d.changes};
}

const GROUP=[HUE.teal,HUE.pink,HUE.amber,HUE.blue];
let current=null;
export const active=()=>current;

/** Opens the live session (or a past workout's editor) as a full-screen page. */
export function open(d,{afterSave}={}){
  const historical=!!d.edit_original,baseline=JSON.stringify(d);let actions=-1,reordering=false,closed=false,timer=0,saveTimer=0;
  const persist=()=>{if(historical)store.saveEdit(d);else store.saveDraft(d)};
  const changed=()=>{clearTimeout(saveTimer);saveTimer=setTimeout(persist,300)};
  const save=()=>{clearTimeout(saveTimer);persist()};
  const note=(kind,reason)=>d.changes.push({id:uid(),at:iso(Date.now(),d.timezone),kind,reason});
  const elapsed=()=>Math.max(0,(d.paused_ms>0?d.paused_ms:Date.now())-d.started_ms-d.paused_total);
  const ex=()=>d.exercises;

  const title=el('button',{type:'button',class:'live-title',text:d.name,attrs:{'aria-label':'Rename workout'}});title.onclick=rename;
  const pauseBtn=button('Pause','btn quiet',pause);
  const finishBtn=button(historical?'Save':'Finish','btn primary small',historical?saveEdits:finish);
  const p=page(d.name,{cls:'live',actions:historical?[finishBtn]:[pauseBtn,finishBtn],onclose:()=>{closed=true;clearInterval(timer);if(current===api)current=null;if(!historical)save();nav.refresh()}});
  p.heading.replaceWith(title);
  p.bar.querySelector('.icon-btn').replaceWith(iconButton(historical?'back':'down',historical?'Close editor':'Minimise workout',close));
  const clockEl=el('strong',{class:'live-clock',text:'0:00'}),pace=el('span',{class:'live-pace'}),bar=el('div',{class:'live-bar',attrs:{'aria-hidden':'true'}});
  const list=el('div',{class:'live-list'});
  p.body.append(el('div',{class:'live-head'},clockEl,pace),bar,list);
  const api={d,focus,adopt,discard,matchesSaved,workout,page:p};current=historical?current:api;

  function close(){if(historical&&JSON.stringify(d)!==baseline){discardEdits();return}p.close()}
  function update(){
    if(historical){clockEl.textContent=clock(d.edit_original.duration_seconds||0);pace.textContent='Editing · '+store.day(d.edit_original);bar.hidden=true;return}
    clockEl.textContent=clock(elapsed()/1000);pauseBtn.textContent=d.paused_ms>0?'Resume':'Pause';
    let plan=0,left=0;const now=Date.now();
    for(const e of ex()){const ms=(e.planned||0)*1000;plan+=ms;if(e.ended_ms>0)continue;left+=Math.max(0,ms-(e.started_ms>0?now-e.started_ms:0))}
    if(plan>0){const projected=elapsed()+left,diff=Math.round((plan-projected)/60000),end=new Date(now+left).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'});
      pace.textContent=(diff===0?'On plan':Math.abs(diff)+' min '+(diff>0?'ahead':'behind'))+' · ends '+end;pace.style.color=diff<-3?'var(--warning)':diff>=0?'var(--success)':''}
    else pace.textContent='';
    bar.replaceChildren(...ex().map(e=>{const s=el('span');s.style.flexGrow=Math.max(1,e.planned||60);s.className=e.ended_ms>0?'done':e.started_ms>0?'now':'';return s}));
  }
  const groupHue=i=>{const g=ex()[i].group;if(!g)return null;const seen=[];for(let k=0;k<=i;k++){const x=ex()[k].group;if(x&&!seen.includes(x))seen.push(x)}return GROUP[(seen.length-1)%GROUP.length]};

  function render(){
    if(reordering){reorderList();return}
    const y=p.body.scrollTop;list.replaceChildren();
    ex().forEach((e,i)=>{list.append(card(i));if(i+1<ex().length)list.append(linkBar(i))});
    list.append(el('div',{class:'live-tools'},button(el('span',{},icon('plus'),'Add exercise'),'btn quiet grow',addExercise),iconButton('sparkle','Ask your coach',coach,'tonal',HUE.violet)));
    const notes=el('textarea',{class:'field',rows:2,placeholder:'Workout notes',value:d.notes||'',attrs:{'aria-label':'Workout notes'}});notes.oninput=()=>{d.notes=notes.value;changed()};
    list.append(notes,button(historical?'Discard changes':'Cancel workout','btn ghost danger-text',historical?discardEdits:cancel));
    p.body.scrollTop=y;update();
  }
  function linkBar(i){
    const on=!!ex()[i].group&&ex()[i].group===ex()[i+1].group,tint=on?groupHue(i):null;
    const b=iconButton('link',on?'Break superset':'Superset with next',()=>link(i),'link-btn'+(on?' on':''),tint||undefined);
    const wrap=el('div',{class:'link-bar'+(on?' on':'')},b);if(tint)wrap.style.setProperty('--link',tint);return wrap;
  }
  function link(i){const e=ex()[i],n=ex()[i+1],g=e.group,h=n.group;
    if(g&&g===h){const tail=uid();for(let k=i+1;k<ex().length&&ex()[k].group===g;k++)ex()[k].group=tail;note('edit_exercises','Split a superset')}
    else{const join=g||h||uid();e.group=join;for(let k=i+1;k<ex().length&&(k===i+1||(h&&ex()[k].group===h));k++)ex()[k].group=join;note('edit_exercises','Linked a superset')}
    haptic();tidy();save();render()}
  /** A superset is a run of neighbours: a lone exercise leaves its group. */
  function tidy(){const used=new Set(),n=ex().length;for(let i=0;i<n;){const g=ex()[i].group;let j=i+1;while(j<n&&g&&ex()[j].group===g)j++;if(g){const id=j-i<2?'':used.has(g)?uid():(used.add(g),g);for(let k=i;k<j;k++)ex()[k].group=id}i=j}}

  function card(index){
    const e=ex()[index],id=e.eid,run=store.cardio(id),info=store.data('exercise',id),tint=groupHue(index);
    const box=el('article',{class:'ex-card'});if(tint){box.classList.add('grouped');box.style.setProperty('--link',tint)}
    const art=tile(id,44),name=el('div',{class:'grow ex-name'},el('strong',{text:store.exerciseName(id)}),target(e)?el('small',{text:target(e)}):null);
    name.querySelector('strong').style.color=exerciseHue(info);
    const history=el('button',{type:'button',class:'ex-open',attrs:{'aria-label':'Open '+store.exerciseName(id)+' history'}},art,name);history.onclick=()=>nav.exercise(id);
    box.append(el('div',{class:'ex-head'},history,iconButton('more','Exercise options',()=>{actions=actions===index?-1:index;render()})));
    if(actions===index)box.append(el('div',{class:'ex-actions'},
      iconButton('refresh','Replace exercise',()=>replace(index),'',HUE.blue),iconButton('grip','Reorder exercises',()=>{reordering=true;actions=-1;render()},'',HUE.violet),
      iconButton('chat','Note',()=>noteOn(index),'',HUE.amber),iconButton('trash','Remove exercise',()=>removeExercise(index),'',HUE.red)));
    const unit=run?units.distanceLabel(id):units.loadLabel(id);
    const switcher=el('button',{type:'button',class:'unit-switch',text:unit,attrs:{'aria-label':'Unit '+unit+'. Switch for this exercise'}});switcher.onclick=()=>{units.flip(id);haptic();render()};
    box.append(el('div',{class:'set-cols'+(run?' run':'')},el('span',{text:'Set'}),el('span',{text:'Previous'}),switcher,el('span',{text:run?'Time':'Reps'}),run?null:el('span',{text:'RIR'}),el('span')));
    const before=previous(id);let number=0;
    e.sets.forEach((s,i)=>{if(s.kind==='working')number++;const b=previousFor(before,e.sets,i);
      const old=b?(run?units.distanceNumber(b.distance_m||0,id)+' · '+clock(b.seconds):units.loadNumber(b.weight_kg||0,id)+' × '+(b.reps??'')):'–';box.append(setRow(index,i,s,number,old,run))});
    box.append(button(el('span',{},icon('plus'),'Add set'),'btn ghost add-set',()=>addSet(index)));
    if(e.note)box.append(el('p',{class:'ex-note',text:e.note}));
    return box;
  }
  function target(e){
    if(historical)return '';const t=d.template_id?store.data('template',d.template_id):null;const p=(t?.exercises||[]).find(x=>x.exercise_id===e.eid);if(!p)return '';
    if(p.distance_m!=null)return 'Target '+units.distance(p.distance_m)+(p.speed_kmh!=null?' at '+units.speed(p.speed_kmh):'');
    const reps=p.min_reps===p.max_reps?String(p.min_reps):p.min_reps+'–'+p.max_reps;return 'Target '+(p.sets||1)+' × '+reps+(p.rir==null?'':' · '+num(p.rir)+' in reserve');
  }
  function previous(id){
    if(!historical)return store.previous(id);const day=store.day(d.edit_original);
    for(const r of store.workouts()){const w=r.data;if(w.status!=='completed'||!(store.day(w)<day))continue;const found=(w.sets||[]).filter(s=>s.exercise_id===id&&s.completed!==false&&s.kind!=='note');if(found.length)return found}
    return [];
  }
  /** Warm-ups line up with last time's warm-ups, hard sets with hard sets. */
  function previousFor(before,sets,index){const warm=sets[index].kind==='warmup';let nth=0;for(let i=0;i<index;i++)if((sets[i].kind==='warmup')===warm)nth++;return before.filter(b=>(b.kind==='warmup')===warm)[nth]||null}

  function input(value,label,mode,onInput){const v=el('input',{class:'set-input',value,attrs:{'aria-label':label,inputmode:mode,enterkeyhint:'next',autocomplete:'off'}});v.onfocus=()=>v.select();v.oninput=()=>{onInput(v.value.trim().replace(',','.'));changed()};return v}
  const parse=t=>{const n=Number(t);return t===''||!Number.isFinite(n)?null:n};
  function setRow(ex_,index,s,number,old,run){
    const id=ex()[ex_].eid,row=el('div',{class:'set-row'+(run?' run':'')+(s.done?' done':'')});
    const tag=setTag(s.kind,number);tag.setAttribute('role','button');tag.tabIndex=0;tag.setAttribute('aria-label','Set type '+s.kind+'. Tap to change');
    tag.onclick=()=>{const order=['working','warmup','drop','failure'];s.kind=order[(order.indexOf(s.kind)+1)%4];haptic();save();render()};tag.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();tag.click()}};
    const prev=el('button',{type:'button',class:'set-prev',text:old,attrs:{'aria-label':'Previous '+old+'. Tap to copy'}});prev.onclick=()=>usePrevious(ex_,index);
    row.append(tag,prev);
    if(run){
      row.append(input(s.distance!=null?units.distanceNumber(s.distance,id):'','Distance','decimal',t=>{const n=parse(t);if(n==null)delete s.distance;else s.distance=units.distanceIn(n,id)}),
        input(s.seconds!=null?clock(s.seconds):'','Time in minutes and seconds','numeric',t=>{const n=seconds(t);if(n>0)s.seconds=n;else delete s.seconds}));
    }else{
      row.append(input(s.weight!=null?units.loadNumber(s.weight,id):'','Weight','decimal',t=>{const n=parse(t);if(n==null)delete s.weight;else s.weight=units.loadIn(n,id)}),
        input(s.reps!=null?String(s.reps):'','Reps','numeric',t=>{const n=parse(t);if(n==null)delete s.reps;else s.reps=Math.round(n)}),
        input(s.rir!=null?num(s.rir):'','Reps in reserve','decimal',t=>{const n=parse(t);if(n==null)delete s.rir;else s.rir=n}));
    }
    const check=iconButton('check',s.done?'Unmark set':'Complete set',()=>tick(ex_,index),'set-check');row.append(check);
    swipe(row,()=>removeSet(ex_,index),()=>tick(ex_,index));
    return row;
  }
  /** Swipe left to delete, right to complete, as on Android. A vertical move stays a scroll. */
  function swipe(row,left,right){
    let x0=0,y0=0,dx=0,active=false,decided=false;
    row.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse'||e.target.closest('input'))return;x0=e.clientX;y0=e.clientY;dx=0;active=true;decided=false});
    row.addEventListener('pointermove',e=>{if(!active)return;const mx=e.clientX-x0,my=e.clientY-y0;
      if(!decided){if(Math.abs(my)>10){active=false;return}if(Math.abs(mx)>10){decided=true;row.setPointerCapture(e.pointerId)}else return}
      dx=mx;row.style.transform=`translateX(${dx}px)`;row.dataset.swipe=dx<0?'delete':'done';row.style.setProperty('--reveal',Math.min(1,Math.abs(dx)/90))});
    const end=()=>{if(!active)return;active=false;row.style.transform='';delete row.dataset.swipe;if(!decided)return;if(dx<-90){haptic(14);left()}else if(dx>90){haptic(10);right()}};
    row.addEventListener('pointerup',end);row.addEventListener('pointercancel',end);
  }
  const seconds=t=>{const p=t.split(':').map(x=>parseInt(x,10));if(p.some(Number.isNaN))return 0;const v=p.reduce((a,b)=>a*60+b,0);return p.length===1?v*60:v};
  function usePrevious(e_,index){const e=ex()[e_],b=previousFor(previous(e.eid),e.sets,index),s=e.sets[index];if(!b)return;
    if(b.weight_kg!=null)s.weight=b.weight_kg;if(b.reps!=null)s.reps=b.reps;if(b.distance_m!=null)s.distance=b.distance_m;if(b.seconds!=null)s.seconds=b.seconds;haptic();save();render()}
  function removeSet(e_,index){const e=ex()[e_];e.sets.splice(index,1);note('edit_exercises','Removed a set of '+store.exerciseName(e.eid));save();render()}
  function addSet(e_){const e=ex()[e_],last=e.sets[e.sets.length-1],set=last?structuredClone(last):{kind:'working'};set.id=uid();set.done=false;if(set.kind==='warmup')set.kind='working';e.sets.push(set);note('edit_exercises','Added a set of '+store.exerciseName(e.eid));save();render()}
  function tick(e_,index){
    const e=ex()[e_],s=e.sets[index],run=store.cardio(e.eid);
    if(!s.done&&!(run?s.distance!=null&&s.seconds!=null:s.reps!=null)){toast(run?'Enter distance and time':'Enter the reps');return}
    s.done=!s.done;haptic(s.done?12:6);
    if(!historical){const now=Date.now();
      if(s.done){if(!e.started_ms)e.started_ms=Math.max(d.started_ms,now-(e.planned||0)*1000/Math.max(1,e.sets.length));if(e.sets.every(x=>x.done))e.ended_ms=now;
        if(e.ended_ms>0&&e_+1<ex().length&&!ex()[e_+1].started_ms)ex()[e_+1].started_ms=now;record(e.eid,s)}
      else e.ended_ms=0}
    save();render();if(s.done&&!historical)hop(e_);
  }
  /** In a superset the next open set is in the next exercise, so the page moves there. */
  function hop(e_){const g=ex()[e_].group;if(!g)return;const n=ex().length;for(let k=1;k<n;k++){const i=(e_+k)%n;if(ex()[i].group===g&&ex()[i].sets.some(s=>!s.done)){list.querySelectorAll('.ex-card')[i]?.scrollIntoView({behavior:'smooth',block:'start'});return}}}
  function record(id,s){const value=store.e1rm({kind:s.kind,weight_kg:s.weight||0,reps:s.reps});if(value<=0)return;
    const r=(store.overview().personal_records||[]).find(x=>x.exercise_id===id);const recent=r?.recent_best?.estimated_1rm_kg||0,all=r?.historical_best?.estimated_1rm_kg||0;
    if(value>all&&all>0)toast('New all-time record · estimated max '+units.load(value,id),'win');else if(value>recent&&recent>0)toast('New best since your return · estimated max '+units.load(value,id),'win')}
  function pause(){const now=Date.now();if(d.paused_ms>0){d.paused_total+=now-d.paused_ms;d.paused_ms=0}else d.paused_ms=now;save();update()}
  async function rename(){const r=await promptDialog('Workout name',[{name:'name',label:'Workout name',value:d.name}]);if(r?.name){d.name=r.name;title.textContent=r.name;save()}}
  function addExercise(){nav.pick(id=>{const e=planned({exercise_id:id,sets:1,rest_seconds:120,min_reps:0},null);ex().push(e);note('edit_exercises','Added '+store.exerciseName(id));save();render();requestAnimationFrame(()=>focus(id))})}
  function replace(index){const e=ex()[index];actions=-1;nav.pick(id=>{const was=store.exerciseName(e.eid);e.eid=id;note('edit_exercises','Replaced '+was+' with '+store.exerciseName(id));save();render()})}
  async function noteOn(index){const e=ex()[index];const r=await promptDialog('Exercise note',[{name:'note',label:'Note',value:e.note}]);if(r){e.note=r.note;actions=-1;save();render()}}
  function removeExercise(index){const e=ex().splice(index,1)[0];actions=-1;note('edit_exercises','Removed '+store.exerciseName(e.eid));tidy();save();render()}
  function move(from,to){if(to<0||to>=ex().length||from===to)return;const [x]=ex().splice(from,1);ex().splice(to,0,x);note('edit_exercises','Reordered exercises')}
  /** Cards collapse to names so the whole order fits; drag a row by its grip, or use the arrows. */
  function reorderList(){
    list.replaceChildren(el('p',{class:'hint',text:'Drag to reorder'}));
    const rows=ex().map((e,i)=>{const grip=el('span',{class:'grip',attrs:{'aria-hidden':'true'}},icon('grip'));
      const r=el('div',{class:'reorder-row',attrs:{role:'listitem'}},tile(e.eid,40),el('strong',{class:'grow',text:store.exerciseName(e.eid)}),
        iconButton('up','Move up',()=>{move(i,i-1);reorderList()},'small'),iconButton('down','Move down',()=>{move(i,i+1);reorderList()},'small'),grip);
      grip.addEventListener('pointerdown',ev=>drag(ev,r,i));return r});
    list.append(el('div',{class:'reorder',attrs:{role:'list'}},...rows),button('Done','btn primary wide',()=>{reordering=false;tidy();save();render()}));
  }
  function drag(ev,row,from){
    ev.preventDefault();const rows=[...list.querySelectorAll('.reorder-row')],h=row.getBoundingClientRect().height+8,y0=ev.clientY;let to=from;row.classList.add('dragging');row.setPointerCapture(ev.pointerId);haptic(10);
    const moveH=e=>{const dy=e.clientY-y0;row.style.transform=`translateY(${dy}px)`;to=Math.max(0,Math.min(rows.length-1,from+Math.round(dy/h)));
      rows.forEach((r,i)=>{if(r===row)return;const shift=from<to&&i>from&&i<=to?-h:from>to&&i<from&&i>=to?h:0;r.style.transform=shift?`translateY(${shift}px)`:''})};
    const up=()=>{row.removeEventListener('pointermove',moveH);row.removeEventListener('pointerup',up);row.removeEventListener('pointercancel',up);move(from,to);save();reorderList()};
    row.addEventListener('pointermove',moveH);row.addEventListener('pointerup',up);row.addEventListener('pointercancel',up);
  }

  /** The wire format: an active copy keeps open sets so the coach can adapt them; a finished one holds only ticked sets. */
  function workout(status){
    const sets=[],blocks=[],extras={},finished=status==='completed';
    ex().forEach((e,i)=>{for(const s of e.sets){if(finished&&!s.done)continue;const o={id:s.id,exercise_id:e.eid,kind:s.kind||'working',completed:!!s.done};for(const [a,b] of FIELDS)if(s[a]!=null)o[b]=s[a];sets.push(o)}
      const b={id:'b'+i+'-'+d.workout_id,kind:store.cardio(e.eid)?'run':'exercise',exercise_id:e.eid,planned_seconds:Math.min(86400,Math.round(e.planned||0))};
      if(e.started_ms>0){b.started_at=iso(e.started_ms,d.timezone);if(e.ended_ms>=e.started_ms)b.ended_at=iso(e.ended_ms,d.timezone)}blocks.push(b);
      extras[e.eid]={note:e.note||'',rest:e.rest??120,group:e.group||''}});
    const o={name:d.name,started_at:iso(d.started_ms,d.timezone),timezone:d.timezone,duration_seconds:Math.round(elapsed()/1000),status,sets,blocks,session_changes:d.changes,notes:d.notes||'',source:{companion:{scheduled_date:d.scheduled_date||'',exercises:extras,client:'train-web',...(d.scheduled_session_id?{scheduled_session_id:d.scheduled_session_id}:{})}}};
    if(d.sprint_id)o.sprint_id=d.sprint_id;if(d.template_id)o.template_id=d.template_id;return o;
  }
  async function finish(){
    const open=ex().reduce((n,e)=>n+e.sets.filter(s=>!s.done).length,0);
    if(!await confirmDialog('Finish workout?',open?open+(open===1?' unticked set':' unticked sets')+' will be left out.':'All sets are ticked.','Finish','Keep going'))return;
    const w=workout('completed'),before=structuredClone(store.overview());store.putEntity('workout',d.workout_id,w);store.clearDraft();closed=true;clearTimeout(saveTimer);
    current=null;p.onclose=null;p.close();clearInterval(timer);nav.finished(d.workout_id,w,before,structuredClone(d.exercises));
  }
  async function cancel(){
    if(!await confirmDialog('Cancel workout?','Nothing from this session will be kept.','Cancel workout','Keep going',true))return;
    clearTimeout(saveTimer);store.clearDraft();if(store.data('workout',d.workout_id))store.deleteEntity('workout',d.workout_id);discard();
  }
  function discard(){clearTimeout(saveTimer);store.clearDraft();closed=true;current=null;p.onclose=null;clearInterval(timer);p.close();nav.refresh()}
  async function discardEdits(){if(await confirmDialog('Discard changes?','The saved workout stays as it was.','Discard','Keep editing',true)){store.clearEdit();p.onclose=null;p.close();nav.refresh()}}
  function saveEdits(){
    if(JSON.stringify(d)===baseline){store.clearEdit();p.close();afterSave?.();return}
    const latest=store.data('workout',d.workout_id);if(!same(latest,d.edit_original)){toast('This workout changed elsewhere. Reopen it before saving.');return}
    store.putEntity('workout',d.workout_id,savedEdit(d));store.clearEdit();p.onclose=null;p.close();afterSave?.();nav.refresh();toast('Changes saved on this device');
  }
  function coach(){
    if(historical){nav.coach({current_workout_id:d.workout_id},null);return}
    store.putEntity('workout',d.workout_id,workout('active'));nav.coach({current_workout_id:d.workout_id},api);
  }
  /** A locally changed set must reach the coach again before an older proposal can apply. */
  function matchesSaved(){const saved=store.data('workout',d.workout_id);if(!saved)return false;const a=saved.sets||[],b=workout('active').sets;if(a.length!==b.length)return false;
    const keys=['id','exercise_id','kind','completed','weight_kg','reps','rir','distance_m','seconds'];return a.every((x,i)=>keys.every(k=>String(x[k]??'')===String(b[i][k]??'')))}
  /** After an approved change the session follows the proposal in full. */
  function adopt(w){const kept=new Map(ex().map(e=>[e.eid,{...e,sets:[]}])),next=[];
    for(const s of w.sets||[]){let e=kept.get(s.exercise_id);if(!e){e={eid:s.exercise_id,rest:120,note:'',group:'',started_ms:0,ended_ms:0,planned:240,sets:[]};kept.set(s.exercise_id,e)}
      if(!e.sets.length)next.push(e);const row={id:s.id,kind:s.kind||'working',done:!!s.completed};for(const [a,b] of FIELDS)if(s[b]!=null)row[a]=s[b];e.sets.push(row)}
    d.exercises=next;if(w.name)d.name=w.name;save();render()}
  function focus(id){const i=ex().findIndex(e=>e.eid===id);if(i>=0)list.querySelectorAll('.ex-card')[i]?.scrollIntoView({block:'start'})}

  render();if(!historical)timer=setInterval(()=>{if(!closed)update()},1000);
  if(!historical&&navigator.wakeLock)navigator.wakeLock.request('screen').catch(()=>{});
  return api;
}
