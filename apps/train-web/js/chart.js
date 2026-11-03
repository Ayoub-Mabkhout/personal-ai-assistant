// A dated chart to handle with one finger, as on Android: it opens on recent months, drags sideways through older history, and a
// hold draws a line that steps from measurement to measurement. A break longer than gap is dashed, so missing readings never look measured.
import {el,cssColor,alpha,haptic,num} from './core.js';

const LONG={weekday:'short',day:'numeric',month:'short',year:'numeric'};
const epochDay=iso=>Math.floor(Date.parse(iso+'T00:00:00Z')/86400000);
const fromDay=d=>new Date(d*86400000);
export {epochDay};

export function chart({height=220,format=v=>num(v),gap=1e9,window=183,reference=null,label='Chart'}={}){
  const series=[];let events=null,first=Infinity,last=-Infinity,span=0,end=0,placed=false,marker=-1;
  const canvas=el('canvas',{class:'chart',attrs:{role:'img','aria-label':label,tabindex:'0'}});canvas.style.height=height+'px';
  const add=(points,color,width,dashed,gapsOnly,name)=>{series.push({points,color,width,dashed,gapsOnly,name});if(!events&&points.length)events=points;for(const q of points){first=Math.min(first,q[0]);last=Math.max(last,q[0])}return api};
  const api={
    el:canvas,
    dots:(p,c,n)=>add(p,c,0,false,false,n),line:(p,c,w,n)=>add(p,c,w,true,false,n),
    breaks:(p,c,w,n)=>add(p,c,w,false,false,n),gaps:(p,c)=>add(p,c,1,true,true,null),
    spanTo(days){marker=-1;const from=span,to=Math.min(days,total()),right=end,t0=performance.now();
      const step=t=>{const f=Math.min(1,(t-t0)/220);span=from+(to-from)*f;end=clamp(right);draw();if(f<1)requestAnimationFrame(step)};requestAnimationFrame(step)},
    framed(){const wrap=el('div',{class:'chart-wrap'});const chips=el('div',{class:'range'});const names=['3M','6M','1Y','All'],days=[92,183,365,1e6];
      names.forEach((n,i)=>{const b=el('button',{type:'button',class:'range-chip'+(i===1?' on':''),text:n});b.onclick=()=>{chips.querySelectorAll('.on').forEach(x=>x.classList.remove('on'));b.classList.add('on');api.spanTo(days[i])};chips.append(b)});
      wrap.append(chips,canvas);return wrap}
  };
  const total=()=>Math.max(14,(last-first)*1.04);
  const clamp=v=>Math.max(first+span*.97,Math.min(last+span*.03,v));
  let W=0,H=0,plot={l:4,t:10,r:0,b:0},low=0,high=1,step=1;const dpr=()=>window.devicePixelRatio||1;
  const x=d=>plot.l+(d-(end-span))/span*(plot.r-plot.l),y=v=>plot.b-(v-low)/(high-low)*(plot.b-plot.t);
  function scale(){let min=Infinity,max=-Infinity;const from=end-span;
    for(const s of series){if(s.gapsOnly)continue;const q=s.points;for(let i=0;i<q.length;i++){const inside=q[i][0]>=from&&q[i][0]<=end||(i+1<q.length&&q[i][0]<from&&q[i+1][0]>from)||(i>0&&q[i][0]>end&&q[i-1][0]<end);if(inside){min=Math.min(min,q[i][1]);max=Math.max(max,q[i][1])}}}
    if(reference!=null&&(max===-Infinity||reference<=max*1.25)){min=Math.min(min,reference);max=Math.max(max,reference)}
    if(max===-Infinity){min=0;max=1}if(max===min){min-=1;max+=1}
    const raw=(max-min)/3,p=10**Math.floor(Math.log10(raw)),u=raw/p;step=(u<=1?1:u<=2?2:u<=2.5?2.5:u<=5?5:10)*p;low=Math.floor(min/step)*step;high=Math.ceil(max/step)*step}
  function draw(){
    const r=canvas.getBoundingClientRect();if(!r.width)return;W=r.width;H=r.height;const k=dpr();canvas.width=W*k;canvas.height=H*k;
    plot={l:4,t:10,r:W-52,b:H-24};if(!placed&&series.length){placed=true;span=Math.min(window,total());end=clamp(last+span*.03)}
    const c=canvas.getContext('2d');c.setTransform(k,0,0,k,0,0);c.clearRect(0,0,W,H);if(!series.length||span<=0)return;scale();
    const muted=cssColor('var(--muted)'),stroke=cssColor('var(--stroke)'),strong=cssColor('var(--stroke-strong)'),text=cssColor('var(--text)');
    c.font='500 11px Onest,system-ui,sans-serif';c.textAlign='right';c.fillStyle=muted;c.lineWidth=1;
    for(let v=low;v<=high+step/2;v+=step){const at=y(v);c.strokeStyle=stroke;c.beginPath();c.moveTo(plot.l,at);c.lineTo(plot.r,at);c.stroke();c.fillText(format(v),W-2,at+4)}
    dates(c,muted,stroke);
    c.save();c.beginPath();c.rect(plot.l-4,0,plot.r-plot.l+8,plot.b+4);c.clip();
    if(reference!=null){c.strokeStyle=strong;c.setLineDash([3,4]);c.beginPath();c.moveTo(plot.l,y(reference));c.lineTo(plot.r,y(reference));c.stroke();c.setLineDash([])}
    for(const s of series)drawSeries(c,s);
    if(marker>=0){const at=x(events[marker][0]);c.strokeStyle=text;c.lineWidth=1.5;c.beginPath();c.moveTo(at,plot.t);c.lineTo(at,plot.b);c.stroke()}
    c.restore();if(marker>=0)tip(c);
  }
  function drawSeries(c,s){const color=cssColor(s.color);c.strokeStyle=c.fillStyle=color;c.lineCap='round';c.lineJoin='round';
    if(s.width===0){const r=span>400?1.4:2.2;for(const q of s.points)if(q[0]>=end-span-2&&q[0]<=end+2){c.beginPath();c.arc(x(q[0]),y(q[1]),r,0,7);c.fill()}return}
    c.lineWidth=s.width;const line=new Path2D(),missing=new Path2D();let before=null,px=0,py=0;
    for(const q of s.points){const a=x(q[0]),b=y(q[1]);if(before===null){line.moveTo(a,b)}else if(q[0]-before>gap){missing.moveTo(px,py);missing.lineTo(a,b);line.moveTo(a,b)}else line.lineTo(a,b);before=q[0];px=a;py=b}
    if(!s.gapsOnly)c.stroke(line);if(s.dashed){c.setLineDash([4,5]);c.lineWidth=1.5;c.stroke(missing);c.setLineDash([])}}
  /** Weeks up close, then months, then years; January names the year. */
  function dates(c,muted,stroke){const from=end-span,base=H-6;c.textAlign='center';c.fillStyle=muted;
    const put=(d,text)=>{const at=x(d);if(at<plot.l+12||at>plot.r-6)return;c.strokeStyle=stroke;c.beginPath();c.moveTo(at,plot.b);c.lineTo(at,plot.b+4);c.stroke();c.fillText(text,at,base)};
    const start=fromDay(Math.floor(from));
    if(span<=62){const weeks=span<=31?1:2;const d=new Date(start);d.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7));for(;d/86400000<=end;d.setUTCDate(d.getUTCDate()+7*weeks))put(Math.floor(d/86400000),d.toLocaleDateString(undefined,{day:'numeric',month:'short',timeZone:'UTC'}));return}
    const months=span<=240?1:span<=460?2:span<=1000?3:span<=2200?6:12;const d=new Date(Date.UTC(start.getUTCFullYear(),start.getUTCMonth(),1));while(d.getUTCMonth()%months)d.setUTCMonth(d.getUTCMonth()-1);
    for(;d/86400000<=end;d.setUTCMonth(d.getUTCMonth()+months))put(Math.floor(d/86400000),d.getUTCMonth()===0?String(d.getUTCFullYear()):d.toLocaleDateString(undefined,{month:'short',timeZone:'UTC'}))}
  /** The date and every series at the chosen measurement, kept inside the frame. */
  function tip(c){const e=events[marker],date=fromDay(e[0]).toLocaleDateString(undefined,{...LONG,timeZone:'UTC'}),rows=[];
    for(const s of series){if(!s.name)continue;const q=s.points.find(p=>Math.abs(p[0]-e[0])<.5);if(!q)continue;rows.push([s.color,s.name+'  '+format(q[1])]);
      c.fillStyle=cssColor('var(--surface)');c.beginPath();c.arc(x(e[0]),y(q[1]),5,0,7);c.fill();c.fillStyle=cssColor(s.color);c.beginPath();c.arc(x(e[0]),y(q[1]),3.5,0,7);c.fill()}
    c.textAlign='left';c.font='700 12px Onest,system-ui,sans-serif';let w=c.measureText(date).width;c.font='500 12px Onest,system-ui,sans-serif';for(const r of rows)w=Math.max(w,c.measureText(r[1]).width+14);
    const pad=9,line=17,bw=w+2*pad,bh=pad*2+line*(1+rows.length),high=Math.min(...series.filter(s=>s.name).map(s=>{const q=s.points.find(p=>Math.abs(p[0]-e[0])<.5);return q?y(q[1]):Infinity})),side=x(e[0])>W/2?-1:1,left=Math.max(0,Math.min(W-bw,high<bh+16?x(e[0])+side*14-(side<0?bw:0):x(e[0])-bw/2)),top=high<bh+16?Math.max(0,Math.min(plot.b-bh,high-bh/2)):0;
    c.fillStyle=cssColor('var(--surface-alt)');c.strokeStyle=cssColor('var(--stroke-strong)');c.lineWidth=1;c.beginPath();c.roundRect(left,top,bw,bh,12);c.fill();c.stroke();
    let at=top+pad+12;c.fillStyle=cssColor('var(--text)');c.font='700 12px Onest,system-ui,sans-serif';c.fillText(date,left+pad,at);c.font='500 12px Onest,system-ui,sans-serif';
    for(const [color,text] of rows){at+=line;c.fillStyle=cssColor(color);c.beginPath();c.arc(left+pad+4,at-4,4,0,7);c.fill();c.fillStyle=cssColor('var(--text)');c.fillText(text,left+pad+14,at)}
    canvas.setAttribute('aria-label',label+'. '+date+': '+rows.map(r=>r[1]).join(', '))}
  function snap(px){if(!events)return;const r=canvas.getBoundingClientRect(),dayAt=end-span+(px-r.left-plot.l)/((plot.r-plot.l)/span);let best=-1,near=Infinity;
    events.forEach((e,i)=>{if(e[0]<end-span||e[0]>end)return;const d=Math.abs(e[0]-dayAt);if(d<near){near=d;best=i}});if(best>=0&&best!==marker){if(marker>=0)haptic(4);marker=best}draw()}
  // One finger: a hold scrubs, a sideways drag pans and flings, a vertical move belongs to the page.
  let downX=0,downY=0,lastX=0,holding=false,dragging=false,moved=false,timer=0,velocity=0,lastT=0,flingFrame=0;
  canvas.style.touchAction='pan-y';
  canvas.addEventListener('pointerdown',e=>{cancelAnimationFrame(flingFrame);downX=lastX=e.clientX;downY=e.clientY;holding=dragging=moved=false;velocity=0;lastT=e.timeStamp;
    timer=setTimeout(()=>{holding=true;canvas.setPointerCapture(e.pointerId);haptic(12);snap(downX)},240)});
  canvas.addEventListener('pointermove',e=>{if(holding){snap(e.clientX);return}const dx=e.clientX-downX,dy=e.clientY-downY;
    if(!dragging&&Math.abs(dx)>6&&Math.abs(dx)>Math.abs(dy)){clearTimeout(timer);moved=true;if(span<total()){dragging=true;marker=-1;canvas.setPointerCapture(e.pointerId)}}
    else if(Math.abs(dy)>6){clearTimeout(timer);moved=true}
    if(dragging){const perDay=(plot.r-plot.l)/span,move=e.clientX-lastX;end=clamp(end-move/perDay);const dt=Math.max(1,e.timeStamp-lastT);velocity=move/dt;lastT=e.timeStamp;draw()}lastX=e.clientX});
  const finish=e=>{clearTimeout(timer);if(dragging){let v=velocity;const glide=()=>{v*=.94;if(Math.abs(v)<.02)return;const before=end;end=clamp(end-v*16/((plot.r-plot.l)/span));draw();if(end!==before)flingFrame=requestAnimationFrame(glide)};flingFrame=requestAnimationFrame(glide)}
    else if(holding)marker=-1;else if(!moved&&e.type==='pointerup'){if(marker>=0)marker=-1;else snap(e.clientX)}holding=dragging=false;draw()};
  canvas.addEventListener('pointerup',finish);canvas.addEventListener('pointercancel',finish);
  canvas.addEventListener('keydown',e=>{if(!events)return;if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();const visible=events.map((q,i)=>i).filter(i=>events[i][0]>=end-span&&events[i][0]<=end);if(!visible.length)return;const at=visible.indexOf(marker);marker=visible[Math.max(0,Math.min(visible.length-1,at<0?visible.length-1:at+(e.key==='ArrowRight'?1:-1)))];draw()}else if(e.key==='Escape'){marker=-1;draw()}});
  new ResizeObserver(draw).observe(canvas);
  return api;
}

/** A small single line for a tile; see art.spark for the SVG version. */
export const toPoints=(items,dateKey,valueKey,convert=v=>v)=>items.filter(i=>i[valueKey]!=null).map(i=>[epochDay(i[dateKey].slice(0,10)),convert(i[valueKey])]);
export {alpha};
