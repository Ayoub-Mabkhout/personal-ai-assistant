// One durable conversation. The relay accepts questions while the coach is offline.
import {el,icon,iconButton,page,toast,uid,clock} from './core.js';
import * as store from './store.js';
import * as units from './units.js';
import {api,ApiError} from './api.js';
import {tile} from './art.js';
import {nav} from './nav.js';

const PENDING='train-coach-pending';
const pending=()=>{try{return JSON.parse(sessionStorage.getItem(PENDING))||{}}catch{return {}}};
/** context may carry current_workout_id, sprint_id or template_id; the server ignores anything else from a browser. */
export function open(context={},live=null,prefill='',photos=[]){
  const wire={};for(const k of ['current_workout_id','sprint_id','template_id'])if(context[k])wire[k]=context[k];
  const state=el('span',{class:'chip-status',text:'Checking…'});
  const p=page('Coach',{cls:'coach',actions:[state]});
  const items=el('div',{class:'chat',attrs:{'aria-live':'polite'}});p.body.append(items);
  const input=el('textarea',{class:'field chat-input',rows:1,placeholder:'Ask your coach',value:prefill||pending().text||'',attrs:{'aria-label':'Ask your coach',enterkeyhint:'send'}});
  input.oninput=()=>{input.style.height='auto';input.style.height=Math.min(140,input.scrollHeight)+'px'};
  const send=iconButton('send','Send',ask,'send-btn');requestAnimationFrame(()=>input.oninput());
  const attached=photos.length?el('p',{class:'hint',text:photos.length+(photos.length===1?' photo':' photos')+' attached for this question only'}):null;
  p.root.append(el('footer',{class:'chat-bar'},attached,el('div',{class:'chat-row'},input,send)));
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&matchMedia('(pointer:fine)').matches){e.preventDefault();ask()}});
  let seen='',timer=0;
  async function poll(){
    if(p.closed)return;
    try{const r=await api('trainer/conversation?limit=50');const on=!!r.status?.available;state.textContent=on?'Online':'Offline';state.dataset.on=String(on);
      const key=JSON.stringify([on,r.items]);if(key!==seen){seen=key;paint(r.items||[],on);requestAnimationFrame(()=>p.body.scrollTo({top:p.body.scrollHeight,behavior:'smooth'}))}}
    catch{state.textContent='No connection';state.dataset.on='false'}
    timer=setTimeout(poll,5000);
  }
  async function ask(){
    const text=input.value.trim();if(!text)return;send.disabled=true;
    // The same question keeps its ID across retries, so a slow network can't ask it twice.
    const key=text+'\n'+JSON.stringify(wire)+'\n'+photos.join(',');const prior=pending();const id=prior.key===key?prior.id:uid();
    try{sessionStorage.setItem(PENDING,JSON.stringify({key,id,text}))}catch{}
    try{const problem=await store.sync();if(problem&&problem!=='')throw new Error(problem);
      const result=await api('trainer/questions',{body:{id,text,photos,photo_approval:photos.length>0,context:wire}});
      if(result.state==='queued')toast('Message queued. Check this Coach chat for the reply.');
      input.value='';input.style.height='';photos=[];attached?.remove();try{sessionStorage.removeItem(PENDING)}catch{}clearTimeout(timer);poll()}
    catch(e){toast(e instanceof ApiError?(e.status===409?'Couldn’t queue this message. Your draft is still here.':'Your server refused the question.'):'No connection. Your draft is still here. Tap Send when connected.')}
    finally{send.disabled=false}
  }
  function paint(list,online){
    const shown=list.filter(q=>!['next_session_brief','sprint_brief'].includes(q.context?.purpose));
    if(!shown.length){items.replaceChildren(el('p',{class:'empty',text:online?'Ask about a swap, fatigue, pain or your plan.':'The coach is offline. You can still send a message. The reply will appear in this chat when the coach is back.'}));return}
    items.replaceChildren(...shown.flatMap(q=>{const mine=el('p',{class:'bubble mine',text:q.question});
      if(q.state==='completed'){const c=el('div',{class:'bubble coach'},el('p',{text:q.answer}));proposals(c,q);return [mine,c]}
      const message=q.state==='failed'?"Your coach couldn't answer. Try again.":q.state==='queued'?
        (online?'Queued. The reply will appear here.':'Queued. The reply will appear here when the coach is back online.'):'Your coach is thinking…';
      return [mine,el('p',{class:'bubble wait'+(q.state==='failed'?' failed':''),text:message})]}));
  }
  /** Shows what each proposal would change next to what's there now; Apply takes them all, once. */
  function proposals(c,q){
    const list=q.proposals||[];if(!list.length)return;const done=!!q.approved;
    c.append(el('p',{class:'proposal-title',text:'Proposed changes'}));
    for(const x of list){const now=store.data(x.kind,x.id);if(x.kind==='exercise'&&x.data)c.append(tile(x.data,64));
      c.append(el('p',{class:'proposal before',text:'Before: '+describe(x.kind,now)}),el('p',{class:'proposal after'+(x.deleted?' deleted':''),text:x.deleted?'After: deleted.'+(x.kind==='workout'?' Sprint progress and your next workout recalculate.':''):'After: '+describe(x.kind,x.data)}))}
    if(done){c.append(el('p',{class:'applied',text:'Applied'}));return}
    const apply=el('button',{type:'button',class:'btn quiet',text:'Apply changes'});
    apply.onclick=async()=>{
      if(live&&!live.matchesSaved()){toast('Your workout changed since your coach saw it. Ask again before applying changes.');return}
      apply.disabled=true;
      try{await api(`trainer/${encodeURIComponent(q.id)}/approve`,{body:{}});await store.sync();
        if(live)for(const x of list)if(x.kind==='workout'&&x.id===live.d.workout_id){if(x.deleted)live.discard();else live.adopt(x.data)}
        nav.refresh();clearTimeout(timer);poll()}
      catch(e){toast(e instanceof ApiError?(e.status===409?'That changed since your coach answered. Ask again.':'Your server refused the change.'):'No connection. Nothing changed.')}
      finally{apply.disabled=false}};
    c.append(apply);
  }
  poll();setTimeout(()=>input.focus({preventScroll:true}),120);
}
function describe(kind,d){
  if(!d)return 'new '+kind;
  if(kind==='sprint')return d.name+' · '+d.phase+' · '+(d.target_sessions||0)+' workouts until '+d.end+(d.cycle?' · cycle of '+d.cycle.length:'');
  if(kind==='template')return d.name+((d.exercises||[]).length?': '+d.exercises.map(p=>store.exerciseName(p.exercise_id)+' '+(p.sets||1)+'×'+(p.min_reps??'')).join(', '):'');
  if(kind!=='workout')return d.name||kind;
  const rows=new Map();for(const x of d.sets||[]){const n=store.exerciseName(x.exercise_id);if(!rows.has(n))rows.set(n,[]);
    rows.get(n).push((x.distance_m!=null?units.distance(x.distance_m)+' in '+clock(x.seconds):(x.weight_kg!=null?units.load(x.weight_kg)+' × ':'')+(x.reps??0))+(x.completed===false?' (open)':''))}
  return [...rows].map(([n,v])=>n+': '+v.join(', ')).join('; ')||d.name;
}
