// One month of training at a glance, as on Android: a day holds a circle in its workout's colour, an outline for a rest day, and
// sprints sit behind as quiet bands. Swipe or use the arrows for other months; a bar per month above jumps anywhere in years of history.
import {el,alpha,cssColor} from './core.js';

const WEEK=['M','T','W','T','F','S','S'];
const iso=(y,m,d)=>`${y}-${String(m+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;

/** days: Map iso → [colour,…] (empty array = rest day); bands: [{from,to,color}] */
export function calendar({year,month,days,bands,onTap,onSwipe,today}){
  const lead=(new Date(Date.UTC(year,month,1)).getUTCDay()+6)%7,length=new Date(Date.UTC(year,month+1,0)).getUTCDate();
  const grid=el('div',{class:'cal',attrs:{role:'grid','aria-label':new Date(Date.UTC(year,month,1)).toLocaleDateString(undefined,{month:'long',year:'numeric',timeZone:'UTC'})}});
  for(const w of WEEK)grid.append(el('span',{class:'cal-head',text:w,attrs:{'aria-hidden':'true'}}));
  for(let i=0;i<lead;i++)grid.append(el('span',{class:'cal-blank'}));
  for(let d=1;d<=length;d++){
    const key=iso(year,month,d),hues=days.get(key),col=(lead+d-1)%7,cell=el('button',{type:'button',class:'cal-day',attrs:{role:'gridcell','aria-label':new Date(key+'T12:00:00Z').toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'long',timeZone:'UTC'})+(hues?hues.length?', workout':', rest day':'')}});
    // A sprint is a wash behind its days, one rounded strip per week, so the circles stay the loudest thing here.
    const band=bands.find(b=>b.from<=key&&key<=b.to);
    if(band){const bg=el('span',{class:'cal-band'});bg.style.background=alpha(band.color,document.documentElement.dataset.theme==='dark'?.10:.13);if(key===band.from||col===0)bg.classList.add('start');if(key===band.to||col===6||d===length)bg.classList.add('end');cell.append(bg)}
    const dot=el('span',{class:'cal-dot',text:String(d)});
    if(hues&&hues.length){dot.classList.add('filled');dot.style.background=hues.length>1?`linear-gradient(90deg,${cssColor(hues[0])} 50%,${cssColor(hues[1])} 50%)`:cssColor(hues[0])}
    else if(hues)dot.classList.add('rest');
    if(key===today)dot.classList.add('today');if(key>today)dot.classList.add('future');
    cell.append(dot);if(hues)cell.addEventListener('click',()=>onTap(key));else{cell.disabled=true;cell.tabIndex=-1}
    grid.append(cell);
  }
  let startX=0,startY=0;
  grid.addEventListener('touchstart',e=>{startX=e.touches[0].clientX;startY=e.touches[0].clientY},{passive:true});
  grid.addEventListener('touchend',e=>{const dx=e.changedTouches[0].clientX-startX,dy=e.changedTouches[0].clientY-startY;if(Math.abs(dx)>60&&Math.abs(dx)>Math.abs(dy)*1.5)onSwipe(dx<0?1:-1)},{passive:true});
  return grid;
}

/** Every training month as a bar, newest at the end, so years read at a glance. */
export function months(list,counts,selected,onPick){
  const top=Math.max(1,...list.map(m=>counts.get(m)||0));
  const strip=el('div',{class:'months',attrs:{role:'listbox','aria-label':'Months'}});
  for(const m of list){const n=counts.get(m)||0,[y,mo]=m.split('-').map(Number),on=m===selected;
    const bar=el('span',{class:'month-bar'+(n?'':' empty')});bar.style.height=n?Math.max(6,44*n/top)+'px':'3px';
    const name=mo===1?"'"+String(y).slice(2):new Date(Date.UTC(y,mo-1,1)).toLocaleDateString(undefined,{month:'narrow',timeZone:'UTC'});
    const b=el('button',{type:'button',class:'month'+(on?' on':''),attrs:{role:'option','aria-selected':String(on),'aria-label':new Date(Date.UTC(y,mo-1,1)).toLocaleDateString(undefined,{month:'long',year:'numeric',timeZone:'UTC'})+', '+n+(n===1?' workout':' workouts')}},bar,el('span',{class:'month-name',text:name}));
    b.onclick=()=>onPick(m);strip.append(b)}
  requestAnimationFrame(()=>strip.querySelector('.on')?.scrollIntoView({inline:'center',block:'nearest'}));
  return strip;
}
