// The phone-side Train store, ported from the Android WorkoutStore: revisioned entities, an ordered outbox with stable mutation
// IDs, conflict review, and a live draft. Everything lives in IndexedDB so a workout survives a closed tab or a dead signal.
import {uid} from './core.js';
import {api,ApiError} from './api.js';

const DB='train',STORE='kv';
let db=null,cache={cursor:0,entities:{},overview:{}},outbox=[],draftValue=null,editValue=null;
const listeners=new Set();
export const onChange=f=>{listeners.add(f);return()=>listeners.delete(f)};
const emit=()=>listeners.forEach(f=>{try{f()}catch(e){console.error(e)}});

function open(){return new Promise((resolve,reject)=>{const r=indexedDB.open(DB,1);r.onupgradeneeded=()=>r.result.createObjectStore(STORE);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})}
function get(key){return new Promise(resolve=>{try{const r=db.transaction(STORE).objectStore(STORE).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>resolve(undefined)}catch{resolve(undefined)}})}
function put(key,value){return new Promise(resolve=>{try{const t=db.transaction(STORE,'readwrite');t.objectStore(STORE).put(value,key);t.oncomplete=()=>resolve(true);t.onerror=()=>resolve(false)}catch{resolve(false)}})}
const save={cache:()=>put('cache',cache),outbox:()=>put('outbox',outbox)};

/** Loads what this device already knows; the account key keeps two people on one browser apart. */
export async function load(account){
  db=db||await open();
  const prefix=account+':';
  save.cache=()=>put(prefix+'cache',cache);save.outbox=()=>put(prefix+'outbox',outbox);
  cache=(await get(prefix+'cache'))||{cursor:0,entities:{},overview:{}};outbox=(await get(prefix+'outbox'))||[];
  draftValue=(await get(prefix+'draft'))||null;editValue=(await get(prefix+'edit'))||null;
  saveDraft.key=prefix+'draft';saveEdit.key=prefix+'edit';emit();
}
export function rows(kind){const group=cache.entities[kind]||{};return Object.entries(group).filter(([,r])=>r&&!r.deleted).map(([id,r])=>({id,revision:r.revision||0,data:r.data||{}}))}
export function data(kind,id){const r=cache.entities[kind]?.[id];return r&&!r.deleted?r.data:null}
export function revision(kind,id){return cache.entities[kind]?.[id]?.revision||0}
export const overview=()=>cache.overview||{};
function apply(kind,id,rev,deleted,value){(cache.entities[kind]||(cache.entities[kind]={}))[id]={revision:rev,deleted,data:value||{}}}

/** Saves an edit here first and queues it; the same mutation ID is reused for every retry. */
export function putEntity(kind,id,value){queue(kind,id,value,false)}
export function deleteEntity(kind,id){queue(kind,id,data(kind,id),true)}
function queue(kind,id,value,deleted){
  const rev=revision(kind,id);
  outbox.push({mutation_id:uid(),kind,id,base_revision:rev,deleted,data:value?structuredClone(value):{}});
  apply(kind,id,rev,deleted,value);save.outbox();save.cache();emit();
}
export const waiting=()=>outbox.length;
export const conflicts=()=>outbox.filter(o=>o.conflict);
const pending=(kind,id)=>outbox.some(o=>o.kind===kind&&o.id===id);

/** The owner's choice on a rejected edit: keep it on top of the newest revision, or take the server's version. */
export async function resolve(mutation,keep){
  const op=outbox.find(o=>o.mutation_id===mutation);if(!op)return;
  const latest=await api(`entities/${op.kind}/${encodeURIComponent(op.id)}`);
  const i=outbox.indexOf(op);
  if(keep){delete op.conflict;delete op.sent;op.mutation_id=uid();op.base_revision=latest.revision}
  else{outbox.splice(i,1);apply(op.kind,op.id,latest.revision,latest.deleted,latest.data);await save.cache()}
  await save.outbox();emit();
}

let syncing=null;
/** Pushes the outbox in order, then pulls changes and the overview. Resolves to a readable problem, or "". */
export function sync(){if(!syncing)syncing=run().finally(()=>{syncing=null});return syncing}
async function run(){
  try{
    for(;;){
      const op=outbox.find(o=>!o.conflict);if(!op)break;op.sent=true;await save.outbox();
      const wire={...op};delete wire.sent;delete wire.conflict;
      try{
        const result=(await api('sync',{method:'POST',body:{operations:[wire]}})).results[0];
        outbox.splice(outbox.indexOf(op),1);
        for(const later of outbox)if(later.kind===op.kind&&later.id===op.id)later.base_revision=result.revision;
        await save.outbox();
        if(!pending(op.kind,op.id)){apply(result.kind,result.id,result.revision,result.deleted,result.data);await save.cache()}
      }catch(e){if(e instanceof ApiError&&(e.status===409||e.status===422)){op.conflict=true;await save.outbox()}else throw e}
    }
    for(;;){
      const page=await api(`changes?after=${cache.cursor||0}&limit=100`);
      for(const r of page.items||[])if(!pending(r.kind,r.id))apply(r.kind,r.id,r.revision,r.deleted,r.data);
      cache.cursor=page.cursor??cache.cursor;await save.cache();if(!page.has_more)break;
    }
    cache.overview=await api('overview');await save.cache();emit();return '';
  }catch(e){emit();if(e instanceof ApiError){if(e.status===401)return 'signed_out';return `Your server refused the update (${e.status}). Your entries stay on this device.`}return 'Offline. Your entries stay on this device.'}
}

export const draft=()=>draftValue;
export function saveDraft(d){draftValue=d;put(saveDraft.key,d);emit()}
export function clearDraft(){draftValue=null;put(saveDraft.key,null);emit()}
/** A past workout being corrected keeps its own draft, apart from the active session. */
export const edit=()=>editValue;
export function saveEdit(d){editValue=d;put(saveEdit.key,d)}
export function clearEdit(){editValue=null;put(saveEdit.key,null)}

export const exerciseName=id=>data('exercise',id)?.name||id;
export const cardio=id=>data('exercise',id)?.mode==='cardio';
export function workouts(){return rows('workout').sort((a,b)=>String(b.data.started_at).localeCompare(String(a.data.started_at)))}
/** The date a workout happened, in its own time zone. */
export function day(w){
  const at=w.started_at||'';const t=Date.parse(at);if(Number.isNaN(t))return at.slice(0,10)||null;
  try{return new Intl.DateTimeFormat('en-CA',{timeZone:w.timezone||'UTC',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(t))}catch{return at.slice(0,10)}
}
export function today(){return new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
/** The most recent completed sets of an exercise, for the Previous column. */
export function previous(exercise){
  for(const w of workouts()){if(w.data.status!=='completed')continue;const found=(w.data.sets||[]).filter(s=>s.exercise_id===exercise&&s.completed!==false&&s.kind!=='note');if(found.length)return found}
  return [];
}
export function e1rm(s){if(!['working','failure'].includes(s.kind)||!s.weight_kg||!s.reps||s.reps>10)return 0;return s.reps===1?s.weight_kg:s.weight_kg*(1+s.reps/30)}
/** The active sprint, or the next one that hasn't ended. */
export function sprint(){
  const now=today();let best=null;
  for(const r of rows('sprint')){const d=r.data;if(['cancelled','completed'].includes(d.status))continue;if(d.status==='active')return r;if(d.end<now)continue;if(!best||d.start<best.data.start)best=r}
  return best;
}
export function sprintCompleted(id){return workouts().filter(w=>w.data.sprint_id===id&&w.data.status==='completed').length}
/** Next in the cycle, counted from what this device knows, so finishing or deleting a session moves it at once. */
export function next(){
  const local=sprint();let finished='';
  if(local){const d=local.data,cycle=d.cycle||[];if(cycle.length){const count=sprintCompleted(local.id),target=d.target_sessions||cycle.length;
    if(count>=target)finished=local.id;else{const t=cycle[count%cycle.length],o=overview().next_workout,slot=o?.sprint_id===local.id&&o.template_id===t&&o.starts_at?o:null;
    return {sprint:local,template_id:t,date:slot?.date||today(),index:count+1,total:target,starts_at:slot?.starts_at||null,scheduled_session_id:slot?.scheduled_session_id||null}}}}
  const planned=overview().next_workout;
  if(planned?.template_id&&finished!==planned.sprint_id){const d=data('sprint',planned.sprint_id);return {sprint:d?{id:planned.sprint_id,data:d}:null,template_id:planned.template_id,date:planned.date||today(),index:planned.sequence_number||(planned.position??0)+1,total:planned.target_sessions||0,starts_at:planned.starts_at||null,scheduled_session_id:planned.scheduled_session_id||null}}
  return null;
}
export const athlete=()=>data('athlete','self')||{};
