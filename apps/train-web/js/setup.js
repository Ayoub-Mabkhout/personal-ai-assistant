// First run for a new member, after the name from the join screen: body stats, two opt-ins, then the coach plans the first sprint.
// Everything here can be changed later in Profile. Backing out leaves a clear way back from the dashboard.
import {el,icon,button,page,toast,uid,haptic,confirmDialog} from './core.js';
import * as store from './store.js';
import * as units from './units.js';
import {api} from './api.js';
import * as settings from './settings.js';
import {iso} from './live.js';
import {nav} from './nav.js';
import {choosePhotos} from './body.js';

export const FIRST_SPRINT='Plan my first sprint. Ask me what I need to know about my goals, schedule and equipment, then propose the sprint and any exercises it needs.';
const zone=()=>Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';

export function open(account,done){
  const p=page('Welcome',{cls:'setup'});let step=0;
  const dots=el('div',{class:'steps',attrs:{'aria-hidden':'true'}},el('span'),el('span'),el('span'));
  const body=el('div',{class:'stack'});p.body.append(dots,body);
  const paint=()=>{[...dots.children].forEach((d,i)=>d.classList.toggle('on',i<=step));body.replaceChildren(...[stats,choices,coach][step]());p.body.scrollTop=0;body.querySelector('input,select,button')?.focus({preventScroll:true})};

  /** Age and body stats, in the units the member picks. They feed ranks and the coach. */
  function stats(){
    const a=store.athlete();let imperial=a.units==='imperial';
    const seg=el('div',{class:'segmented'});const unitBtn=(label,on)=>{const b=el('button',{type:'button',class:'seg'+(on===imperial?' on':''),text:label,attrs:{'aria-pressed':String(on===imperial)}});b.onclick=()=>{imperial=on;relabel()};return b};
    const age=el('input',{class:'field',type:'number',min:13,max:100,value:a.age_years??'',attrs:{'aria-label':'Age in years',inputmode:'numeric'}});
    const height=el('input',{class:'field',value:'',attrs:{inputmode:'decimal'}}),weight=el('input',{class:'field',value:'',attrs:{inputmode:'decimal'}});
    const hl=el('span'),wl=el('span');
    const sex=el('select',{class:'field',attrs:{'aria-label':'Sex, used for ranks'}},...[['unspecified','Prefer not to say'],['female','Female'],['male','Male']].map(([v,t])=>el('option',{value:v,text:t,selected:a.sex===v})));
    const fill=()=>{if(a.height_cm)height.value=imperial?Math.round(a.height_cm/2.54):Math.round(a.height_cm);const kg=store.overview().bodyweight?.latest?.kg;if(kg)weight.value=imperial?Math.round(kg/units.LB*10)/10:kg};
    function relabel(){const h=num(height.value),w=num(weight.value);seg.replaceChildren(unitBtn('Metric',false),unitBtn('Imperial',true));
      if(h!=null)height.value=String(Math.round(imperial?h/2.54:h*2.54));if(w!=null)weight.value=String(Math.round((imperial?w/units.LB:w*units.LB)*10)/10);
      hl.textContent='Height ('+(imperial?'in':'cm')+')';wl.textContent='Weight ('+(imperial?'lb':'kg')+')';height.setAttribute('aria-label',hl.textContent);weight.setAttribute('aria-label',wl.textContent)}
    seg.replaceChildren(unitBtn('Metric',false),unitBtn('Imperial',true));hl.textContent='Height ('+(imperial?'in':'cm')+')';wl.textContent='Weight ('+(imperial?'lb':'kg')+')';fill();
    const next=button('Continue','btn primary wide',()=>{
      const y=num(age.value),h=num(height.value),w=num(weight.value);
      if(y!=null&&(y<13||y>100||!Number.isInteger(y))){toast('Enter your age in whole years');age.focus();return}
      const d={...store.athlete(),units:imperial?'imperial':'metric',sex:sex.value};
      if(y!=null)d.age_years=y;if(h!=null&&h>0)d.height_cm=Math.round((imperial?h*2.54:h)*10)/10;
      store.putEntity('athlete','self',d);
      if(w!=null&&w>0)store.putEntity('measurement',uid(),{measured_at:iso(Date.now(),zone()),kind:'bodyweight',value:Math.round((imperial?w*units.LB:w)*100)/100,unit:'kg',source:'Train web'});
      step=1;paint()});
    return [el('h2',{class:'setup-title',text:'About you'}),el('p',{class:'hint',text:'Ranks compare you with lifters of your sex and bodyweight. Your coach uses all of this. Leave anything blank you would rather not share.'}),
      seg,el('label',{class:'field-label'},el('span',{text:'Age'}),age),el('div',{class:'row2'},el('label',{class:'field-label'},hl,height),el('label',{class:'field-label'},wl,weight)),
      el('label',{class:'field-label'},el('span',{text:'Sex'}),sex),next];
  }
  /** Two independent opt-ins, both off unless chosen. */
  function choices(){
    const v=settings.get();
    const diss=toggle('Diss mode','Crude, profane nudges when you skip a session, and blunt briefs when you fall short of the plan.',!!v.roast);
    const timed=toggle('Scheduled sprints','Book dated sessions with start times and get a reminder before each one. Off keeps a simple repeating cycle.',!!v.scheduled_sprints);
    const photos=toggle('Reminder photos','Let Diss mode reminders show private photos you choose. Off by default.',!!v.photos_enabled);let ids=[...(v.photo_ids||[])];
    const choose=button('Choose photos','btn quiet wide',async()=>{const r=await choosePhotos(ids);if(r){ids=r;choose.textContent=ids.length?ids.length+(ids.length===1?' photo chosen':' photos chosen'):'Choose photos'}});
    if(ids.length)choose.textContent=ids.length+(ids.length===1?' photo chosen':' photos chosen');
    const extra=el('div',{class:'stack nested'});const sync=()=>{extra.hidden=!diss.input.checked;extra.replaceChildren(...[photos.el,photos.input.checked?choose:null].filter(Boolean))};
    diss.input.onchange=async()=>{if(diss.input.checked&&!await confirmDialog('Turn on Diss mode?','Reminders and some briefs may use crude, profane language. You can turn it off any time in Profile.','Turn on','Cancel'))diss.input.checked=false;sync()};
    photos.input.onchange=sync;sync();
    return [el('h2',{class:'setup-title',text:'How Train treats you'}),el('p',{class:'hint',text:'Both stay off unless you turn them on. You can change either one later in Profile.'}),
      el('div',{class:'card'},diss.el,extra,timed.el),
      button('Continue','btn primary wide',async()=>{let ok=await settings.save({roast:diss.input.checked,scheduled_sprints:timed.input.checked});
        if(photos.input.checked||ids.length)ok=await settings.save({photos_enabled:photos.input.checked,photo_ids:ids})&&ok;
        if(!ok&&(diss.input.checked||timed.input.checked))toast('Saved once you are online. Check Profile later.');step=2;paint()}),
      button('Back','btn ghost wide',()=>{step=0;paint()})];
  }
  function coach(){
    return [el('div',{class:'setup-coach'},icon('sparkle')),el('h2',{class:'setup-title',text:'Plan your first sprint'}),
      el('p',{class:'hint',text:'Your coach asks about your goals, the days you can train and your equipment, then proposes a sprint. Nothing changes until you approve it.'}),
      button('Talk to your coach','btn primary wide',finish),button('Back','btn ghost wide',()=>{step=1;paint()})];
  }
  async function finish(){
    try{account.setup_complete=(await api('me',{method:'PATCH',body:{setup_complete:true}})).setup_complete}catch{}
    haptic(12);p.onclose=null;p.close();done?.(account);nav.coach({},null,FIRST_SPRINT);
  }
  p.onclose=()=>done?.(account);
  paint();
}
const num=v=>{const t=String(v).trim().replace(',','.');if(!t)return null;const n=Number(t);return Number.isFinite(n)?n:null};
function toggle(title,note,on){const input=el('input',{type:'checkbox',class:'switch',checked:on,attrs:{role:'switch'}});
  return {el:el('label',{class:'toggle'},el('span',{class:'grow'},el('strong',{text:title}),el('small',{text:note})),input),input}}
