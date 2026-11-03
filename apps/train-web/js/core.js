// Small DOM toolkit for Train: elements, the native glyphs, pages that stack like the Android sheets, dialogs and toasts.
import {GLYPHS} from './glyphs.js';

const SVG='http://www.w3.org/2000/svg';
// Optional children are written as cond?node:null throughout; the DOM would otherwise print them as the text "null".
for(const name of ['append','prepend','replaceChildren']){const native=Element.prototype[name];Element.prototype[name]=function(...nodes){return native.apply(this,nodes.filter(n=>n!==null&&n!==undefined&&n!==false))}}
export const uid=()=>'c'+crypto.randomUUID().replace(/-/g,'');
export const plural=(n,word,many)=>n+' '+(n===1?word:(many||word+'s'));
export const clock=s=>{s=Math.max(0,Math.round(s||0));const h=Math.floor(s/3600),m=Math.floor(s/60)%60,r=s%60,p=v=>String(v).padStart(2,'0');return h?`${h}:${p(m)}:${p(r)}`:`${m}:${p(r)}`};
export const num=v=>Number.isInteger(v)?String(v):(Math.round(v*10)/10).toString();
export const reduced=()=>matchMedia('(prefers-reduced-motion:reduce)').matches;

/** el('div',{class:'card',text:'Hi',on:{click:f},attrs:{role:'list'}},child,...) */
export function el(tag,props,...children){
  const n=document.createElement(tag);
  if(props)for(const [k,v] of Object.entries(props)){
    if(v===undefined||v===null||v===false)continue;
    if(k==='class')n.className=v;else if(k==='text')n.textContent=v;else if(k==='html')n.innerHTML=v;
    else if(k==='on')for(const [e,f] of Object.entries(v))n.addEventListener(e,f);
    else if(k==='style')Object.assign(n.style,v);else if(k==='attrs')for(const [a,b] of Object.entries(v))n.setAttribute(a,b);
    else if(k==='data')for(const [a,b] of Object.entries(v))n.dataset[a]=b;else n[k]=v;
  }
  for(const c of children.flat())if(c!==null&&c!==undefined&&c!==false)n.append(c instanceof Node?c:document.createTextNode(String(c)));
  return n;
}
export function svg(tag,attrs,...children){const n=document.createElementNS(SVG,tag);for(const [k,v] of Object.entries(attrs||{}))n.setAttribute(k,v);n.append(...children.flat().filter(Boolean));return n}

/** A native glyph on its 24-unit grid. */
export function icon(name,cls){
  const root=svg('svg',{viewBox:'0 0 24 24',class:'i'+(cls?' '+cls:''),'aria-hidden':'true'});
  for(let part of (GLYPHS[name]||'').split('|')){
    const fill=part.startsWith('F');if(fill)part=part.slice(1);let node;
    if(part.startsWith('O')){const [cx,cy,r]=part.slice(1).trim().split(/\s+/);node=svg('circle',{cx,cy,r})}
    else if(part.startsWith('R')){const [x,y,w,h,r]=part.slice(1).trim().split(/\s+/);node=svg('rect',{x,y,width:w,height:h,rx:r})}
    else node=svg('path',{d:part});
    if(fill){node.setAttribute('fill','currentColor');node.setAttribute('stroke','none')}
    root.append(node);
  }
  return root;
}
export function button(label,cls,run,attrs){const b=el('button',{class:cls||'btn',type:'button',attrs},label);if(run)b.addEventListener('click',run);return b}
export function iconButton(name,label,run,cls,color){const b=el('button',{class:'icon-btn'+(cls?' '+cls:''),type:'button',attrs:{'aria-label':label,title:label}},icon(name));if(color)b.style.color=color;if(run)b.addEventListener('click',run);return b}

/** Hues shared with Android; CSS variables keep both themes right. */
export const HUE={amber:'var(--amber)',teal:'var(--teal)',violet:'var(--violet)',pink:'var(--pink)',blue:'var(--blue)',green:'var(--green)',orange:'var(--orange)',red:'var(--red)'};
export function cssColor(value){
  if(!value.startsWith('var('))return value;
  return getComputedStyle(document.documentElement).getPropertyValue(value.slice(4,-1)).trim()||'#888';
}
export function alpha(color,a){
  const c=cssColor(color).replace('#','');if(c.length<6)return color;
  const n=parseInt(c.slice(0,6),16);return `rgba(${n>>16&255},${n>>8&255},${n&255},${a})`;
}

let toastTimer=0;
export function toast(message,kind){
  let t=document.getElementById('toast');if(!t){t=el('div',{id:'toast',class:'toast',attrs:{role:'status','aria-live':'polite'}});document.body.append(t)}
  t.textContent=message;t.dataset.kind=kind||'';t.hidden=false;t.classList.remove('out');void t.offsetWidth;t.classList.add('in');
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>{t.classList.add('out');setTimeout(()=>{t.hidden=true},220)},4200);
}

/** Pages stack over the dashboard like the Android sheets. Back, the browser's back and a swipe from the edge all close the top one. */
const stack=[];
export function page(title,options={}){
  const back=iconButton('back','Back',()=>history.back());
  const heading=el('h2',{class:'page-title',text:title});
  const end=el('div',{class:'bar-end'},...(options.actions||[]));
  const bar=el('header',{class:'page-bar'},back,heading,end);
  const body=el('div',{class:'page-body'});
  const root=el('section',{class:'page'+(options.cls?' '+options.cls:''),attrs:{role:'dialog','aria-modal':'true','aria-label':title}},bar,body);
  if(options.footer)root.append(options.footer);
  const entry={root,body,bar,heading,end,onclose:options.onclose,closed:false};
  // Closing from code removes the page now and skips the popstate its history.back() causes, so a page opened right after survives.
  entry.close=()=>{if(entry.closed||!stack.includes(entry))return;ignore++;remove(entry);history.back()};
  stack.push(entry);document.getElementById('pages').append(root);document.body.classList.add('paged');
  history.pushState({page:stack.length},'');
  requestAnimationFrame(()=>root.classList.add('open'));
  setTimeout(()=>back.focus({preventScroll:true}),60);
  return entry;
}
export function topPage(){return stack[stack.length-1]}
let ignore=0;
function remove(top){
  const i=stack.indexOf(top);if(i<0)return;stack.splice(i,1);top.closed=true;top.root.classList.remove('open');top.root.classList.add('closing');
  setTimeout(()=>top.root.remove(),reduced()?0:220);if(!stack.length)document.body.classList.remove('paged');
  const after=top.onclose;top.onclose=null;if(after)after();
}
addEventListener('popstate',()=>{if(ignore){ignore--;return}if(openDialog){openDialog.cancel();history.pushState({page:stack.length},'');return}const top=stack[stack.length-1];if(top)remove(top)});
export function closeAll(){const n=stack.length;if(n)history.go(-n)}

/** Native-feeling dialogs that resolve with the choice; Escape and the backdrop cancel. */
let openDialog=null;
function dialog(build){
  return new Promise(resolve=>{
    const d=el('dialog',{class:'dialog'});const done=v=>{if(!d.open)return;openDialog=null;d.close();d.remove();resolve(v)};
    build(d,done);d.addEventListener('cancel',e=>{e.preventDefault();done(null)});d.addEventListener('click',e=>{if(e.target===d)done(null)});
    document.body.append(d);d.showModal();openDialog={cancel:()=>done(null)};
  });
}
export function confirmDialog(title,message,ok='OK',cancel='Cancel',danger){
  return dialog((d,done)=>{d.append(el('h3',{text:title}),message?el('p',{class:'dialog-text',text:message}):null,
    el('div',{class:'dialog-actions'},button(cancel,'btn ghost',()=>done(false)),button(ok,'btn '+(danger?'danger':'primary'),()=>done(true))))});
}
/** fields: [{name,label,value,type,inputmode}] */
export function promptDialog(title,fields,ok='Save'){
  return dialog((d,done)=>{
    const inputs=fields.map(f=>el('input',{class:'field',value:f.value??'',type:f.type||'text',placeholder:f.label,attrs:{'aria-label':f.label,inputmode:f.inputmode||'text',enterkeyhint:'done'}}));
    const form=el('form',{on:{submit:e=>{e.preventDefault();const out={};fields.forEach((f,i)=>out[f.name]=inputs[i].value.trim());done(out)}}},
      el('h3',{text:title}),...inputs.map((i,k)=>el('label',{class:'field-label'},el('span',{text:fields[k].label}),i)),
      el('div',{class:'dialog-actions'},button('Cancel','btn ghost',()=>done(null)),el('button',{class:'btn primary',type:'submit'},ok)));
    d.append(form);setTimeout(()=>{inputs[0]?.focus();inputs[0]?.select()},40);
  });
}
export function choiceDialog(title,items){
  return dialog((d,done)=>{d.append(el('h3',{text:title}),el('div',{class:'choices'},...items.map((t,i)=>button(t,'choice',()=>done(i)))),
    el('div',{class:'dialog-actions'},button('Cancel','btn ghost',()=>done(null))))});
}
export function haptic(ms=8){try{navigator.vibrate?.(ms)}catch{}}
export function card(...children){return el('div',{class:'card'},...children)}
export function stat(value,label){return el('div',{class:'stat'},el('strong',{text:value}),el('span',{text:label}))}
export function pair(left,right,cls){return el('div',{class:'pair'},el('span',{text:left}),el('strong',{class:cls||'',text:right}))}
export function detail(text){return el('p',{class:'hint',text})}
export function label(text){return el('p',{class:'label',text})}
/** A tappable row with a title, a note and a chevron, as in the native app. */
export function row(title,note,run,lead){const r=el('button',{class:'row-btn',type:'button'},lead||null,el('span',{class:'grow'},el('strong',{text:title}),note?el('small',{text:note}):null),icon('arrow','chev'));r.addEventListener('click',run);return r}
