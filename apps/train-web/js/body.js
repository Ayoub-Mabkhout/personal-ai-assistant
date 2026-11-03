// Weight with both averages and the days they rest on, a quick log, and private progress photos. The coach only sees photos the
// owner approves for that one question, and each photo keeps its date and the sprint it was taken in.
import {el,icon,iconButton,button,page,toast,uid,card,label,HUE,alpha,cssColor,haptic,num,choiceDialog,confirmDialog} from './core.js';
import * as store from './store.js';
import * as units from './units.js';
import {api,photoUrl} from './api.js';
import {chart,epochDay} from './chart.js';
import * as sprints from './sprints.js';
import {iso} from './live.js';
import {nav} from './nav.js';

const zone=()=>Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
export function open(){
  const p=page('Body');let state='relaxed';const selected=new Set();
  const paint=()=>{const y=p.body.scrollTop;p.body.replaceChildren(weight(),logger(),photos());p.body.scrollTop=y};
  function weight(){
    const bw=store.overview().bodyweight||{},latest=bw.latest,average=latest&&latest.average_7d!=null,unit=units.loadLabel();
    const c=card(el('strong',{class:'big-number',text:latest?units.load(average?latest.average_7d:latest.kg):'No weight yet'}),
      el('p',{class:'hint'+(bw.stale?' warn':''),text:!latest?'Weigh in the morning, before food.':bw.stale?'History ends '+latest.date:average?'7-day average':'Latest reading'}));
    const daily=bw.daily||[];
    if(daily.length){const dots=daily.map(d=>[epochDay(d.date),units.loadValue(d.kg)]),seven=daily.filter(d=>d.average_7d!=null).map(d=>[epochDay(d.date),units.loadValue(d.average_7d)]),fourteen=daily.filter(d=>d.average_14d!=null).map(d=>[epochDay(d.date),units.loadValue(d.average_14d)]);
      const ch=chart({height:240,gap:7,format:v=>num(v)+' '+unit,label:'Bodyweight'});ch.dots(dots,'var(--weighed)','Weighed').gaps(dots,'var(--stroke-strong)').breaks(fourteen,HUE.teal,1,'14-day').breaks(seven,HUE.pink,3,'7-day');
      c.append(ch.framed(),el('div',{class:'legend'},...[['Weighed','var(--weighed)'],['7-day',HUE.pink],['14-day',HUE.teal]].map(([n,col])=>{const d=el('span',{class:'key-dot'});d.style.background=cssColor(col);return el('span',{},d,n)})))}
    return c;
  }
  /** A stepper starting from the latest reading: tap the arrows or type, then tick. */
  function logger(){
    const latest=store.overview().bodyweight?.latest,step=units.imperial()?.2:.1;let value=Math.round(units.loadValue(latest?.kg||70)/step)*step;
    const field=el('input',{class:'stepper-value',value:num(value),attrs:{'aria-label':'Weight in '+units.loadLabel(),inputmode:'decimal'}});field.oninput=()=>{const n=Number(field.value.replace(',','.'));if(Number.isFinite(n))value=n};
    const bump=d=>{value=Math.max(0,Math.round((value+d)*10)/10);field.value=num(value);haptic(4)};
    const hold=(btn,d)=>{let t=0;const go=()=>{bump(d);t=setTimeout(go,t?60:380)};btn.addEventListener('pointerdown',()=>{t=0;go()});['pointerup','pointerleave','pointercancel'].forEach(e=>btn.addEventListener(e,()=>clearTimeout(t)));btn.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')bump(d)})};
    const minus=iconButton('minus','Less'),plus=iconButton('plus','More');hold(minus,-step);hold(plus,step);
    const save=iconButton('check','Log weight',()=>{if(!(value>0)){toast('Enter your weight');return}store.putEntity('measurement',uid(),{measured_at:iso(Date.now(),zone()),kind:'bodyweight',value:Math.round(units.loadIn(value)*100)/100,unit:'kg',source:'Train web'});toast('Logged '+units.load(units.loadIn(value)));store.sync().then(paint)},'tonal',HUE.green);
    return el('div',{class:'logger'},minus,el('div',{class:'stepper'},field,el('span',{text:units.loadLabel()})),plus,save);
  }
  function photos(){
    const all=store.rows('photo').filter(r=>r.data.state===state).sort((a,b)=>String(b.data.captured_at).localeCompare(String(a.data.captured_at)));
    const tabs=el('div',{class:'segmented small'},...[['relaxed','Relaxed'],['flexed','Flexed'],['pumped','Pumped']].map(([k,n])=>{const b=el('button',{type:'button',class:'seg'+(state===k?' on':''),text:n});b.onclick=()=>{state=k;selected.clear();paint()};return b}));
    const c=card(el('h3',{class:'card-title',text:'Photos'}),tabs);
    // Newest first, under the sprint each photo belongs to.
    const groups=new Map();for(const r of all){const sid=sprintOf(r.data);if(!groups.has(sid))groups.set(sid,[]);groups.get(sid).push(r)}
    if(!all.length)c.append(el('p',{class:'hint',text:'No '+state+' photos yet.'}));
    for(const [sid,list] of groups){const s=sid&&store.data('sprint',sid),head=el('p',{class:'label'});if(s){const dot=el('span',{class:'key-dot'});dot.style.background=cssColor(sprints.hue(sid));head.append(dot,s.name)}else head.textContent='Outside a sprint';
      c.append(head,el('div',{class:'photo-grid'},...list.map(r=>thumb(r))))}
    const ask=button(selected.size?'Ask about '+selected.size+(selected.size===1?' photo':' photos'):'Choose photos to ask about','btn quiet wide',()=>{if(!selected.size){toast('Tap photos to choose them');return}
      nav.coach({},null,'Estimate my body-fat range from these photos and compare them with earlier ones.',[...selected])});
    if(selected.size)ask.classList.replace('quiet','primary');
    const file=el('input',{type:'file',accept:'image/jpeg,image/png,image/webp',class:'visually-hidden',attrs:{'aria-label':'Choose a photo'}});file.onchange=()=>{if(file.files[0])upload(file.files[0],state).then(paint)};
    c.append(ask,button(el('span',{},icon('plus'),'Add photo'),'btn ghost wide',()=>file.click()),file,el('p',{class:'hint small',text:'Each look by your coach needs your approval. Any estimate is a rough range.'}));
    const est=store.rows('composition').map(r=>r.data).sort((a,b)=>b.assessed_at.localeCompare(a.assessed_at)).slice(0,3);
    if(est.length)c.append(label('Estimates'),...est.map(e=>el('div',{class:'pair'},el('span',{text:new Date(e.assessed_at).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'})}),el('strong',{text:num(e.low_percent)+'–'+num(e.high_percent)+'%'}))));
    return c;
  }
  /** A tap selects with a ring and a tick; a hold opens it nearly full screen. */
  function thumb(r){
    const on=selected.has(r.id),day=new Date(r.data.captured_at);
    const b=el('button',{type:'button',class:'photo'+(on?' on':''),attrs:{'aria-pressed':String(on),'aria-label':'Photo from '+day.toLocaleDateString()+'. Tap to choose, hold to view'}},
      el('img',{src:photoUrl(r.data.blob_id),alt:'',loading:'lazy',decoding:'async'}),el('span',{class:'photo-date',text:day.toLocaleDateString(undefined,{day:'numeric',month:'short',year:'2-digit'})}),el('span',{class:'tick'},icon('check')));
    let t=0,held=false;
    b.addEventListener('pointerdown',()=>{held=false;t=setTimeout(()=>{held=true;haptic(12);viewer(r)},420)});
    ['pointerup','pointerleave','pointercancel'].forEach(e=>b.addEventListener(e,()=>clearTimeout(t)));
    b.addEventListener('contextmenu',e=>e.preventDefault());
    b.onclick=()=>{if(held)return;if(selected.has(r.id))selected.delete(r.id);else if(selected.size>=6){toast('Choose up to six');return}else selected.add(r.id);haptic(6);paint()};
    return b;
  }
  paint();const off=store.onChange(()=>{if(p.closed)off()});
}
/** The sprint the photo was taken in: recorded at upload, or worked out from its date for older photos. */
function sprintOf(d){if(d.sprint_id)return d.sprint_id;const day=d.captured_at.slice(0,10);return sprints.inOrder().find(r=>r.data.start<=day&&day<=(r.data.end||r.data.start))?.id||null}
/** The photo nearly full screen. It stays until a tap, a hold or back closes it. */
export function viewer(r){
  const d=el('dialog',{class:'viewer'},el('img',{src:photoUrl(r.data.blob_id),alt:'Progress photo'}),
    el('p',{class:'viewer-caption',text:new Date(r.data.captured_at).toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'long',year:'numeric'})+' · '+r.data.pose+' · '+r.data.state}));
  const close=()=>{d.close();d.remove()};d.addEventListener('click',close);d.addEventListener('cancel',e=>{e.preventDefault();close()});
  document.body.append(d);d.showModal();
}
/** Large photos are re-encoded to fit the 8 MiB limit; the ID is the SHA-256 of the bytes sent. */
export async function upload(file,state='relaxed'){
  try{
    let blob=file;if(blob.size>7.5*1024*1024||!['image/jpeg','image/png','image/webp'].includes(blob.type))blob=await shrink(file);
    const bytes=await blob.arrayBuffer(),hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(b=>b.toString(16).padStart(2,'0')).join('');
    await api('photos/'+hash,{method:'PUT',body:bytes,raw:true,type:blob.type});
    const pose=['front','side','back','other'][await choiceDialog('Which pose?',['Front','Side','Back','Other'])??0];
    const sid=store.sprint()?.id,captured=file.lastModified&&Date.now()-file.lastModified<400*86400000?file.lastModified:Date.now();
    const id=uid();store.putEntity('photo',id,{captured_at:iso(captured,zone()),blob_id:hash,pose,state,...(sid?{sprint_id:sid}:{})});await store.sync();toast('Photo added');return id;
  }catch(e){toast(e.message==='offline'?'Connect to add photos.':e.message||"Couldn't add that photo");return null}
}
async function shrink(file){
  const bitmap=await createImageBitmap(file,{imageOrientation:'from-image'}),scale=Math.min(1,2048/Math.max(bitmap.width,bitmap.height));
  const c=new OffscreenCanvas(Math.round(bitmap.width*scale),Math.round(bitmap.height*scale));c.getContext('2d').drawImage(bitmap,0,0,c.width,c.height);
  return c.convertToBlob({type:'image/jpeg',quality:.88});
}
/** Choose up to twelve private photos for reminders. Resolves to the chosen IDs, or null when backed out. Uploading alone chooses nothing. */
export function choosePhotos(current=[]){
  return new Promise(resolve=>{
    const chosen=new Set(current);let result=null;
    const done=button('Use these photos','btn primary wide',()=>{result=[...chosen];p.close()});
    const p=page('Reminder photos',{onclose:()=>resolve(result)});
    const grid=el('div',{class:'photo-grid'}),count=el('p',{class:'hint small',attrs:{role:'status'}});
    const paint=()=>{const list=store.rows('photo').sort((a,b)=>String(b.data.captured_at).localeCompare(String(a.data.captured_at)));
      grid.replaceChildren(...list.map(r=>{const on=chosen.has(r.id),b=el('button',{type:'button',class:'photo'+(on?' on':''),attrs:{'aria-pressed':String(on),'aria-label':'Photo from '+new Date(r.data.captured_at).toLocaleDateString()}},
        el('img',{src:photoUrl(r.data.blob_id),alt:'',loading:'lazy'}),el('span',{class:'photo-date',text:new Date(r.data.captured_at).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'2-digit'})}),el('span',{class:'tick'},icon('check')));
        b.onclick=()=>{if(chosen.has(r.id))chosen.delete(r.id);else if(chosen.size>=12){toast('Choose up to twelve');return}else chosen.add(r.id);haptic(6);paint()};return b}));
      if(!list.length)grid.append(el('p',{class:'hint',text:'No photos yet. Upload one below.'}));
      count.textContent=chosen.size?chosen.size+' chosen. One appears per reminder, in turn.':'None chosen.'};
    const file=el('input',{type:'file',accept:'image/jpeg,image/png,image/webp',multiple:true,class:'visually-hidden',attrs:{'aria-label':'Upload photos'}});
    file.onchange=async()=>{for(const f of file.files)await upload(f);file.value='';paint()};
    p.body.append(el('p',{class:'hint',text:'Only you see these. Tap to choose the ones your reminders may show.'}),grid,count,
      button(el('span',{},icon('plus'),'Upload photos'),'btn quiet wide',()=>file.click()),file,done);
    paint();
  });
}
