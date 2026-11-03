// Drawn pieces of Train, ported from the native views: exercise figures with equipment badges, tier crests, the ridge of camps,
// the muscle map and dashboard sparklines. All SVG, so they stay sharp and cost nothing to ship.
import {svg,el,icon,HUE,alpha,cssColor} from './core.js';
import {data,rows} from './store.js';

const WORDS=[['run','run','treadmill','jog'],['walk','walk','hike'],['curl','curl'],['extension','pushdown','skullcrusher','extension','triceps','dip'],['raise','raise','fly'],['squat','squat','leg press','hack'],['lunge','lunge','split','step'],['hinge','deadlift','romanian','hip thrust','good morning'],['pull','pull-up','pull up','chin','pulldown'],['row','row'],['press','press','bench','push'],['core','plank','crunch','sit-up','ab ']];
/** Backend fields when present, otherwise read from the name so imported exercises are illustrated too. */
export function movement(e){const v=e?.movement||'';if(v&&v!=='other')return v;const n=(e?.name||'').toLowerCase();for(const w of WORDS)for(const k of w.slice(1))if(n.includes(k))return w[0];return 'other'}
export function equipment(e){const t=((e?.equipment||'')+' '+(e?.name||'')).toLowerCase();if(t.includes('barbell')||t.includes('ez bar'))return 'barbell';if(t.includes('dumbbell'))return 'dumbbell';if(t.includes('cable'))return 'cable';if(/machine|smith|treadmill|leg press/.test(t))return 'machine';if(/bodyweight|pull-up|pull up|push-up/.test(t))return 'person';return ''}
export function group(e){switch(movement(e)){case 'press':case 'raise':case 'extension':return 'Push';case 'row':case 'pull':case 'curl':return 'Pull';case 'squat':case 'lunge':case 'hinge':return 'Legs and hips';case 'run':case 'walk':return 'Cardio';case 'core':return 'Core';default:return 'Other'}}
export function hue(groupName){return {Push:HUE.pink,Pull:HUE.blue,'Legs and hips':HUE.green,Cardio:HUE.orange,Core:HUE.amber}[groupName]||HUE.violet}
export const exerciseHue=e=>hue(group(e));
/** A session takes the colour of the movement family with the most sets. */
export function sessionHue(w){const counts={};let best='Other',most=0;for(const s of w.sets||[]){if(s.kind==='warmup'&&!s.distance_m)continue;const g=group(data('exercise',s.exercise_id));counts[g]=(counts[g]||0)+1;if(counts[g]>most){most=counts[g];best=g}}return hue(best)}
const GEAR={barbell:HUE.amber,dumbbell:HUE.blue,machine:HUE.teal,cable:HUE.green,person:HUE.violet};
const POSES={press:[[24,14],[[10,34,38,34],[24,18,24,34],[24,22,14,26,14,12],[24,22,34,26,34,12],[8,10,40,10]]],squat:[[24,10],[[24,14,22,26],[22,26,32,30,28,42],[22,26,14,32,18,42],[10,17,38,17],[24,17,24,17]]],hinge:[[34,14],[[30,18,16,24],[16,24,20,34,20,44],[28,20,28,34],[16,36,40,36]]],row:[[32,12],[[28,16,16,26],[16,26,20,36,18,44],[26,20,32,28,24,31],[14,33,34,33]]],pull:[[24,16],[[8,6,40,6],[24,20,24,32],[24,22,14,16,14,6],[24,22,34,16,34,6],[24,32,20,44],[24,32,28,44]]],curl:[[24,8],[[24,12,24,28],[24,16,18,24,12,16],[24,16,30,24,36,16],[24,28,20,44],[24,28,28,44],[8,15,16,15],[32,15,40,15]]],extension:[[24,8],[[24,12,24,28],[24,15,18,23,20,31],[24,15,30,23,28,31],[24,28,20,44],[24,28,28,44],[24,4,20,31],[24,4,28,31]]],raise:[[24,8],[[24,12,24,28],[24,16,8,16],[24,16,40,16],[24,28,20,44],[24,28,28,44],[6,12,6,20],[42,12,42,20]]],lunge:[[24,8],[[24,12,24,26],[24,26,34,30,34,42],[24,26,16,34,6,42],[24,16,20,26],[24,16,28,26]]],core:[[36,24],[[32,26,14,32],[14,32,6,40],[30,28,28,38,24,40]]],run:[[30,9],[[28,13,22,26],[22,26,32,31,28,42],[22,26,14,33,6,31],[27,16,36,20,38,14],[27,16,18,19,14,26]]],walk:[[26,9],[[26,13,24,27],[24,27,30,36,30,44],[24,27,18,36,14,44],[25,17,32,25],[25,17,18,25]]],other:[[24,9],[[24,13,24,28],[24,17,14,24],[24,17,34,24],[24,28,18,44],[24,28,30,44]]]};

/** One exercise's figure: its own drawn pose when the coach gave it one, else the movement's, with an equipment badge. */
export function tile(exerciseOrId,size=44){
  const e=typeof exerciseOrId==='string'?data('exercise',exerciseOrId):exerciseOrId;const color=exerciseHue(e),gear=equipment(e);
  let [head,limbs]=POSES[movement(e)]||POSES.other;
  if(Array.isArray(e?.pose?.head)&&e.pose.head.length===2&&Array.isArray(e.pose.limbs)&&e.pose.limbs.length){head=e.pose.head;limbs=e.pose.limbs}
  const root=svg('svg',{viewBox:'0 0 48 48',width:size,height:size,class:'tile','aria-hidden':'true'},
    svg('rect',{width:48,height:48,rx:12.5,fill:alpha(color,.17)}),svg('circle',{cx:head[0],cy:head[1],r:3.8,fill:cssColor(color)}),
    ...limbs.filter(l=>l.length>=4).map(l=>svg('polyline',{points:l.join(' '),fill:'none',stroke:cssColor(color),'stroke-width':2.6,'stroke-linecap':'round','stroke-linejoin':'round'})));
  if(gear){const badge=svg('g',{transform:'translate(27.8 27.8)'},svg('circle',{cx:10.1,cy:10.1,r:11.1,fill:'var(--surface)'}));const g=icon(gear);g.setAttribute('x',2.4);g.setAttribute('y',2.4);g.setAttribute('width',15.4);g.setAttribute('height',15.4);g.style.color=cssColor(GEAR[gear]);g.style.strokeWidth='2.2';badge.append(g);root.append(badge)}
  return root;
}

export const TIERS=['Iron','Bronze','Silver','Gold','Platinum','Emerald','Diamond','Master','Grandmaster','Challenger'];
export const FLOORS=[0,200,300,400,500,600,700,800,900,950];
const COLORS=[['#A6ABB4','#565B64','#DADDE2'],['#D98A4E','#7E4318','#F6C196'],['#C9D3E6','#6F7C96','#FFFFFF'],['#FFC233','#B96D08','#FFEC9C'],['#7DE3FF','#2A7FB8','#E2FAFF'],['#3FD58F','#137A52','#C4F7DE'],['#5B9BFF','#2A3FC4','#BFE0FF'],['#B66DFF','#5A1FB8','#E7CCFF'],['#FF5F7E','#A81A3E','#FFC4D2'],['#FFE27A','#E0562E','#FFFFFF']];
export const tierOf=score=>{let t=0;FLOORS.forEach((f,i)=>{if(score>=f)t=i});return t};
export const tierIndex=name=>{const n=(name||'').toLowerCase();const i=TIERS.findIndex(t=>n===t.toLowerCase()||n.startsWith(t.toLowerCase()+' '));return i<0?0:i};
/** Rank and division, which climb from 4 to 1; the apex ranks have no divisions. */
export function label(score){const t=tierOf(score);if(t>=7)return TIERS[t];return TIERS[t]+' '+(4-Math.floor((score-FLOORS[t])*4/(FLOORS[t+1]-FLOORS[t])))}
const dark=()=>document.documentElement.dataset.theme==='dark'||(!document.documentElement.dataset.theme&&matchMedia('(prefers-color-scheme:dark)').matches);
export function tierColor(t){return dark()||t!==2?COLORS[t][t===3&&!dark()?1:0]:COLORS[t][1]}
function gray(c){const n=parseInt(c.slice(1),16),y=Math.round(((n>>16&255)*3+(n>>8&255)*6+(n&255))/10/2+40);return `rgb(${y},${y},${y+8})`}
/** The ten-step heraldic crest: a shield gains a crown, wings, a star and a second pair of wings. */
export function crest(tier,locked,size=46){
  const c=COLORS[tier].map(x=>locked?gray(x):x);const poly=(fill,...p)=>svg('polygon',{points:p.join(' '),fill});
  const parts=[];
  if(tier>=6)parts.push(poly(c[0],2,26,24,20,24,44,8,50),poly(c[0],118,26,96,20,96,44,112,50));
  if(tier>=3)parts.push(poly(c[1],10,44,26,30,26,74,14,66),poly(c[1],110,44,94,30,94,74,106,66));
  if(tier>=2)parts.push(poly(c[2],44,16,50,4,60,12,70,4,76,16));
  parts.push(poly(c[1],60,14,96,28,92,84,60,122,28,84,24,28),poly(c[0],60,14,96,28,92,84,60,122),poly('rgba(18,10,36,.28)',60,24,86,34,83,80,60,108,37,80,34,34));
  parts.push(tier>=4?poly(c[2],60,40,65,54,80,55,68,64,72,79,60,70,48,79,52,64,40,55,55,54):poly(c[2],60,44,74,60,60,76,46,60));
  return svg('svg',{viewBox:'0 -4 120 134',width:size,height:Math.round(size*134/120),class:'crest','aria-hidden':'true'},...parts);
}
const CAMPS=[[.06,.86],[.15,.74],[.24,.76],[.34,.66],[.43,.58],[.53,.64],[.63,.42],[.71,.48],[.81,.28],[.91,.14]];
/** The camps up a dusk ridge; those above the current rank are dimmed. */
export function ridge(current){
  const W=360,H=176,hill=(fill,...p)=>svg('polygon',{points:[0,H,...p.map((v,i)=>i%2?v*H:v*W),W,H].join(' '),fill});
  const sky=svg('defs',{},svg('linearGradient',{id:'dusk',x1:0,y1:0,x2:0,y2:1},svg('stop',{offset:0,'stop-color':'#1A1248'}),svg('stop',{offset:.65,'stop-color':'#5A2A9A'}),svg('stop',{offset:1,'stop-color':'#C95F8E'})));
  const root=svg('svg',{viewBox:`0 0 ${W} ${H}`,class:'ridge',preserveAspectRatio:'xMidYMid slice','aria-hidden':'true'},sky,svg('rect',{width:W,height:H,fill:'url(#dusk)'}),
    hill('#2A1460',0,.9,.2,.68,.3,.76,.43,.54,.53,.62,.63,.38,.71,.46,.91,.08,1,.24),hill(dark()?cssColor('var(--bg)'):'#1D1729',0,.98,.3,.88,.6,.94,1,.78));
  CAMPS.forEach(([x,y],i)=>{const here=i===current,w=here?36:20,h=here?40:23,c=crest(i,i>current,w);c.setAttribute('x',x*W-w/2);c.setAttribute('y',y*H-h/2);c.setAttribute('width',w);c.setAttribute('height',h);root.append(c)});
  return root;
}
const REGIONS=[['shoulder',14,26,25,26,22,44,11,42],['shoulder',71,26,82,26,85,42,74,44],['chest',26,26,46,26,46,44,24,42],['chest',50,26,70,26,72,42,50,44],['arm',11,45,22,46,19,70,8,68],['arm',74,46,85,45,88,68,77,70],['back',30,46,46,47,46,76,33,76],['back',50,47,66,46,63,76,50,76],['leg',30,79,47,79,45,118,32,118],['leg',49,79,66,79,64,118,51,118],['calf',33,121,44,121,43,146,35,146],['calf',52,121,63,121,61,146,53,146]];
const MUSCLES={shoulder:['shoulder','delt'],chest:['chest','pec'],arm:['arm','bicep','tricep','forearm'],back:['back','lat','trap','erector','core','ab'],leg:['leg','quad','hamstring','glute','thigh'],calf:['calf','calves']};
/** Each region takes the tier colour of the trained muscles under it. */
export function bodyMap(scores={}){
  const best=region=>{let b=-1;for(const [k,v] of Object.entries(scores))if(MUSCLES[region].some(w=>k.toLowerCase().includes(w)))b=Math.max(b,v);return b};
  return svg('svg',{viewBox:'0 0 96 150',class:'bodymap',role:'img','aria-label':'Muscle ranks on a body map'},svg('circle',{cx:48,cy:12,r:9,fill:'var(--stroke-strong)'}),
    ...REGIONS.map(([r,...p])=>{const v=best(r);return svg('polygon',{points:p.join(' '),fill:v<0?'var(--stroke)':COLORS[tierOf(v)][0]})}));
}
/** A small undecorated trend for a dashboard tile. */
export function spark(values,color){
  if(values.length<2)return null;const min=Math.min(...values),max=Math.max(...values)===min?min+1:Math.max(...values),W=120,H=30,p=3;
  const pts=values.map((v,i)=>[p+i*(W-2*p)/(values.length-1),H-p-(v-min)/(max-min)*(H-2*p)]);const line=pts.map(q=>q.join(',')).join(' ');const id='s'+Math.random().toString(36).slice(2);const last=pts[pts.length-1];
  return svg('svg',{viewBox:`0 0 ${W} ${H}`,class:'spark',preserveAspectRatio:'none','aria-hidden':'true'},svg('defs',{},svg('linearGradient',{id,x1:0,y1:0,x2:0,y2:1},svg('stop',{offset:0,'stop-color':cssColor(color),'stop-opacity':.3}),svg('stop',{offset:1,'stop-color':cssColor(color),'stop-opacity':0}))),
    svg('polygon',{points:`${line} ${last[0]},${H} ${p},${H}`,fill:`url(#${id})`}),svg('polyline',{points:line,fill:'none',stroke:cssColor(color),'stroke-width':2,'stroke-linecap':'round','stroke-linejoin':'round','vector-effect':'non-scaling-stroke'}),
    svg('circle',{cx:last[0],cy:last[1],r:2.6,fill:cssColor(color)}));
}
/** Set tags: a working set shows its number, warm-up, drop and failure sets a coloured letter. */
export const SET_KINDS=['working','warmup','drop','failure'];
export function setTag(kind,n){const color={warmup:HUE.orange,drop:HUE.blue,failure:HUE.red}[kind];const t=el('span',{class:'set-tag',text:{warmup:'W',drop:'D',failure:'F'}[kind]||String(n)});if(color){t.style.color=color;t.style.background=alpha(color,.18)}return t}
export const setName=k=>({warmup:'Warm-up',drop:'Drop',failure:'Failure'}[k]||'Working');
