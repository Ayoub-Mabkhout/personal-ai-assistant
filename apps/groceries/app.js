'use strict';
const $=id=>document.getElementById(id),base='/groceries/',client=location.origin+base,HOLD=4000,SVG='http://www.w3.org/2000/svg';
function read(key,fallback){try{return JSON.parse(localStorage.getItem(key))??fallback}catch{return fallback}}
function write(key,value){try{localStorage.setItem(key,JSON.stringify(value))}catch{}}
const cached=read('groceries-cache',null);
let snapshot={items:[],recipes:[],...cached},queue=read('groceries-outbox',[]),failures=read('groceries-review',[]),tokens=read('groceries-login',null);
let ready=cached!==null,synced=cached!==null,rendered=false,syncing=false,again=false,refreshPromise=null,editing=null,added=0,tab='list',importBody=null;
const staged=new Map(),rowRefs=new Map(),recipeRefs=new Map();
const uuid=()=>crypto.randomUUID(),saveQueue=()=>write('groceries-outbox',queue),saveFailures=()=>write('groceries-review',failures);
const reduced=()=>matchMedia('(prefers-reduced-motion:reduce)').matches;
const line=item=>[item.quantity,item.name].filter(Boolean).join(' ');
const plural=(n,word)=>n+' '+word+(n===1?'':'s');

function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function icon(id,cls){
  const svg=document.createElementNS(SVG,'svg'),use=document.createElementNS(SVG,'use');
  svg.setAttribute('class',cls?'i '+cls:'i');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
  use.setAttribute('href','#'+id);svg.append(use);return svg;
}
function art(id){const svg=icon(id);svg.setAttribute('class','art');svg.setAttribute('viewBox','0 0 96 96');return svg}
function tick(){
  const svg=document.createElementNS(SVG,'svg'),path=document.createElementNS(SVG,'path');
  svg.setAttribute('class','tick');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
  path.setAttribute('d','M5 12.5l4.5 4.5L19 7.5');path.setAttribute('pathLength','1');svg.append(path);return svg;
}
function button(label,cls,run){const b=el('button',label,cls);b.type='button';if(run)b.onclick=run;return b}
function place(parent,nodes){
  nodes.forEach((node,i)=>{if(parent.children[i]!==node)parent.insertBefore(node,parent.children[i]||null)});
  while(parent.children.length>nodes.length)parent.lastElementChild.remove();
}

const toasts={queue:[],current:null,timer:0,exit:0};
function toast(message,options={}){
  const item={message,ms:options.ms||6500,action:options.action,kind:options.kind};
  if(options.replace||!toasts.current)return showToast(item);
  if(!toasts.queue.some(x=>x.message===message))toasts.queue.push(item);
}
function showToast(item){
  const box=$('toast');
  clearTimeout(toasts.timer);clearTimeout(toasts.exit);
  toasts.current=item;
  box.className=item.kind==='error'?'error':'';
  box.setAttribute('role',item.kind==='error'?'alert':'status');
  box.replaceChildren(el('span',item.message,'msg'));
  if(item.action)box.append(button(item.action.label,'act',()=>{dismissToast();item.action.run()}));
  box.hidden=false;
  box.style.animation='none';box.offsetWidth;box.style.animation='';
  toasts.timer=setTimeout(dismissToast,item.ms);
}
function dismissToast(){
  clearTimeout(toasts.timer);toasts.current=null;
  const next=toasts.queue.shift(),box=$('toast');
  if(next)return showToast(next);
  box.classList.add('out');
  toasts.exit=setTimeout(()=>{box.hidden=true;box.classList.remove('out')},reduced()?0:150);
}

const themeApi=window.groceriesTheme||{state:()=>({mode:'sun',resolved:'light',next:0}),set(){},subscribe(){}};
const MODES=['sun','system','light','dark'],MODE_NAME={sun:'Sunrise & sunset',system:'System',light:'Light',dark:'Dark'},MODE_ICON={sun:'i-sunrise',system:'i-monitor',light:'i-sun',dark:'i-moon'};
const clock=new Intl.DateTimeFormat([],{hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
// Rounded up so the named minute never precedes the actual switch.
function modeText(){
  const state=themeApi.state(),name=MODE_NAME[state.mode];
  return state.mode==='sun'&&state.next?name+' · '+state.resolved+' until '+clock.format(Math.ceil(state.next/60000)*60000):name;
}
function showMode(){
  $('theme').setAttribute('aria-label','Colour mode: '+modeText()+'. Change.');
  $('theme').querySelector('use').setAttribute('href','#'+MODE_ICON[themeApi.state().mode]);
}
$('theme').onclick=()=>{
  themeApi.set(MODES[(MODES.indexOf(themeApi.state().mode)+1)%MODES.length]);
  toast('Colour mode: '+modeText(),{ms:2200,replace:true});
};
themeApi.subscribe(showMode);
showMode();

function signIn(){
  const state=uuid();
  sessionStorage.setItem('groceries-state',JSON.stringify({state,time:Date.now()}));
  location.href=location.origin+'/auth/authorize?'+new URLSearchParams({client_id:client,redirect_uri:client,response_type:'code',state});
}
async function exchange(body){
  const r=await fetch('/auth/token',{method:'POST',body:new URLSearchParams({...body,client_id:client})});
  if(!r.ok)throw Error('Sign-in was not completed.');
  const result=await r.json();
  tokens={...result,refresh_token:result.refresh_token||body.refresh_token};
  tokens.expires_at=Date.now()+tokens.expires_in*1000;
  write('groceries-login',tokens);
  return tokens;
}
const fault=(state,label,detail='')=>Object.assign(Error(label),{state,label,detail});
const say=error=>error.state?error.label+(error.detail?' · '+error.detail:''):error.message;
async function access(){
  if(!tokens)throw fault('signedout','Sign in to sync','local changes wait on this phone');
  if(tokens.expires_at<Date.now()+60000){
    if(!refreshPromise)refreshPromise=exchange({grant_type:'refresh_token',refresh_token:tokens.refresh_token}).finally(()=>refreshPromise=null);
    await refreshPromise;
  }
  return tokens.access_token;
}
async function api(path,body){
  const token=await access();
  let r;
  try{
    r=await fetch(base+'v1/'+path,{method:body?'POST':'GET',headers:{Authorization:'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});
  }catch{throw fault('offline','Cloud unreachable','changes are saved on this phone')}
  if(r.status===401){localStorage.removeItem('groceries-login');tokens=null;throw fault('signedout','Please sign in again.','local changes wait on this phone')}
  if(!r.ok){
    let detail='Cloud request failed.';
    try{const data=await r.json();detail=typeof data.detail==='string'?data.detail:'Please check the recipe fields.'}catch{}
    const error=Error(detail);error.status=r.status;throw error;
  }
  return r.json();
}

const STATE_ICON={connecting:'i-refresh',syncing:'i-refresh',ok:'i-cloud-check',offline:'i-cloud-off',signedout:'i-user',error:'i-alert'};
function setStatus(state,label,detail=''){
  const box=$('connection'),glyph=box.querySelector('.i'),text=box.querySelector('.s-label'),more=box.querySelector('.s-detail');
  const changed=box.dataset.state!==state||text.textContent!==label;
  box.dataset.state=state;
  glyph.classList.toggle('spin',state==='connecting'||state==='syncing');
  glyph.querySelector('use').setAttribute('href','#'+STATE_ICON[state]);
  text.textContent=label;more.textContent=detail;box.title=detail?label+' · '+detail:label;
  if(changed&&!reduced())box.animate([{opacity:.2},{opacity:1}],{duration:150,easing:'ease-out'});
}
function report(error){
  if(error.state)setStatus(error.state,error.label,error.detail);
  else if(error instanceof TypeError)setStatus('offline','Cloud unreachable','changes are saved on this phone');
  else setStatus('error',error.message,'will retry shortly');
}

// A permanent client error must not block the changes queued behind it, so it is parked for review.
// Auth, timeout and rate-limit responses are transient and keep the change at the head of the queue.
const rejected=error=>error.status>=400&&error.status<500&&![401,408,425,429].includes(error.status);
function reason(error){
  if(error.status===413)return 'This change was too large to send.';
  if(error.status===404)return 'This item is no longer on the cloud list.';
  return error.message;
}
function park(change,error){
  failures.push({change,error:reason(error)});saveFailures();
  queue.shift();saveQueue();
  toast('A change needs review. Your original entry is still saved on this phone.',{kind:'error',action:{label:'Review',run:openReview}});
}
function persist(){write('groceries-cache',snapshot);saveQueue()}
async function sync(){
  if(syncing){again=true;return}
  syncing=true;
  try{
    if(!navigator.onLine)throw fault('offline','Offline','changes are saved on this phone');
    if(!tokens)throw fault('signedout','Sign in to sync','local changes wait on this phone');
    setStatus('syncing','Syncing…');
    while(queue.length){
      const change=queue[0];
      try{await api('mutations',change)}
      catch(error){if(!rejected(error))throw error;park(change,error);continue}
      queue.shift();saveQueue();
    }
    snapshot={items:[],recipes:[],...await api('list')};
    AssistantDaylight.configure(snapshot.daylight);
    persist();synced=true;
    setStatus('ok','Cloud saved','works while the laptop is asleep');
  }catch(error){report(error)}
  finally{
    syncing=false;ready=true;render();
    if(again){again=false;setTimeout(sync,0)}
  }
}
function enqueue(value){queue.push({id:uuid(),created_at:new Date().toISOString(),...value});saveQueue();render();sync()}

// Ticking and removing wait HOLD ms before reaching the outbox so a stray tap can be undone;
// leaving the page commits immediately so nothing is lost.
function hold(change,message){
  const id=change.target;
  staged.set(id,{change,timer:setTimeout(()=>commit(id),HOLD)});
  render();
  toast(message,{ms:HOLD,replace:true,action:{label:'Undo',run:()=>cancel(id)}});
}
function commit(id){
  const entry=staged.get(id);
  if(!entry)return;
  clearTimeout(entry.timer);staged.delete(id);enqueue(entry.change);
}
function cancel(id){
  const entry=staged.get(id);
  if(!entry)return;
  clearTimeout(entry.timer);staged.delete(id);render();
}
function commitAll(){for(const id of [...staged.keys()])commit(id)}

// Mirrors split_items in groceries/store.py; the two must keep splitting identically.
function split(text){
  const compounds=new Map();
  for(const phrase of ['mac and cheese','salt and pepper','oil and vinegar']){
    const key='COMPOUND'+compounds.size;
    if(new RegExp(phrase,'i').test(text)){compounds.set(key,phrase);text=text.replace(new RegExp(phrase,'ig'),key)}
  }
  return text.split(/\s*(?:,|;|\band\b|\bund\b)\s*/i).map(x=>x.trim()).filter(Boolean).map(x=>compounds.get(x)||x);
}

function overlay(){
  const items=snapshot.items.map(x=>({...x}));
  const apply=(change,held)=>{
    if(change.operation==='add')for(const [i,item] of change.items.entries())items.push({...item,id:'pending-'+change.id+'-'+i,complete:0,version:0});
    if(change.operation==='complete'){const item=items.find(x=>x.id===change.target);if(item){item.complete=change.complete;if(held)item.held=true}}
    if(change.operation==='delete'){const i=items.findIndex(x=>x.id===change.target);if(i>=0)items.splice(i,1)}
  };
  for(const change of queue)apply(change,false);
  for(const entry of staged.values())apply(entry.change,true);
  return items;
}

function nameNode(item){
  const name=el('span',undefined,'name');
  if(item.quantity)name.append(el('span',item.quantity,'q'),' ');
  name.append(document.createTextNode(item.name));
  return name;
}
function buildRow(){
  const ref={item:null,locked:false,nameKey:''};
  const node=el('div',undefined,'item'),row=el('div',undefined,'row'),toggle=el('label',undefined,'toggle'),input=el('input'),box=el('span',undefined,'cb'),copy=el('span',undefined,'copy'),meta=el('span'),chip=el('span',undefined,'pill warning');
  const search=el('a',undefined,'row-btn'),remove=button(undefined,'row-btn remove',()=>{if(!ref.locked)hold({operation:'delete',target:ref.item.id,version:ref.item.version},'Removed '+ref.item.name+'.')}),undo=button('Undo','undo',()=>cancel(ref.item.id));
  input.type='checkbox';box.append(tick());
  chip.append(icon('i-phone'),document.createTextNode('Saved on phone'));meta.append(chip);
  search.target='_blank';search.rel='noopener noreferrer';search.title='Search products; availability depends on the selected store';search.append(icon('i-search'));
  remove.append(icon('i-trash'));undo.prepend(icon('i-undo'));
  copy.append(el('span'),meta);toggle.append(input,box,copy);row.append(toggle,search,remove,undo);node.append(row);
  input.onchange=()=>{
    const item=ref.item;
    if(staged.has(item.id))return cancel(item.id);
    hold({operation:'complete',target:item.id,version:item.version,complete:!item.complete},(item.complete?'Restored ':'Marked bought: ')+item.name+(item.complete?' to your list.':'.'));
  };
  return Object.assign(ref,{node,input,copy,chip,search,remove});
}
function updateRow(ref,item){
  const queued=queue.some(x=>x.target===item.id),held=!!item.held;
  ref.item=item;ref.locked=!item.version||queued||held;
  ref.node.toggleAttribute('data-staged',held);
  ref.input.checked=!!item.complete;
  ref.input.disabled=(!item.version||queued)&&!held;
  const key=(item.quantity||'')+'\u0000'+item.name;
  if(ref.nameKey!==key){ref.nameKey=key;ref.copy.firstChild.replaceWith(nameNode(item))}
  ref.chip.hidden=!!item.version;
  const href='https://shop.rewe.de/productList?search='+encodeURIComponent(item.name);
  if(ref.search.href!==href)ref.search.href=href;
  ref.search.setAttribute('aria-label','Search REWE for '+item.name);
  ref.remove.setAttribute('aria-label','Remove '+item.name);
  ref.remove.setAttribute('aria-disabled',String(ref.locked));
}
const bought=item=>item.held?!item.complete:!!item.complete;
function leave(node,box,moving){
  let gone=node;
  if(moving){
    gone=node.cloneNode(true);
    gone.querySelector('input').checked=node.querySelector('input').checked;
    gone.classList.remove('enter');box.insertBefore(gone,node);
  }
  gone.classList.add('leaving');gone.inert=true;
  setTimeout(()=>gone.remove(),reduced()?0:260);
}
function placeRows(rows){
  for(const [box,done] of [[$('shopping'),false],[$('completed'),true]]){
    const want=rows.filter(x=>bought(x.item)===done).map(x=>x.ref.node);
    for(const node of [...box.children])if(!node.classList.contains('leaving')&&!want.includes(node))leave(node,box,rows.some(x=>x.ref.node===node));
    want.forEach((node,i)=>{
      const live=[...box.children].filter(x=>!x.classList.contains('leaving'));
      if(live[i]!==node)box.insertBefore(node,live[i]||null);
    });
  }
}
function skeleton(count){
  const box=el('div',undefined,'card skeleton');box.setAttribute('aria-hidden','true');
  for(let i=0;i<count;i++){const row=el('div',undefined,'skel-row');row.append(el('span',undefined,'skel'),el('span',undefined,'skel w'+(i%3)));box.append(row)}
  return box;
}
function skeletonCards(count){
  const box=el('div');box.setAttribute('aria-hidden','true');
  for(let i=0;i<count;i++){const card=el('div',undefined,'card skel-card');card.append(el('span',undefined,'skel w1'),el('span',undefined,'skel w0'));box.append(card)}
  return box;
}
function empty(art_id,title,text,action){
  const box=el('div',undefined,'card empty');
  box.append(art(art_id),el('h3',title),el('p',text));
  if(action)box.append(button(action.label,'btn tonal',action.run));
  return box;
}
function setState(box,kind,build){
  if(box.dataset.kind===kind)return;
  box.dataset.kind=kind;box.replaceChildren();
  if(kind)box.append(build(kind));
}
// Once a queued add syncs, the server id replaces the temporary one; the row is reused so it does not flicker.
function renderList(){
  const items=overlay(),rows=[],present=new Set(items.map(x=>x.id));
  const vanished=[...rowRefs].filter(([id])=>id.startsWith('pending-')&&!present.has(id));
  for(const item of items){
    let ref=rowRefs.get(item.id);
    if(!ref){
      const i=vanished.findIndex(([,old])=>old.item.name===item.name);
      if(i>=0){ref=vanished.splice(i,1)[0][1];rowRefs.set(item.id,ref)}
    }
    if(!ref){
      ref=buildRow();rowRefs.set(item.id,ref);
      if(rendered){ref.node.classList.add('enter');ref.node.addEventListener('animationend',()=>ref.node.classList.remove('enter'),{once:true})}
    }
    updateRow(ref,item);rows.push({ref,item});
  }
  for(const id of [...rowRefs.keys()])if(!present.has(id))rowRefs.delete(id);
  placeRows(rows);
  const open=rows.filter(x=>!bought(x.item)).length,done=rows.length-open;
  $('bought').hidden=!done;$('bought-count').textContent='('+done+')';
  $('list').setAttribute('aria-busy',String(!ready));
  $('store').hidden=!ready;
  const kind=!ready?'skeleton':open?'':done?'done':!tokens?'local':synced?'clear':'unavailable';
  setState($('list-state'),kind,k=>({
    skeleton:()=>skeleton(4),
    done:()=>empty('art-bag','Everything is bought','Open Bought below if you need to put something back.'),
    clear:()=>empty('art-bag','Your list is clear','Add something above.'),
    unavailable:()=>empty('art-bag','Your list has not loaded yet','Anything you add now is saved on this phone and syncs later.',{label:'Try again',run:sync}),
    local:()=>empty('art-bag','Your list is clear','Add something above. Sign in to keep it in sync across your devices.',{label:'Sign in',run:signIn})
  })[k]());
}
function renderStore(){
  const box=$('store'),store=snapshot.store||{},sig=JSON.stringify(store);
  if(box.dataset.sig===sig)return;
  box.dataset.sig=sig;box.replaceChildren();
  const tile=el('span',undefined,'tile');tile.append(icon('i-store'));
  if(!store.name){box.append(tile,el('p','REWE store details will appear after syncing.'));return}
  box.append(tile,el('strong',store.name),el('p',store.address||''));
  if(/^https:\/\/www\.rewe\.de\//.test(store.url)){
    const a=el('a','Store details');a.href=store.url;a.target='_blank';a.rel='noopener noreferrer';a.append(icon('i-link-out'));box.append(a);
  }
  box.append(el('p','Product links open REWE search. Stock at this branch has not been verified.','plain'));
}

const ingredientKey=item=>(item.quantity||'')+'\u0000'+item.name;
const TILES=['','green','amber','blue'];
const tileFor=id=>TILES[[...id].reduce((hash,c)=>(hash*31+c.charCodeAt(0))>>>0,7)%TILES.length];
function buildRecipe(recipe,previous){
  const unchecked=previous?previous.unchecked:new Set();
  const node=el('details',undefined,'card recipe'),summary=el('summary'),head=el('div',undefined,'grow'),meta=el('div',undefined,'r-meta');
  node.open=previous?previous.node.open:false;
  meta.append(el('span',plural(recipe.ingredients.length,'ingredient')));
  if(recipe.pending){const chip=el('span',undefined,'pill warning');chip.append(icon('i-phone'),document.createTextNode('Saved on phone'));meta.append(chip)}
  const tile=el('span',undefined,('tile '+tileFor(recipe.id)).trim());tile.append(icon('i-book'));
  head.append(el('div',recipe.title,'r-title'),meta);summary.append(tile,head,icon('i-chev-down','chev'));

  const body=el('div',undefined,'recipe-body'),pick=el('div',undefined,'pickhead'),count=el('span'),toggleAll=button('','link-btn'),choice=el('div',undefined,'ingredients-choice');
  const addLabel=el('span'),add=button(undefined,'btn primary');
  const boxes=recipe.ingredients.map(item=>{
    const label=el('label',undefined,'toggle'),input=el('input'),box=el('span',undefined,'cb'),copy=el('span',undefined,'copy');
    input.type='checkbox';input.checked=!unchecked.has(ingredientKey(item));box.append(tick());copy.append(nameNode(item));
    input.onchange=()=>{if(input.checked)unchecked.delete(ingredientKey(item));else unchecked.add(ingredientKey(item));refresh()};
    label.append(input,box,copy);choice.append(label);return input;
  });
  function refresh(){
    const n=boxes.filter(x=>x.checked).length;
    count.textContent=n+' of '+boxes.length+' selected';
    toggleAll.textContent=n===boxes.length?'Select none':'Select all';
    addLabel.textContent=n?'Add '+n+' to list':'Add to list';
    add.disabled=!n;
  }
  toggleAll.onclick=()=>{
    const target=boxes.some(x=>!x.checked);
    recipe.ingredients.forEach((item,i)=>{boxes[i].checked=target;if(target)unchecked.delete(ingredientKey(item));else unchecked.add(ingredientKey(item))});
    refresh();
  };
  add.append(icon('i-cart'),addLabel);
  add.onclick=()=>{
    const items=recipe.ingredients.filter((_,i)=>boxes[i].checked).map(x=>({name:x.name,quantity:x.quantity||''}));
    if(!items.length)return toast('Choose at least one ingredient.',{kind:'error'});
    enqueue({operation:'add',items});
    added+=items.length;showBadge();
    toast('Added '+plural(items.length,'ingredient')+' to your list.',{replace:true,action:{label:'View list',run:()=>showTab('list')}});
  };
  const edit=button('Edit','btn tonal',()=>openRecipe(recipe));
  edit.prepend(icon('i-edit'));edit.disabled=!!recipe.pending;
  pick.append(count,toggleAll);
  const foot=el('div',undefined,'recipe-foot');foot.append(add,edit);
  body.append(pick,choice,foot);
  if(recipe.instructions&&recipe.instructions.trim()){const note=el('div',recipe.instructions,'recipe-note');note.prepend(el('strong','Method'));body.append(note)}
  if(/^https?:\/\//.test(recipe.source)){const a=el('a','Original recipe','recipe-link');a.href=recipe.source;a.target='_blank';a.rel='noopener noreferrer';a.append(icon('i-link-out'));body.append(a)}
  node.append(summary,body);refresh();
  return {node,unchecked};
}
// A card is rebuilt only when its recipe changed, so ingredient choices and the open state survive background syncs.
function renderRecipes(){
  const recipes=new Map(snapshot.recipes.map(x=>[x.id,x])),nodes=[],seen=new Set();
  for(const change of queue)if(change.operation==='recipe_save')recipes.set(change.recipe.id,{...change.recipe,version:change.version||0,pending:true});
  for(const recipe of recipes.values()){
    const sig=JSON.stringify([recipe.title,recipe.ingredients,recipe.instructions,recipe.source,recipe.version,!!recipe.pending]);
    let ref=recipeRefs.get(recipe.id);
    if(!ref||ref.sig!==sig){ref={...buildRecipe(recipe,ref),sig};recipeRefs.set(recipe.id,ref)}
    nodes.push(ref.node);seen.add(recipe.id);
  }
  for(const id of [...recipeRefs.keys()])if(!seen.has(id))recipeRefs.delete(id);
  place($('recipe-list'),nodes);
  setState($('recipes-state'),!ready?'skeleton':recipes.size?'':tokens&&!synced?'unavailable':'empty',kind=>({
    skeleton:()=>skeletonCards(2),
    unavailable:()=>empty('art-book','Recipes have not loaded yet','They appear as soon as your list syncs.',{label:'Try again',run:sync}),
    empty:()=>empty('art-book','No recipes saved yet','Paste ingredients from AnyList or add your own.',{label:'New recipe',run:()=>openRecipe()})
  })[kind]());
}

function openRecipe(recipe){
  editing=recipe||null;
  $('recipe-editor').hidden=false;
  $('editor-title').textContent=recipe?'Edit recipe':'Save a recipe';
  $('recipe-title').value=recipe?.title||'';
  $('recipe-ingredients').value=recipe?.ingredients.map(line).join('\n')||'';
  $('recipe-instructions').value=recipe?.instructions||'';
  $('recipe-source').value=recipe?.source||'';
  $('recipe-editor').scrollIntoView({behavior:reduced()?'auto':'smooth',block:'start'});
  $('recipe-title').focus({preventScroll:true});
}
$('new-recipe').onclick=()=>openRecipe();
$('cancel-recipe').onclick=()=>$('recipe-editor').hidden=true;
$('add').onsubmit=e=>{
  e.preventDefault();
  const names=split($('items').value);
  if(!names.length)return;
  enqueue({operation:'add',items:names.map(name=>({name,quantity:''}))});
  $('items').value='';$('items').focus();
};
$('recipe-editor').onsubmit=e=>{
  e.preventDefault();
  const ingredients=$('recipe-ingredients').value.split('\n').map(x=>x.trim()).filter(Boolean).map(text=>{
    const m=text.match(/^([\d.,/½¼¾]+\s*(?:g|kg|ml|l|tbsp|tsp|cups?|pieces?)?\s+)\s*(.+)$/i);
    return m?{quantity:m[1].trim(),name:m[2]}:{quantity:'',name:text};
  });
  if(!ingredients.length)return toast('Add at least one ingredient.',{kind:'error'});
  enqueue({operation:'recipe_save',...(editing?{version:editing.version}:{}),recipe:{id:editing?.id||uuid(),title:$('recipe-title').value.trim(),ingredients,instructions:$('recipe-instructions').value,source:$('recipe-source').value}});
  $('recipe-editor').hidden=true;
  toast('Recipe saved.');
};

async function busy(control,work){
  control.disabled=true;control.setAttribute('aria-busy','true');
  try{await work()}catch(error){toast(say(error),{kind:'error'})}
  finally{control.disabled=false;control.removeAttribute('aria-busy')}
}
$('import-content').oninput=$('import-source').oninput=()=>{importBody=null;$('commit-import').hidden=true};
$('preview-import').onclick=()=>busy($('preview-import'),async()=>{
  const body={content:$('import-content').value,format:'auto',source:$('import-source').value};
  const preview=await api('recipes/import/preview',body);
  importBody=body;
  const box=$('import-preview'),count=el('span',undefined,'pill success');
  count.append(icon('i-check'),document.createTextNode(plural(preview.count,'recipe')+' found'));
  box.replaceChildren(count);
  for(const recipe of preview.recipes){
    const card=el('div',undefined,'preview');
    card.append(el('h3',recipe.title),el('pre',recipe.ingredients.map(line).join('\n')+'\n\n'+recipe.instructions));
    box.append(card);
  }
  for(const warning of preview.warnings){const w=el('p',warning,'warn');w.prepend(icon('i-alert'));box.append(w)}
  $('commit-import').hidden=false;
});
$('commit-import').onclick=()=>busy($('commit-import'),async()=>{
  if(!importBody)return;
  const saved=await api('recipes/import/commit',importBody);
  toast('Imported '+plural(saved.saved_ids.length,'recipe')+'. Choose ingredients to add to your list.');
  importBody=null;$('commit-import').hidden=true;$('import-preview').replaceChildren();$('import-content').value='';$('recipe-import').open=false;
  await sync();
});

let reviewSig='';
function renderReview(){
  const panel=$('review'),sig=JSON.stringify(failures);
  panel.hidden=!failures.length;
  if(sig===reviewSig)return;
  reviewSig=sig;panel.replaceChildren();
  if(!failures.length)return;
  const n=failures.length,summary=el('summary'),label=el('span',n+(n===1?' saved change needs':' saved changes need')+' review','grow');
  summary.append(icon('i-alert'),label,icon('i-chev-down','chev'));panel.append(summary);
  for(const [index,failure] of failures.entries()){
    const card=el('article'),change=failure.change,actions=el('div',undefined,'actions');
    const detail=change.recipe?change.recipe.title+'\n'+change.recipe.ingredients.map(line).join('\n'):(change.items||[]).map(x=>x.name).join(', ')||'Shopping item changed on another device.';
    card.append(el('strong',failure.error),el('pre',detail));
    actions.append(
      button('Retry with current list','btn tonal',()=>{
        const next={...change,id:uuid()};
        const row=snapshot.items.find(x=>x.id===next.target)||snapshot.recipes.find(x=>x.id===(next.recipe?.id||next.target));
        if(row)next.version=row.version;
        failures.splice(index,1);saveFailures();queue.push(next);saveQueue();render();sync();
      }),
      button('Discard','btn ghost',()=>{
        if(!confirm('Discard this saved change?'))return;
        failures.splice(index,1);saveFailures();render();
      })
    );
    card.append(actions);panel.append(card);
  }
}
function openReview(){
  const panel=$('review');
  panel.open=true;panel.scrollIntoView({behavior:reduced()?'auto':'smooth',block:'center'});
}

function renderChrome(){
  const n=queue.length,pill=$('pending');
  pill.hidden=!n;
  if(n&&pill.dataset.n!==String(n)){
    pill.dataset.n=String(n);
    pill.replaceChildren(icon('i-phone'),document.createTextNode(n+' saved on phone'));
    pill.title=plural(n,'change')+(n===1?' is':' are')+' saved on this phone and will sync when possible';
  }
  const cell=$('signin');
  cell.querySelector('strong').textContent=tokens?'Sign out':'Sign in';
  cell.querySelector('small').textContent=tokens?'Your local list stays on this phone':'Keep your list in sync across devices';
  cell.querySelector('.tile').className=tokens?'tile red':'tile';
  cell.querySelector('use').setAttribute('href',tokens?'#i-sign-out':'#i-sign-in');
  cell.classList.toggle('danger',!!tokens);
}
function render(){renderList();renderStore();renderRecipes();renderReview();renderChrome();if(ready)rendered=true}

const tabList=document.querySelector('[role=tablist]'),tabButtons=[...tabList.querySelectorAll('[role=tab]')];
function showBadge(){const badge=$('list-badge');badge.hidden=!added||tab==='list';badge.textContent='+'+added}
function showTab(name,focus){
  const changed=name!==tab;
  tab=name;tabList.dataset.active=name;
  for(const control of tabButtons){
    const on=control.dataset.tab===name,panel=$(control.dataset.tab);
    control.setAttribute('aria-selected',String(on));control.tabIndex=on?0:-1;panel.hidden=!on;
    if(on&&changed&&!reduced()){panel.classList.remove('page-in');panel.offsetWidth;panel.classList.add('page-in')}
    if(on&&focus)control.focus();
  }
  $('add').hidden=name!=='list';
  if(name==='list')added=0;
  showBadge();
  if(changed)window.scrollTo({top:0,behavior:'instant'});
}
tabButtons.forEach((control,i)=>{
  control.onclick=()=>showTab(control.dataset.tab);
  control.onkeydown=e=>{
    const to={ArrowRight:i+1,ArrowLeft:i-1,Home:0,End:tabButtons.length-1}[e.key];
    if(to===undefined)return;
    e.preventDefault();showTab(tabButtons[(to+tabButtons.length)%tabButtons.length].dataset.tab,true);
  };
});

const sheet=$('phone-setup');
let pairing=null,pairingTimer=0,pairingBusy=false,pairingRun=0;
function clearPairing(){pairingRun++;pairingBusy=false;clearInterval(pairingTimer);pairing=null;$('pair-code').textContent=''}
function setExpiry(kind,text,glyph){
  const pill=$('pair-expiry');
  pill.className='pill '+kind;pill.querySelector('span').textContent=text;pill.querySelector('use').setAttribute('href','#'+glyph);
}
function tickPairing(){
  if(!pairing)return;
  const left=Math.max(0,Math.ceil((pairing.expiresAt-Date.now())/1000));
  if(left)return setExpiry('info','Expires in '+Math.floor(left/60)+':'+String(left%60).padStart(2,'0'),'i-clock');
  clearInterval(pairingTimer);
  $('pair-code-box').dataset.state='expired';
  $('pair-code-box').querySelector('[data-copy]').disabled=true;
  setExpiry('danger','Code expired','i-alert');
}
async function pair(){
  if(!tokens)return toast('Sign in to create a pairing code.',{kind:'error',action:{label:'Sign in',run:signIn}});
  if(pairingBusy)return;
  clearPairing();pairingBusy=true;
  const run=pairingRun;
  $('pair-server').textContent=location.origin;
  $('pair-code-box').dataset.state='loading';
  $('pair-code-box').querySelector('[data-copy]').disabled=true;
  setExpiry('info','Getting your code…','i-refresh');
  if(!sheet.open)sheet.showModal();
  try{
    const paired=await api('mobile/pairing',{});
    if(run!==pairingRun)return;
    pairing={expiresAt:Date.now()+(paired.expires_in||600)*1000};
    $('pair-code').textContent=paired.code;
    $('pair-code-box').dataset.state='ready';
    $('pair-code-box').querySelector('[data-copy]').disabled=false;
    tickPairing();pairingTimer=setInterval(tickPairing,1000);
  }catch(error){
    if(run!==pairingRun)return;
    if(sheet.open)sheet.close();
    toast(say(error),{kind:'error'});
  }finally{if(run===pairingRun)pairingBusy=false}
}
async function copyText(text){
  try{await navigator.clipboard.writeText(text);return true}catch{}
  const area=el('textarea',text,'sr');
  area.setAttribute('readonly','');document.body.append(area);area.select();
  let ok=false;
  try{ok=document.execCommand('copy')}catch{}
  area.remove();return ok;
}
document.querySelectorAll('[data-copy]').forEach(control=>control.onclick=async()=>{
  const ok=await copyText($(control.dataset.copy).textContent),label=control.querySelector('span'),glyph=control.querySelector('use');
  label.textContent=ok?'Copied':'Copy failed';glyph.setAttribute('href',ok?'#i-check':'#i-copy');
  clearTimeout(control.reset);
  control.reset=setTimeout(()=>{label.textContent='Copy';glyph.setAttribute('href','#i-copy')},1800);
});
$('pair-phone').onclick=pair;
$('pair-renew').onclick=pair;
$('pair-close').onclick=()=>sheet.close();
sheet.onclick=e=>{if(e.target===sheet)sheet.close()};
sheet.onclose=clearPairing;

$('signin').onclick=()=>{
  if(!tokens)return signIn();
  if(queue.length&&!confirm('There are unsynced changes on this phone. Sign out and keep them here?'))return;
  localStorage.removeItem('groceries-login');tokens=null;
  setStatus('signedout','Signed out','your local list remains on this phone');render();
};
$('refresh').onclick=sync;
window.addEventListener('online',sync);
window.addEventListener('offline',()=>setStatus('offline','Offline','changes are saved on this phone'));
window.addEventListener('pagehide',commitAll);
document.addEventListener('visibilitychange',()=>{if(document.hidden)commitAll();else sync()});
if('IntersectionObserver'in window)new IntersectionObserver(([entry])=>$('bar').classList.toggle('stuck',!entry.isIntersecting)).observe(document.querySelector('.top'));

(async()=>{
  const params=new URLSearchParams(location.search);
  if(params.has('code')){
    const expected=JSON.parse(sessionStorage.getItem('groceries-state')||'null'),code=params.get('code');
    history.replaceState(null,'',base);sessionStorage.removeItem('groceries-state');
    try{
      if(!expected||params.get('state')!==expected.state||Date.now()-expected.time>600000)throw Error('Sign-in session expired. Try again.');
      await exchange({grant_type:'authorization_code',code});
    }catch(error){toast(error.message,{kind:'error'})}
  }
  render();await sync();
  if('serviceWorker'in navigator)navigator.serviceWorker.register(base+'sw.js',{scope:base}).catch(()=>{});
  setInterval(sync,30000);
})();
