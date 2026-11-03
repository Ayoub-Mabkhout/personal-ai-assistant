// The dashboard and the pages it opens directly: the end-of-workout screen, ranks, running, profile with reminders, and the
// shared standings. Ported from Android's WorkoutScreen; the next workout leads and everything else is one tap into its own page.
import {el,icon,iconButton,button,page,confirmDialog,toast,card,stat,pair,label,row,HUE,cssColor,alpha,haptic,num,clock,plural,reduced} from './core.js';
import * as store from './store.js';
import * as units from './units.js';
import {api,ApiError} from './api.js';
import {crest,ridge,bodyMap,spark,tierIndex,tierOf,tierColor,label as tierLabel,tile} from './art.js';
import {chart,epochDay} from './chart.js';
import * as history from './history.js';
import * as plan from './plan.js';
import * as body from './body.js';
import * as live from './live.js';
import {nav} from './nav.js';
import * as settings from './settings.js';
import {FIRST_SPRINT} from './setup.js';

let root=null,loading=false,problem='',chosen=null,me=null;
export function mount(node,account){root=node;me=account;render()}
export const account=()=>me;
const overview=()=>store.overview();
const autoBriefs=()=>!!store.athlete().auto_coach_briefs;

/** Sync, then repaint; a sign-out sends the page back to the join screen. */
export async function refresh(){
  render();if(loading)return;loading=true;render();
  const m=await store.sync();loading=false;problem=m==='signed_out'?'':m;if(m==='signed_out'){location.reload();return}render();
}
export function render(){
  if(!root)return;const o=overview();
  const head=el('header',{class:'dash-head'},el('h1',{text:'Train'}),coachChip());
  const parts=[head];
  for(const c of store.conflicts())parts.push(conflictBanner(c));
  if(me?.setup_complete===false)parts.push(setupBanner());
  const d=store.draft();parts.push(d?resume(d):next());
  parts.push(el('div',{class:'tiles'},sprintTile(),rankTile(o),weightTile(o),runTile(o)));
  parts.push(el('nav',{class:'doors','aria-label':'Train sections'},
    door('history','History',HUE.amber,()=>history.open()),door('recipe','Templates',HUE.teal,()=>plan.templates()),door('barbell','Exercises',HUE.violet,()=>plan.pick(id=>history.exercise(id),{title:'Exercises'})),
    door('body','Body',HUE.pink,()=>body.open()),door('star','Friends',HUE.orange,standings),door('settings','Profile',HUE.blue,profile)));
  let state=loading?'Updating…':problem;if(store.waiting()>0&&!loading&&!problem)state=plural(store.waiting(),'change')+' waiting to sync';
  if(state)parts.push(el('p',{class:'sync-state'+(problem?' warn':''),text:state,attrs:{role:'status'}}));
  root.replaceChildren(...parts.filter(Boolean));
}
function conflictBanner(c){const b=el('button',{type:'button',class:'banner warn'},icon('alert'),el('span',{class:'grow'},el('strong',{text:'A '+c.kind+' edit needs a decision'}),el('small',{text:'Your server has a newer version.'})));
  b.onclick=async()=>{const keep=await confirmDialog('Which version?','This '+c.kind+' changed somewhere else while you edited it here. Keep your edit, or use the server version.','Keep mine','Use server');if(keep===null)return;
    try{await store.resolve(c.mutation_id,keep);refresh()}catch{toast('Connect to your server to decide this.')}};return b}
/** Online or Offline, like Voice's connection chip. Tapping opens the coach. */
function coachChip(){const on=!!overview().trainer?.available;const b=el('button',{type:'button',class:'chip-status',attrs:{'data-on':String(on)}},el('span',{class:'dot'}),on?'Coach online':'Coach offline');b.onclick=()=>nav.coach({},null);return b}
function door(name,text,hue,run){const face=el('span',{class:'door-face'},icon(name));face.style.background=alpha(hue,.17);face.style.color=cssColor(hue);const b=el('button',{type:'button',class:'door'},face,el('span',{text}));b.onclick=run;return b}
function setupBanner(){const b=el('button',{type:'button',class:'banner info'},icon('sparkle'),el('span',{class:'grow'},el('strong',{text:'Finish setting up'}),el('small',{text:'A few details, then your coach plans your first sprint.'})));b.onclick=()=>nav.setup();return b}
function hero(...kids){return el('section',{class:'hero'},...kids)}
function glass(name,text,run){return iconButton(name,text,run,'glass')}
function resume(d){return hero(el('p',{class:'hero-kicker',text:'Workout in progress'}),el('h2',{class:'hero-title',text:d.name}),button('Resume workout','btn on-hero wide',()=>live.open(d)))}

/** The next workout, with the rest of the cycle one tap away: picking another swaps today, and Start follows the pick. */
function next(){
  const n=store.next(),tools=el('div',{class:'hero-tools'});const h=hero();
  if(!n){const first=!store.rows('sprint').length;h.append(el('h2',{class:'hero-title',text:first?'Plan your first sprint':'No workout planned'}),el('p',{class:'hero-note',text:'Your coach proposes it; nothing changes until you approve.'}));
    tools.append(button(el('span',{},icon('sparkle'),'Plan with your coach'),'btn on-hero grow',()=>nav.coach({},null,first?FIRST_SPRINT:'Plan my next sprint from my progress and goals, and name it.')))}
  else{
    const planned=n.template_id,sid=n.sprint?.id||null,cycle=n.sprint?.data.cycle||[],order=[planned];const at=Math.max(0,cycle.indexOf(planned));
    for(let i=0;i<cycle.length;i++){const t=cycle[(i+at)%cycle.length];if(!order.includes(t)&&store.data('template',t))order.push(t)}
    const id=order.includes(chosen)?chosen:planned,t=store.data('template',id),was=store.data('template',planned),name=t?.name||'Session',plannedName=was?.name||'Session';
    const when=n.starts_at?new Date(n.starts_at):null;
    h.append(el('p',{class:'hero-kicker',text:'Workout '+n.index+(n.total?' of '+n.total:'')+(when?' · '+dayWord(when)+' '+when.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}):'')}),
      el('h2',{class:'hero-title',text:name}),plan.summary(t)?el('p',{class:'hero-note',text:plan.summary(t)}):null);
    if(order.length>1)h.append(picker(order,id));
    h.append(brief());
    tools.append(button('Start','btn on-hero grow',()=>{chosen=null;begin(name,id,sid,n.date,id===planned?null:plan.change('swap_day','Swapped '+plannedName+' for '+name,n.date),false,n.scheduled_session_id)}));
  }
  tools.append(glass('plus','New empty workout',()=>begin('Workout',null,null,null,null)),glass('recipe','Start from a template',()=>plan.templates()));
  if(n)tools.append(glass('more',"Change today's workout",()=>plan.changeToday(n)));
  h.append(tools);return h;
}
const dayWord=d=>{const t=new Date();const diff=Math.round((new Date(d.getFullYear(),d.getMonth(),d.getDate())-new Date(t.getFullYear(),t.getMonth(),t.getDate()))/86400000);return diff===0?'today':diff===1?'tomorrow':d.toLocaleDateString(undefined,{weekday:'short',day:'numeric',month:'short'})};
/** The cycle as equal buttons that always fit the card; "A - Chest" shows its short part, and the title has the rest. */
function picker(order,current){return el('div',{class:'cycle',attrs:{role:'radiogroup','aria-label':'Choose today’s session'}},...order.map(id=>{const name=store.data('template',id)?.name||'Session',on=id===current;
  const b=el('button',{type:'button',class:'cycle-btn'+(on?' on':''),text:name.split(/\s+[-–—:]\s+/)[0],attrs:{role:'radio','aria-checked':String(on),'aria-label':name}});b.onclick=()=>{chosen=id;haptic();render()};return b}))}
/** The coach's latest brief, or plainly where it stands. Reading it never runs the model. */
function brief(){const b=overview().next_session_brief;if(!b)return null;const has=!!b.text,off=!has&&!autoBriefs();
  const box=el('button',{type:'button',class:'hero-brief'},icon('sparkle'),el('span',{text:has?b.text:off?'Automatic briefs are off.':history.briefState(b.status)}));box.onclick=()=>off?profile():nav.coach({},null);return box}
export function begin(name,template,sprint,date,changed,shorter,slot){
  const d=live.fromTemplate(name,template,sprint,date,slot);if(changed)d.changes.push(changed);
  if(shorter&&d.exercises.length>1)d.exercises.length=Math.max(1,Math.ceil(d.exercises.length/2));
  store.saveDraft(d);live.open(d);render();
}

function tileCard(title,run,...kids){const b=el('button',{type:'button',class:'tile-card'},el('span',{class:'tile-label',text:title}),...kids);b.onclick=run;return b}
function progress(f){return plan.progressBar(f)}
function sprintTile(){
  const s=store.sprint();if(!s)return tileCard('Sprint',()=>history.open('sprints'),el('strong',{class:'tile-value small',text:'Not started'}),el('small',{text:'Set one up with your coach'}));
  const d=s.data,total=d.target_sessions||(d.scheduled||[]).length||0;let done=(overview().sprints||[]).find(x=>x.id===s.id)?.completed||0;if((d.cycle||[]).length)done=store.sprintCompleted(s.id);
  const left=Math.round((Date.parse(d.end+'T00:00:00Z')-Date.parse(store.today()+'T00:00:00Z'))/86400000);
  return tileCard('Sprint',()=>plan.sprint(s.id),el('strong',{class:'tile-value',text:done+' of '+total}),progress(total?done/total:0),el('small',{text:d.name}),left>=0?el('small',{text:plural(left,'day')+' left'}):null);
}
/** The crest fills the tile with the rank beneath it; the Ranks page has the detail. */
function rankTile(o){const ranked=o.aggregate_score!=null,t=tierOf(o.aggregate_score||0),name=ranked?tierLabel(o.aggregate_score):'Unranked';
  const n=el('strong',{class:'rank-tile-name',text:name});if(ranked)n.style.color=tierColor(t);
  const b=el('button',{type:'button',class:'tile-card rank-tile',attrs:{'aria-label':'Overall rank: '+name}},crest(t,!ranked,72),n);b.onclick=ranks;return b}
function weightTile(o){const bw=o.bodyweight||{},latest=bw.latest,stale=!!bw.stale,average=latest&&latest.average_7d!=null;
  const value=!latest||stale?'Log weight':units.load(average?latest.average_7d:latest.kg),note=!latest?'3 days makes an average':stale?'History ends '+latest.date:average?'7-day average':'Latest reading';
  const daily=bw.daily||[];const line=daily.length>2&&!stale?spark(daily.slice(-30).map(p=>p.average_7d??p.kg),HUE.pink):null;
  return tileCard('Weight',()=>body.open(),el('strong',{class:'tile-value',text:value}),el('small',{text:note}),line)}
function runTile(o){const r=o.running,best=r?.best_working;
  if(!best)return tileCard('Running',running,el('strong',{class:'tile-value small',text:'No working run'}),el('small',{text:"Warm-ups don't count here"}));
  const runs=r.recent_working||[];return tileCard('Running',running,el('strong',{class:'tile-value',text:units.pace(best.pace_seconds_per_km)}),el('small',{text:'Best in 28 days'}),runs.length>1?spark(runs.map(x=>x.speed_kmh),HUE.orange):null)}

/** The plain end-of-workout summary. A rank-up gets one short crest reveal; the brief lands here as soon as it's written. */
export function finished(id,w,before,used){
  const p=page(w.name,{cls:'end'});const reveal=el('div',{class:'reveal'}),achieved=el('div',{class:'stack'}),briefBox=el('div'),note=el('p',{class:'hint',text:'Counting your session…'}),changes=el('div',{class:'stack'});
  briefBox.append(history.workoutBrief(id,false));
  p.body.append(reveal,history.sessionStats(w),achieved,briefBox,note,changes);
  const template=w.template_id?store.data('template',w.template_id):null;
  if(template&&used&&plan.differs(template,used))p.body.append(row('Update the template?','This session differed from the plan.',()=>plan.saveStructure(w.template_id,template,used)));
  p.body.append(button('Done','btn primary wide',()=>p.close()));
  p.onclose=()=>render();
  (async()=>{const m=await store.sync();if(p.closed)return;render();
    if(m){note.textContent="Saved on this device. Ranks update when you're back online.";return}
    note.remove();diff(before,overview(),changes);achieve(id,w,achieved,reveal);poll(0)})();
  async function poll(tries){
    if(p.closed)return;const b=(overview().workout_briefs||{})[id];briefBox.replaceChildren(history.workoutBrief(id,false));
    if(b?.state==='ready'){briefBox.firstChild.classList.add('arrive');return}
    if(b?.state==='writing'||tries<3){if(tries<80)setTimeout(async()=>{if(p.closed)return;await store.sync();poll(tries+1)},6000)}
  }
}
function diff(before,after,out){const old=new Map((before.ranks||[]).map(r=>[r.exercise_id,r.score]));
  for(const r of after.ranks||[]){const prior=old.get(r.exercise_id);if(prior==null||prior===r.score)continue;out.append(pair(r.name,prior+' → '+r.score,r.score>prior?'up':''))}
  if(before.aggregate_score!=null&&after.aggregate_score!=null&&before.aggregate_score!==after.aggregate_score)out.append(pair('Overall',before.aggregate_score+' → '+after.aggregate_score,'up'))}
/** The reward: a crest for the biggest rank step, each new record, and a plain reason when a lift stayed unranked. */
function achieve(id,w,out,reveal){
  const won=history.workoutWins(id);if(won)out.append(won);
  let top=null;for(const x of (overview().workout_wins||{})[id]||[]){if(x.kind==='record')continue;if(!top||x.kind==='overall'||(x.score>top.score&&top.kind!=='overall'))top=x}
  if(top){const t=tierIndex(top.tier),c=crest(t,false,130),title=el('strong',{class:'reveal-title',text:top.tier});title.style.color=tierColor(t);
    reveal.append(el('p',{class:'hint',text:(top.kind==='overall'?'Overall':top.name.replace(' (Barbell)',''))+' rank up'}),c,title);haptic(30);if(!reduced())c.classList.add('pop')}
  const trained=new Set((w.sets||[]).filter(s=>s.kind!=='warmup').map(s=>s.exercise_id));
  for(const r of overview().lift_ranks||[])if(r.status==='needs_hard_set'&&trained.has(r.exercise_id))out.append(el('p',{class:'hint',text:r.exercise_name.replace(' (Barbell)','')+' ranks from a set at 2 reps in reserve or fewer.'}));
}

/** Overall on the ridge, then a crest per main lift with why it's unranked, then muscles and the personal body rank. */
export function ranks(){
  const o=overview(),p=page('Ranks'),ranked=o.aggregate_score!=null,score=o.aggregate_score||0;
  p.body.append(el('div',{class:'ridge-card'},ridge(ranked?tierOf(score):-1),el('div',{class:'ridge-label'},el('small',{text:'Overall rank'}),el('strong',{text:ranked?tierLabel(score):'Unranked'}))));
  const lifts=card(el('p',{class:'label',text:'Main lifts'}));const list=o.lift_ranks||[];
  if(!list.length)lifts.append(el('p',{class:'hint',text:'Ranks appear once your history has synced.'}));for(const r of list)lifts.append(lift(r));p.body.append(lifts);
  p.body.append(el('div',{class:'pair-cards'},card(el('p',{class:'label',text:'Muscles'}),bodyMap(o.muscle_scores||{})),bodyRank(o)),
    row('How ranks are worked out','Sources, method and limits',()=>method(o)));
}
function lift(r){const ranked=r.status==='ranked',t=ranked?tierIndex(r.tier):2,name=(r.exercise_name||r.name||'').replace(/ \(barbell\)/i,'');
  const why={no_recent_set:'No set in the last 6 months',needs_hard_set:'Needs a set with 2 or fewer reps in reserve',needs_bodyweight:'Log your weight to rank this',needs_profile:'Add your details in Profile'}[r.status]||'Not ranked yet';
  const best=r.historical_best;const words=el('span',{class:'grow'},el('strong',{text:name}));
  if(ranked){words.append(progress(r.progress||0));if(r.next_tier)words.append(el('small',{text:history.nextStep(r)}))}else words.append(el('small',{text:why}));
  if(best)words.append(el('small',{text:'All-time best '+(best.estimated_reps!=null?(best.weight_kg>0?units.load(best.weight_kg)+' × '+best.reps:best.reps+' reps'):units.load(best.weight_kg)+' × '+best.reps)}));
  const tier=ranked?el('strong',{class:'lift-tier',text:r.tier}):null;if(tier)tier.style.color=tierColor(t);
  const b=el('button',{type:'button',class:'lift-row'},crest(t,!ranked,36),words,tier);b.onclick=()=>{if(r.exercise_id)history.exercise(r.exercise_id)};return b}
function bodyRank(o){const r=o.body_rank||{},m=o.body_metrics||{},scored=['within_goal','outside_goal'].includes(r.status),on=r.status==='within_goal';
  const c=el('button',{type:'button',class:'card body-rank'},el('p',{class:'label',text:'Body rank'}));
  if(scored)c.append(el('strong',{class:on?'good':'warn',text:on?'On target':'Outside your goal'}),el('small',{text:'Your own goal, not a health measure.'}));
  else c.append(el('small',{text:r.status==='stale'?'Log a new weight. Your last reading is over 30 days old.':'Set a goal weight in Profile, then log your weight.'}));
  if(m.bodyweight_kg!=null)c.append(pair('Weight',units.load(m.bodyweight_kg)));c.onclick=profile;return c}
function method(o){const p=page('How ranks are worked out'),m=o.ranking_method;
  if(!m){p.body.append(el('p',{class:'hint',text:'Available once your history has synced.'}));return}
  p.body.append(el('p',{text:m.method}),el('p',{text:'Compared with: '+m.cohort}),el('p',{class:'hint',text:m.limitations}),el('p',{class:'hint small',text:'Version '+m.version+'. Current rank uses the last 6 months. Older bests stay separate.'}),o.body_metrics?.method?el('p',{class:'hint small',text:o.body_metrics.method}):null)}

/** Working runs show capability, warm-ups don't, and a projection is never presented as something you ran. */
export function running(){
  const p=page('Running'),r=overview().running;if(!r){p.body.append(el('p',{class:'hint',text:'Your running stats appear after your next sync.'}));return}
  const rank=r.rank,ranked=rank?.status==='ranked',t=ranked?tierIndex(rank.tier):0;
  const tierName=el('strong',{class:'rank-name',text:ranked?rank.tier:'Unranked'});if(ranked)tierName.style.color=tierColor(t);
  p.body.append(el('div',{class:'card run-rank'},crest(t,!ranked,58),el('div',{class:'grow'},el('small',{class:'label',text:'Running rank'}),tierName,
    ranked?el('p',{class:'percentile',text:'Faster than about '+rank.percentile+'% of runners'}):el('small',{text:rank?.status==='needs_profile'?'Add your sex in Profile':'Needs a flat working run of 1 km or more'}),
    ranked&&rank.next_1_5mi_seconds!=null?el('small',{text:'1.5 miles in '+clock(rank.next_1_5mi_seconds)+' for '+rank.next_tier}):null)),
    ranked?el('p',{class:'hint small',text:"Among Running Level's logged runners, by your sex, from your best flat working run in 6 months. Not the general population."}):null);
  const bench=r.benchmark_1_5mi,seen=bench?.observed,guess=bench?.projected;
  p.body.append(hero(el('p',{class:'hero-kicker',text:'1.5 miles'}),seen?el('h2',{class:'hero-title huge',text:clock(seen.seconds)}):el('h2',{class:'hero-title',text:'Not run yet'}),seen?el('p',{class:'hero-note',text:'Ran it · '+seen.date}):null,
    guess?el('p',{class:'hero-note',text:'Projected '+clock(guess.seconds)+' from your best working run. An estimate, not a result.'}):null));
  const best=r.best_working;if(best)p.body.append(card(el('h3',{class:'card-title',text:'Best working run, last 28 days'}),pair('Distance',units.distance(best.distance_m)),pair('Time',clock(best.seconds)),pair('Pace',units.pace(best.pace_seconds_per_km)),pair('Speed',units.speed(best.speed_kmh))));
  const ever=r.historical_best_working;if(ever)p.body.append(card(el('h3',{class:'card-title',text:'All-time best working run'}),pair(units.distance(ever.distance_m)+' in '+clock(ever.seconds),units.pace(ever.pace_seconds_per_km))));
  const runs=r.recent_working||[];if(runs.length>1){const c=chart({height:180,gap:45,format:v=>num(v)+' '+units.speedLabel(),label:'Running speed'});c.line(runs.map(x=>[epochDay(x.date),units.speedValue(x.speed_kmh)]),HUE.orange,2,'Speed');p.body.append(card(el('h3',{class:'card-title',text:'Speed'}),c.framed()))}
  p.body.append(el('p',{class:'hint',text:'Runs are warm-ups by default. Mark a run as a working set to count it here.'}));
}

/** Details that ranks and the coach rely on, sharing, briefs and private reminders. */
export function profile(){
  const p=page('Profile'),base=structuredClone(store.athlete());
  const field=(lbl,key,type='text',mode)=>{const i=el('input',{class:'field',type,value:base[key]??'',attrs:{'aria-label':lbl,inputmode:mode||''}});return [el('label',{class:'field-label'},el('span',{text:lbl}),i),i]};
  const [aL,ageI]=field('Age','age_years','number','numeric'),[hL,h]=field('Height (cm)','height_cm','text','decimal'),[bL,b]=field('Birth date','birth_date','date');
  const sex=el('select',{class:'field',attrs:{'aria-label':'Sex'}},...[['unspecified','Prefer not to say'],['female','Female'],['male','Male']].map(([v,t])=>el('option',{value:v,text:t,selected:base.sex===v})));
  const unitsSel=el('select',{class:'field',attrs:{'aria-label':'Units'}},el('option',{value:'metric',text:'Metric (kg, km)',selected:base.units!=='imperial'}),el('option',{value:'imperial',text:'Imperial (lb, mi)',selected:base.units==='imperial'}));
  const goal=k=>{const i=el('input',{class:'field',value:base[k]!=null?units.loadNumber(base[k]):'',attrs:{'aria-label':(k.includes('min')?'Goal weight from':'Goal weight to')+' in '+units.loadLabel(),inputmode:'decimal'}});return i};
  const gMin=goal('goal_weight_min_kg'),gMax=goal('goal_weight_max_kg');
  const goals=el('textarea',{class:'field',rows:3,placeholder:'Goals, one per line',value:(base.goals||[]).join('\n'),attrs:{'aria-label':'Goals'}});
  const auto=toggle('Coach briefs after workouts','Two short sentences on how it went and what to do next.',!!base.auto_coach_briefs);
  p.body.append(card(el('h3',{class:'card-title',text:'You'}),el('label',{class:'field-label'},el('span',{text:'Sex, for ranks'}),sex),aL,hL,bL,el('label',{class:'field-label'},el('span',{text:'Units'}),unitsSel),
      el('label',{class:'field-label'},el('span',{text:'Goal weight ('+units.loadLabel()+')'}),el('div',{class:'row2'},gMin,gMax)),goals),
    card(auto.el),
    button('Save profile','btn primary wide',()=>{
      const n=v=>{const x=Number(String(v).replace(',','.'));return v===''||!Number.isFinite(x)?null:x};const d={...base,sex:sex.value,units:unitsSel.value,auto_coach_briefs:auto.on()};
      const set=(k,v)=>{if(v==null)delete d[k];else d[k]=v};set('height_cm',n(h.value));const y=n(ageI.value);if(y!=null&&(!Number.isInteger(y)||y<13||y>100)){toast('Enter your age in whole years');return}set('age_years',y);set('birth_date',b.value||null);
      const lo=n(gMin.value),hi=n(gMax.value);set('goal_weight_min_kg',lo==null?null:Math.round(units.loadIn(lo)*10)/10);set('goal_weight_max_kg',hi==null?null:Math.round(units.loadIn(hi)*10)/10);
      if(d.goal_weight_min_kg&&d.goal_weight_max_kg&&d.goal_weight_max_kg<d.goal_weight_min_kg){toast('The goal range is reversed');return}
      d.goals=goals.value.split('\n').map(x=>x.trim()).filter(Boolean);store.putEntity('athlete','self',d);toast('Saved');refresh()}));
  p.body.append(sharing(),reminders());
  p.body.append(card(el('h3',{class:'card-title',text:'This device'}),el('p',{class:'hint',text:'Signed in as '+(me?.name||'you')+'. Your workouts are kept on this device until they sync.'}),
    row('Export my data','A JSON copy of everything you have logged',exportData)));
}
function toggle(title,note,on){const input=el('input',{type:'checkbox',class:'switch',checked:on,attrs:{role:'switch'}});
  return {el:el('label',{class:'toggle'},el('span',{class:'grow'},el('strong',{text:title}),note?el('small',{text:note}):null),input),on:()=>input.checked,input}}
/** What friends can see, and whether their rank-ups notify you. Each switch saves on its own. */
function sharing(){
  const c=card(el('h3',{class:'card-title',text:'Friends'}));
  const status=el('p',{class:'hint small',attrs:{role:'status'}});
  const device=el('div',{class:'stack',hidden:!me?.rank_alerts},
    button('Enable notifications on this device','btn quiet wide',()=>enablePush(status)),status);
  pushStatus(status).catch(()=>{status.textContent='Connect to check notification settings.'});
  const item=(key,title,note,done)=>{const t=toggle(title,note,!!me?.[key]);t.input.onchange=async()=>{try{me={...me,...await api('me',{method:'PATCH',body:{[key]:t.input.checked}})};done?.(t.input.checked)}catch{t.input.checked=!t.input.checked;toast('Connect to change this.')}};return t.el};
  c.append(item('share_progress','Share my progress','Friends can open your sprint, workout count, ranks and lift and volume trends. Notes, photos and coach chats stay private.',on=>toast(on?'Sharing your progress':'Progress is private')),
    item('share_schedule','Share my workout schedule','Friends see your planned sessions and whether you made them. Needs progress sharing.'),
    item('rank_alerts','Competitive notifications','A notification when a friend ranks up.',on=>{device.hidden=!on}),device);
  return c;
}
/** Private reminders before scheduled sessions: push on this device, an opt-in blunt tone, and an optional photo of your own. */
function reminders(){
  const c=card(el('h3',{class:'card-title',text:'Sprints and reminders'}));
  const body_=el('div',{class:'stack'},el('p',{class:'hint',text:'Loading…'}));c.append(body_);
  (async()=>{await settings.load();let s=settings.get();
    if(!('enabled' in s)){body_.replaceChildren(el('p',{class:'hint',text:'Connect to change these.'}));return}
    const save=async patch=>{const ok=await settings.save(patch);s=settings.get();if(!ok)toast("Couldn't save. Check your connection.");return ok};
    const timed=toggle('Scheduled sprints','Dated sessions with start times. Off keeps a repeating cycle; existing times are kept.',!!s.scheduled_sprints);
    const en=toggle('Session reminders','A notification 30 minutes before each scheduled session.',!!s.enabled),roast=toggle('Diss mode','Crude, profane nudges when you skip, and blunt briefs when you fall short of the plan.',!!s.roast);
    timed.input.onchange=async()=>{if(!await save({scheduled_sprints:timed.input.checked}))timed.input.checked=!timed.input.checked};
    en.input.onchange=async()=>{if(!await save({enabled:en.input.checked}))en.input.checked=!en.input.checked;else if(en.input.checked)await enablePush(status)};
    roast.input.onchange=async()=>{if(roast.input.checked&&!await confirmDialog('Turn on Diss mode?','Reminders and some briefs may use crude, profane language. You can turn it off any time.','Turn on','Cancel')){roast.input.checked=false;return}if(!await save({roast:roast.input.checked}))roast.input.checked=!roast.input.checked};
    const photos=toggle('Reminder photos','Your Diss mode reminders may show one of the private photos you choose.',!!s.photos_enabled);
    const pickRow=()=>row('Choose photos',(s.photo_ids||[]).length?plural(s.photo_ids.length,'photo')+' chosen':'None chosen yet',async()=>{const ids=await body.choosePhotos(s.photo_ids||[]);if(ids&&await save({photo_ids:ids})){toast('Photos saved');sync()}});
    const extra=el('div',{class:'stack nested'});
    const sync=()=>{extra.hidden=!roast.input.checked;extra.replaceChildren(...[photos.el,photos.input.checked?pickRow():null].filter(Boolean))};
    photos.input.onchange=async()=>{if(!await save({photos_enabled:photos.input.checked}))photos.input.checked=!photos.input.checked;sync()};
    roast.input.addEventListener('change',()=>setTimeout(sync,0));sync();
    const status=el('p',{class:'hint small',attrs:{role:'status'}});pushStatus(status);
    body_.replaceChildren(timed.el,roast.el,extra,en.el,button('Turn on notifications on this device','btn quiet wide',()=>enablePush(status)),status)})();
  return c;
}
const standalone=()=>matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;
const ios=()=>/iP(hone|ad|od)/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
async function pushStatus(out){
  if(!('serviceWorker' in navigator)||!('PushManager' in window)){out.textContent=ios()&&!standalone()?'On iPhone, add Train to your Home Screen and open it from there to get reminders.':'This browser cannot show reminders.';return}
  if(Notification.permission==='denied'){out.textContent='Notifications are blocked for Train in your settings.';return}
  const sub=await (await navigator.serviceWorker.ready).pushManager.getSubscription();out.textContent=sub?'Notifications are on for this device.':'Notifications are off for this device.';
}
/** Must run from a tap: the browser asks for permission, then the subscription goes to the server. */
async function enablePush(out){
  if(ios()&&!standalone()){toast('Add Train to your Home Screen first, then open it from there.');out.textContent='On iPhone, reminders work from the Home Screen app.';return}
  if(!('PushManager' in window)){toast('This browser cannot show reminders.');return}
  try{const permission=await Notification.requestPermission();if(permission!=='granted'){out.textContent='Notifications were not allowed.';return}
    const {public_key}=await api('push/key');const reg=await navigator.serviceWorker.ready;
    let sub=await reg.pushManager.getSubscription();if(!sub)sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64(public_key)});
    await api('push/subscriptions',{method:'PUT',body:sub.toJSON()});out.textContent='Notifications are on for this device.';toast('Notifications on')}
  catch(e){out.textContent=e instanceof ApiError&&e.status===503?'Notifications are not set up on your server yet.':"Couldn't turn on notifications."}
}
export async function disablePush(){try{const sub=await (await navigator.serviceWorker.ready).pushManager.getSubscription();if(!sub)return;await api('push/subscriptions',{method:'DELETE',body:sub.toJSON()}).catch(()=>{});await sub.unsubscribe()}catch{}}
const b64=s=>{const p='='.repeat((4-s.length%4)%4),raw=atob((s+p).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from(raw,c=>c.charCodeAt(0))};
async function exportData(){try{const data=await api('export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=el('a',{href:url,download:'train-export.json'});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2000)}catch{toast('Connect to export.')}}

/** A reminder opened from a notification; the photo shows here even where the system hid it. */
export async function reminder(id){
  const p=page('Reminder');p.body.append(el('p',{class:'hint',text:'Loading…'}));
  try{const r=await api('reminders/history/'+encodeURIComponent(id));p.body.replaceChildren(el('h2',{class:'reminder-title',text:r.title}),el('p',{class:'reminder-body',text:r.body}),
      r.image?el('img',{class:'reminder-image',src:r.image,alt:'Your reminder photo'}):null,button('Open Train','btn primary wide',()=>p.close()))}
  catch{p.body.replaceChildren(el('p',{class:'hint',text:"Couldn't load this reminder."}))}
}

/** Friends: everyone in Train with their lifting and running rank and current sprint. A friend opens only when they share. */
export async function standings(){
  const p=page('Friends');const list=el('div',{class:'stack'},el('p',{class:'hint',text:'Loading…'}));p.body.append(list);
  try{const {items}=await api('standings');const order=[...items].sort((a,b)=>(b.lifting_score??-1)-(a.lifting_score??-1));
    list.replaceChildren(...order.map((m,i)=>{const mine=m.id===me?.id,lt=tierOf(m.lifting_score||0),rt=tierOf(m.running_score||0);
      const lift=el('span',{class:'stand-rank'},crest(lt,m.lifting_score==null,30),el('small',{text:m.lifting_score==null?'Unranked':tierLabel(m.lifting_score)}));
      const run=el('span',{class:'stand-rank'},crest(rt,m.running_score==null,30),el('small',{text:m.running_score==null?'Unranked':tierLabel(m.running_score)}));
      const s=m.current_sprint,open=mine||m.share_progress;
      const note=s?s.name+' · '+(s.completed??0)+(s.target_sessions?'/'+s.target_sessions:''):open?'No sprint running':'Keeps progress private';
      const words=el('span',{class:'grow'},el('strong',{text:m.name+(mine?' (you)':'')}),el('small',{text:note}));
      if(s?.target_sessions)words.append(plan.progressBar((s.completed||0)/s.target_sessions));
      const b=el(open?'button':'div',{class:'standing'+(mine?' mine':''),...(open?{type:'button'}:{})},el('span',{class:'place',text:String(i+1)}),words,lift,run);
      if(open)b.onclick=()=>friend(m.id,'sprint',m.name);return b}),el('p',{class:'hint small',text:'Ranked by lifting. Turn on sharing in Profile so friends can open your sprint and ranks.'}))}
  catch{list.replaceChildren(el('p',{class:'hint',text:'Connect to see your friends.'}))}
}
const STATUS={completed:['Done','var(--success)'],missed:['Missed','var(--danger)'],skipped:['Skipped','var(--muted)'],active:['Training now','var(--accent)'],upcoming:['Upcoming','var(--muted)']};
/** One friend, in two tabs: their sprint and schedule, and their ranks. A rank-up notification opens Ranks directly. */
export async function friend(id,tab='sprint',name){
  const p=page(name||'Friend');const tabs=el('div',{class:'segmented',attrs:{role:'tablist'}}),body=el('div',{class:'stack'},el('p',{class:'hint',text:'Loading…'}));p.body.append(tabs,body);
  let d;try{d=await api('profiles/'+encodeURIComponent(id))}
  catch(e){tabs.remove();body.replaceChildren(el('p',{class:'hint',text:e instanceof ApiError&&e.status===404?'This friend keeps their progress private.':'Connect to see this.'}));return}
  p.heading.textContent=d.name;
  const show=key=>{tab=key;tabs.replaceChildren(...[['sprint','Sprint'],['ranks','Ranks']].map(([k,t])=>{const b=el('button',{type:'button',class:'seg'+(k===tab?' on':''),text:t,attrs:{role:'tab','aria-selected':String(k===tab)}});b.onclick=()=>show(k);return b}));
    body.replaceChildren(...(tab==='ranks'?friendRanks(d):friendSprint(d)))};
  show(tab);
}
function friendSprint(d){
  const out=[el('div',{class:'stats'},stat(String(d.completed_workouts??0),'workouts'),stat(String((d.sprints||[]).length),'sprints'))],s=d.current_sprint;
  if(s)out.push(card(el('p',{class:'label',text:'Current sprint'}),el('h3',{class:'card-title big',text:s.name}),el('p',{class:'strong-line',text:(s.completed??0)+(s.target_sessions?' of '+s.target_sessions:'')+' workouts'}),s.target_sessions?plan.progressBar((s.completed||0)/s.target_sessions):null));
  else out.push(el('p',{class:'hint',text:'No sprint running.'}));
  const sched=(d.schedule||[]).slice().sort((a,b)=>String(a.starts_at||a.date).localeCompare(String(b.starts_at||b.date)));
  if(sched.length){const c=card(el('p',{class:'label',text:'Schedule'}));for(const x of sched){const [word,color]=STATUS[x.status]||[x.status,'var(--muted)'];const at=x.starts_at?new Date(x.starts_at):new Date(x.date+'T12:00:00');
      const tag=el('strong',{class:'sched-status',text:word});tag.style.color=color;
      c.append(el('div',{class:'sched-row'},el('span',{class:'grow'},el('strong',{text:x.name||'Session'}),el('small',{text:at.toLocaleDateString(undefined,{weekday:'short',day:'numeric',month:'short'})+(x.starts_at?' · '+at.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}):'')})),tag))}
    out.push(c)}
  const vol=d.progress?.volume||[];if(vol.length>1){const c=chart({height:170,gap:21,format:v=>Math.round(v).toLocaleString(),label:'Volume per session'});c.line(vol.map(x=>[epochDay(x.date),units.loadValue(x.value)]),'var(--aurora-3)',2,'Volume');out.push(card(el('h3',{class:'card-title',text:'Volume per session'}),c.framed()))}
  const past=(d.sprints||[]).slice().reverse().filter(x=>x.status!=='active');
  if(past.length)out.push(label('Past sprints'),...past.map(x=>card(el('strong',{text:x.name}),el('small',{class:'hint',text:x.phase+' · '+x.start+' to '+x.end}),pair('Workouts',x.completed+(x.target_sessions?' of '+x.target_sessions:'')))));
  return out;
}
function friendRanks(d){
  const r=d.ranks||{},score=r.lifting_score,ranked=score!=null,out=[];
  out.push(el('div',{class:'ridge-card'},ridge(ranked?tierOf(score):-1),el('div',{class:'ridge-label'},el('small',{text:'Overall rank'}),el('strong',{text:ranked?tierLabel(score):'Unranked'}))));
  const run=r.running,runTier=run?.tier||(run?.score!=null?tierLabel(run.score):null);
  if(run){const t=runTier?tierIndex(runTier):0,n=el('strong',{class:'rank-name',text:runTier||'Unranked'});if(runTier)n.style.color=tierColor(t);
    out.push(el('div',{class:'card run-rank'},crest(t,!runTier,48),el('div',{class:'grow'},el('small',{class:'label',text:'Running'}),n,run.percentile!=null?el('small',{text:'Faster than about '+run.percentile+'% of runners'}):null)))}
  const lifts=card(el('p',{class:'label',text:'Main lifts'}));
  for(const l of r.lifts||[]){const tier=l.tier||(l.score!=null?tierLabel(l.score):null),t=tier?tierIndex(tier):2,name=(l.exercise_name||l.name||'').replace(/ \(barbell\)/i,'');
    const tag=tier?el('strong',{class:'lift-tier',text:tier}):null;if(tag)tag.style.color=tierColor(t);
    lifts.append(el('div',{class:'lift-row'},crest(t,!tier,36),el('span',{class:'grow'},el('strong',{text:name}),l.percentile!=null?el('small',{text:'Stronger than about '+l.percentile+'% of lifters'}):tier?null:el('small',{text:'Not ranked yet'})),tag))}
  if(!(r.lifts||[]).length)lifts.append(el('p',{class:'hint',text:'No ranked lifts yet.'}));out.push(lifts);
  const hues=[HUE.pink,HUE.blue,HUE.green,HUE.amber,HUE.violet,HUE.teal];
  (d.progress?.lifts||[]).filter(l=>l.e1rm_series.length>1).forEach((l,i)=>{const c=chart({height:160,gap:45,format:v=>num(v)+' '+units.loadLabel(),label:l.name+' estimated max'});c.line(l.e1rm_series.map(x=>[epochDay(x.date),units.loadValue(x.value)]),hues[i%hues.length],2,'Estimated');out.push(card(el('h3',{class:'card-title',text:l.name}),c.framed()))});
  return out;
}
