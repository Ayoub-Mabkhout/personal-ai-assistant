'use strict';
const $=id=>document.getElementById(id),client=location.origin+'/tasks/',params=new URLSearchParams(location.search);
const local=()=>localStorage,session=()=>sessionStorage;
function read(key,store=local){try{return JSON.parse(store().getItem(key)||'null')}catch{return null}}
function write(key,value,store=local){try{store().setItem(key,JSON.stringify(value))}catch{}}
function remove(key,store=local){try{store().removeItem(key)}catch{}}
const validTarget=value=>/^(agent|command)\/[A-Za-z0-9_-]{8,64}$/.test(value||'');
let target=params.get('task')||(location.pathname.startsWith('/tasks/agent/')||location.pathname.startsWith('/tasks/command/')?location.pathname.slice(7):location.hash.slice(1))||'',tokens=read('task-login')||read('task-login',session),busy=false,followupToken=null,sending=false;
let viewToken=params.get('view')||read('task-view:'+target);
if(tokens){write('task-login',tokens);remove('task-login',session)}
if(validTarget(target))write('task-target',target,session);
if(params.get('view')&&validTarget(target)){write('task-view:'+target,viewToken);history.replaceState(null,'','/tasks/'+target)}

const labels={queued:'Queued',running:'In progress',completed:'Completed',failed:'Failed',needs_input:'Needs your input',cancelled:'Cancelled',expired:'Expired'};
const events={submitted:'Acknowledged and saved',claimed:'Started on the laptop',lease_expired:'Connection interrupted; returned to the queue',completed:'Completed',failed:'Failed',needs_input:'Needs your input',cancelled:'Cancelled',expired:'Expired'};
const states={queued:['info','clock'],running:['info','arc'],completed:['success','ok'],failed:['danger','x'],needs_input:['warning','alert'],cancelled:['neutral','stop'],expired:['neutral','clock']};
const eventTones={submitted:'info',claimed:'info',lease_expired:'warning',completed:'success',failed:'danger',needs_input:'warning',cancelled:'neutral',expired:'neutral'};
const terminal=new Set(['completed','failed','cancelled','expired']);
const stateTone=state=>(states[state]||['neutral','clock'])[0],stateIcon=state=>(states[state]||['neutral','clock'])[1];

const fatal=message=>Object.assign(Error(message),{final:true});
const soft=message=>Object.assign(Error(message),{friendly:true});
const timeout=()=>AbortSignal.timeout?.(15000);
const describe=error=>error.final||error.friendly?error.message:navigator.onLine===false?'You are offline. This page updates again when you reconnect.':'Could not reach the server. Trying again shortly.';

const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!=null)node.textContent=text;return node};
function icon(name){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),use=document.createElementNS('http://www.w3.org/2000/svg','use');svg.setAttribute('class','i');svg.setAttribute('aria-hidden','true');use.setAttribute('href','#i-'+name);svg.append(use);return svg}
function chip(state){const node=el('span','chip s-'+stateTone(state));node.append(icon(stateIcon(state)),el('span','',labels[state]||state));return node}
const clip=(text,limit)=>text.length>limit?text.slice(0,limit)+'...':text;

const clock=new Intl.DateTimeFormat(undefined,{hour:'numeric',minute:'2-digit'}),relative=new Intl.RelativeTimeFormat(undefined,{numeric:'auto'});
function dayLabel(date){
  const now=new Date(),days=Math.round((new Date(now.getFullYear(),now.getMonth(),now.getDate())-new Date(date.getFullYear(),date.getMonth(),date.getDate()))/864e5);
  if(days===0||days===1){const word=relative.format(days?-1:0,'day');return word.charAt(0).toLocaleUpperCase()+word.slice(1)}
  return date.toLocaleDateString(undefined,date.getFullYear()===now.getFullYear()?{month:'short',day:'numeric'}:{year:'numeric',month:'short',day:'numeric'});
}
const when=seconds=>{const date=new Date(seconds*1000);return dayLabel(date)+', '+clock.format(date)};
function timeNode(seconds,timeOnly){const date=new Date(seconds*1000),node=el('time','',timeOnly?clock.format(date):when(seconds));node.dateTime=date.toISOString();node.title=date.toLocaleString();return node}

const authButton=()=>{$('signin').hidden=!!viewToken;$('signin').textContent=tokens?'Sign out':'Sign in'};
function signIn(){const state=crypto.randomUUID();write('task-oauth-state:'+state,{state,target,time:Date.now()});const redirect=client+(validTarget(target)?'?task='+encodeURIComponent(target):'');location.href=location.origin+'/auth/authorize?'+new URLSearchParams({client_id:client,redirect_uri:redirect,response_type:'code',state})}
async function exchange(body){const response=await fetch('/auth/token',{method:'POST',body:new URLSearchParams({...body,client_id:client})});if(!response.ok){tokens=null;remove('task-login');authButton();throw fatal('Sign in again to view this task.')}const next=await response.json();tokens={...next,refresh_token:next.refresh_token||body.refresh_token,expires_at:Date.now()+next.expires_in*1000};write('task-login',tokens)}
let accessRefresh=null;
async function access(){if(!tokens)throw fatal('Sign in with your Home Assistant account to view this task.');if(tokens.expires_at<Date.now()+60000){if(!accessRefresh)accessRefresh=exchange({grant_type:'refresh_token',refresh_token:tokens.refresh_token}).finally(()=>accessRefresh=null);await accessRefresh}return tokens.access_token}
let preferencesLoaded=false,preferencesLoading=false;
async function loadPreferences(){if(preferencesLoaded||preferencesLoading||!tokens)return;preferencesLoading=true;try{const r=await fetch('/tasks/v1/preferences',{headers:{Authorization:'Bearer '+await access()},cache:'no-store',signal:timeout()});if(r.ok){AssistantDaylight.configure((await r.json()).daylight);preferencesLoaded=true}}catch{}finally{preferencesLoading=false}}
async function taskResponse(){
  loadPreferences();
  const headers=viewToken?{'X-Task-View':viewToken}:{Authorization:'Bearer '+await access()};
  let response=await fetch('/tasks/v1/'+target,{headers,cache:'no-store',signal:timeout()});
  if(response.status===401&&viewToken){remove('task-view:'+target);viewToken=null;authButton();if(tokens)response=await fetch('/tasks/v1/'+target,{headers:{Authorization:'Bearer '+await access()},cache:'no-store',signal:timeout()})}
  if(response.status===401){tokens=null;remove('task-login');authButton();throw fatal('This task link is unavailable. Sign in to view the answer.')}
  return response;
}

function showView(view){
  $('loading').hidden=view!=='loading';$('notice').hidden=view!=='notice';
  $('task-history-section').hidden=view!=='history';$('task-detail-content').hidden=view!=='detail';
}
function setMode(){
  const detail=!!target;
  $('page-title').textContent=detail?'Task details':'Task history';$('eyebrow').textContent=detail?'Assistant task':'Assistant';
  $('nav-task').hidden=!detail;$('nav-task').href=validTarget(target)?'/tasks/'+target:'/tasks/';
  for(const link of document.querySelectorAll('.pillnav a'))link.removeAttribute('aria-current');
  (detail?$('nav-task'):$('nav-history')).setAttribute('aria-current','page');
  document.title=detail?'Task details':'Task history';
}
function setConnection(text,tone='info'){
  $('connection').hidden=!text;$('connection').className='note s-'+tone;$('connection-text').textContent=text;
  $('connection-icon').setAttribute('href','#i-'+(tone==='info'?'clock':'alert'));
}
function fillNotice(root,{title,text,action,run}){
  root.querySelector('.n-title').textContent=title;root.querySelector('.n-text').textContent=text;
  const button=root.querySelector('.n-action');button.hidden=!action;button.textContent=action||'';button.onclick=run||null;
}
function showNotice(options){fillNotice($('notice'),options);showView('notice')}
const signInNotice=(title,text)=>showNotice({title,text,action:'Sign in',run:signIn});

// Detail polling: only while the task is active and the tab is visible.
let pollTimer=0,failures=0,again=false,rendered=false,seen={},knownTurns=new Set(),copyText={};
function schedule(ms){clearTimeout(pollTimer);if(target&&!document.hidden)pollTimer=setTimeout(refresh,ms)}
const changed=(key,value)=>{const signature=JSON.stringify(value);if(seen[key]===signature)return false;seen[key]=signature;return true};
function resetDetail(){rendered=false;seen={};knownTurns.clear();copyText={};failures=0;clearTimeout(pollTimer);setMode();showView('loading')}
function swapText(node,text){if(node.textContent===text)return;node.textContent=text;if(rendered){node.classList.remove('swap');void node.offsetWidth;node.classList.add('swap')}}

async function refresh(){
  if(!target)return loadHistory(historyLoaded?'merge':'fresh');
  if(document.hidden)return;
  if(busy){again=true;return}
  busy=true;
  try{
    if(!validTarget(target))throw fatal('Invalid task link.');
    const response=await taskResponse();
    if(!response.ok)throw response.status===404?fatal('Task not found.'):soft('Task status is temporarily unavailable.');
    const task=await response.json();
    if(!tokens&&!viewToken)return;
    const state=renderTask(task);
    failures=0;setConnection('');authButton();
    if(terminal.has(state))clearTimeout(pollTimer);else schedule(5000);
  }catch(error){
    failures++;authButton();
    if(error.final&&!rendered)showNotice(/Sign in/.test(error.message)?{title:'Sign in to continue',text:error.message,action:'Sign in',run:signIn}:{title:'Task unavailable',text:error.message});
    else setConnection(describe(error),error.final?'danger':'warning');
    if(!error.final){if(!rendered)showView('loading');schedule(Math.min(5000*2**failures,30000))}
  }finally{busy=false;if(again){again=false;refresh()}}
}

function renderTask(task){
  const state=task.conversation_state||task.state,tone=stateTone(state),laptop=task.connection?.laptop;
  followupToken=task.followup_token;
  swapText($('status'),labels[state]||state);
  $('status-chip').className='chip s-'+tone;$('hero').className='hero card s-'+tone;$('status-icon').setAttribute('href','#i-'+stateIcon(state));
  swapText($('state-note'),stateNote(task,state,laptop));
  $('updated').textContent='Updated '+when(task.conversation_updated||task.updated);
  $('activity-bar').hidden=!(state==='running'&&laptop!=='unavailable');
  $('day').textContent=dayLabel(new Date(task.created*1000));
  $('request').textContent=task.request;$('request-meta').textContent='You · '+when(task.created);
  renderResult(task);
  $('turns-section').hidden=!task.turns?.length;
  if(changed('turns',task.turns))renderTurns(task.turns||[]);
  $('activity-section').hidden=!task.history?.length;
  if(changed('history',task.history))renderTimeline(task.history||[]);
  $('task-id').textContent='Task '+task.id;
  syncComposer(task);
  document.title=(labels[state]||state)+' · Task details';
  showView('detail');rendered=true;
  if($('instruction').disabled)growField();
  return state;
}
function stateNote(task,state,laptop){
  if(state==='queued')return laptop==='unavailable'?'Laptop offline. Your task is saved and waiting.':laptop==='blocked'?'The laptop cannot run tasks right now. Your task is saved.':'Waiting to start.';
  if(state==='running')return laptop==='unavailable'?'Laptop disconnected. Waiting for it to reconnect.':'The laptop is working on your task.';
  if(state==='needs_input')return task.can_followup?'The assistant needs your input. Reply below to continue.':'The assistant needs your input to continue.';
  return {completed:task.summary?'Finished. The answer is below.':'Finished.',failed:'This task did not finish.',cancelled:'This task was cancelled.',expired:'This task expired.'}[state]||'';
}

function renderResult(task){
  $('result-section').hidden=!task.summary;
  $('result-title').textContent={needs_input:'Your input is needed',failed:'Details'}[task.state]||'Result';
  $('result-title').className={needs_input:'s-warning',failed:'s-danger'}[task.state]||'';
  if(changed('result',task.summary))renderText($('result'),task.summary||'');
  copyText.result=task.summary||'';
  const withTurns=!!task.turns?.length;
  $('result-chip').hidden=!withTurns;
  if(withTurns){$('result-chip').replaceChildren(...chip(task.state).childNodes);$('result-chip').className='chip s-'+stateTone(task.state)}
  $('result-meta').textContent='Assistant · '+when(task.updated);
}
$('copy-result').onclick=event=>copy(copyText.result,event.currentTarget);

async function copy(text,button){
  try{await navigator.clipboard.writeText(text)}
  catch{const field=el('textarea');field.value=text;field.className='sr-only';document.body.append(field);field.select();try{document.execCommand('copy')}catch{}field.remove()}
  const label=button.querySelector('span');label.textContent='Copied';button.querySelector('use').setAttribute('href','#i-check');
  clearTimeout(button.resetTimer);button.resetTimer=setTimeout(()=>{label.textContent='Copy';button.querySelector('use').setAttribute('href','#i-copy')},1800);
}
function copyButton(text){
  const button=el('button','btn ghost');button.type='button';button.setAttribute('aria-label','Copy answer');
  button.append(icon('copy'),el('span','','Copy'));button.onclick=()=>copy(text,button);return button;
}

// Agent answers are plain text with light markup: paragraphs, lists, headings, code. Built with text nodes only.
function inline(parent,text){
  const pattern=/`([^`\n]+)`|\*\*([^*\n]+)\*\*/g;let last=0,match;
  while((match=pattern.exec(text))){
    if(match.index>last)parent.append(text.slice(last,match.index));
    parent.append(el(match[1]!==undefined?'code':'strong','',match[1]!==undefined?match[1]:match[2]));last=pattern.lastIndex;
  }
  if(last<text.length)parent.append(text.slice(last));
}
function renderText(box,text){
  box.replaceChildren();
  let paragraph=null,list=null,code=null;
  for(const line of String(text).replace(/\r\n?/g,'\n').split('\n')){
    if(code){if(/^\s*```/.test(line))code=null;else code.textContent+=(code.textContent?'\n':'')+line;continue}
    let match;
    if(/^\s*```/.test(line)){const pre=el('pre');code=el('code');pre.append(code);box.append(pre);paragraph=list=null;continue}
    if(!line.trim()){paragraph=null;continue}
    if((match=line.match(/^\s*(#{1,3})\s+(.*)$/))){const heading=el('h3');inline(heading,match[2]);box.append(heading);paragraph=list=null;continue}
    const bullet=line.match(/^\s*[-*•]\s+(.*)$/),numbered=line.match(/^\s*(\d{1,3})[.)]\s+(.*)$/),item=bullet||numbered;
    if(item){
      const kind=bullet?'UL':'OL';
      if(!list||list.tagName!==kind){list=el(kind.toLowerCase());if(numbered&&numbered[1]!=='1')list.start=+numbered[1];box.append(list)}
      const row=el('li');inline(row,item[item.length-1]);list.append(row);paragraph=null;continue;
    }
    if(list&&/^\s{2,}\S/.test(line)){const row=list.lastElementChild;row.append(el('br'));inline(row,line.trim());continue}
    list=null;
    if(!paragraph){paragraph=el('p');box.append(paragraph)}else paragraph.append(el('br'));
    inline(paragraph,line);
  }
}

function renderTurns(turns){
  const nodes=[];
  for(const turn of turns){
    const fresh=rendered&&!knownTurns.has(turn.id);
    const you=el('div','msg you'+(fresh?' new':'')),ask=el('div','bubble');
    ask.append(el('p','',turn.instruction));you.append(ask,el('p','meta','You · '+when(turn.created)));
    const bot=el('div','msg bot'+(fresh?' new':''));
    if(turn.summary){
      const bubble=el('div','bubble rich'),head=el('div','bubble-head'),answer=el('div','prose');
      head.append(el('h2','','Answer'),copyButton(turn.summary));renderText(answer,turn.summary);bubble.append(head,answer);bot.append(bubble);
    }
    const row=el('div','status-row');row.append(chip(turn.state),el('p','meta',when(turn.created)));
    bot.append(row);nodes.push(you,bot);knownTurns.add(turn.id);
  }
  $('turns').replaceChildren(...nodes);
}
function renderTimeline(history){
  const list=$('history');list.replaceChildren();let previous=null;
  history.forEach((event,index)=>{
    const date=new Date(event.at*1000),item=el('li','s-'+(eventTones[event.kind]||'neutral')+(index===history.length-1?' now':''));
    item.append(el('strong','',events[event.kind]||event.kind),timeNode(event.at,previous&&previous.toDateString()===date.toDateString()));
    previous=date;list.append(item);
  });
}

// Follow-up composer: the instruction is stored first so a retry reuses the same idempotent id.
function setSend(retry){$('send-followup').classList.toggle('retry',retry);$('send-icon').setAttribute('href','#i-'+(retry?'refresh':'up'));$('send-followup').lastElementChild.textContent=retry?'Retry sending':'Send instruction'}
function growField(){const field=$('instruction');field.style.height='0';if(field.scrollHeight)field.style.height=Math.min(field.scrollHeight+3,160)+'px';else field.style.height=''}
function syncComposer(task){
  $('followup-section').hidden=!task.can_followup;
  const pending=read('task-followup-pending:'+target);
  if(pending){$('instruction').value=pending.instruction;$('instruction').disabled=true;setSend(true)}
}
async function sendPending(){
  const page=target,pending=read('task-followup-pending:'+page);
  if(!pending||sending||!validTarget(page))return;
  sending=true;$('send-followup').disabled=true;$('followup-status').className='';
  try{
    const headers={'Content-Type':'application/json'};
    if(followupToken)headers['X-Task-Followup']=followupToken;else headers.Authorization='Bearer '+await access();
    const response=await fetch('/tasks/v1/'+page+'/followups',{method:'POST',headers,body:JSON.stringify(pending)});
    if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(typeof error.detail==='string'?error.detail:'Could not save the instruction. Try again.')}
    await response.json();remove('task-followup-pending:'+page);
    if(target===page){$('instruction').disabled=false;$('instruction').value='';setSend(false);growField();$('followup-status').className='ok';$('followup-status').textContent='Instruction saved. It will continue in the same session when the laptop is ready.';await refresh()}
  }catch(error){$('followup-status').className='warn';$('followup-status').textContent=navigator.onLine?error.message:'Saved on this phone. It will send when you reconnect.'}
  finally{sending=false;$('send-followup').disabled=false}
}
$('followup-form').onsubmit=event=>{
  event.preventDefault();
  if(!read('task-followup-pending:'+target)){
    const instruction=$('instruction').value;if(!instruction.trim())return;
    write('task-followup-pending:'+target,{id:crypto.randomUUID(),instruction});$('instruction').disabled=true;
  }
  sendPending();
};
$('instruction').addEventListener('input',growField);
$('instruction').addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();$('followup-form').requestSubmit()}});

// History: loaded explicitly (open, search, load more) and merged in place when the tab returns, so loaded pages and nodes under the finger survive.
let historyCursor=null,historyBusy=false,historyLoaded=false,historyPages=0,historySeq=0,historyStamp=0;
const historyRows=new Map(),historyNodes=new Map();
async function loadHistory(mode='fresh'){
  loadPreferences();
  if(target||document.hidden)return;
  if(mode!=='fresh'&&historyBusy)return;
  if(mode==='more'&&!historyCursor)return;
  if(mode==='merge'&&Date.now()-historyStamp<15000)return;
  const seq=++historySeq;historyBusy=true;
  if(!historyLoaded)showView('loading');
  $('history-more').disabled=true;$('task-history-list').classList.toggle('busy',mode==='fresh'&&historyLoaded);
  try{
    if(!tokens)throw fatal('Sign in to view your task history.');
    const query=new URLSearchParams({q:$('history-search').value,limit:'30'});
    if(mode==='more')query.set('cursor',historyCursor);
    const response=await fetch('/tasks/v1/history?'+query,{headers:{Authorization:'Bearer '+await access()},cache:'no-store',signal:timeout()});
    if(!response.ok)throw response.status===401?fatal('Sign in to view your task history.'):soft('Task history is temporarily unavailable.');
    const data=await response.json();
    if(seq!==historySeq)return;
    if(mode==='fresh'){historyRows.clear();historyPages=0}
    for(const task of data.items)historyRows.set(task.kind+'/'+task.id,task);
    if(mode==='more')historyPages++;else if(mode==='fresh')historyPages=1;
    if(mode!=='merge'||historyPages<=1)historyCursor=data.next_cursor;
    historyLoaded=true;historyStamp=Date.now();setConnection('');renderHistory();
  }catch(error){
    if(seq!==historySeq)return;
    if(error.final){historyLoaded=false;historyRows.clear();setConnection('');signInNotice('Sign in to see your tasks','Use your Home Assistant account to browse recent tasks and their answers.')}
    else if(!historyLoaded)showNotice({title:'Could not load your tasks',text:describe(error),action:'Try again',run:()=>loadHistory('fresh')});
    else setConnection(describe(error),'warning');
  }finally{if(seq===historySeq){historyBusy=false;$('history-more').disabled=false;$('task-history-list').classList.remove('busy');authButton()}}
}
function renderHistory(){
  showView('history');
  const list=$('task-history-list'),rows=[...historyRows.values()].sort((a,b)=>b.updated-a.updated||(a.kind<b.kind?1:a.kind>b.kind?-1:0)||(a.id<b.id?1:a.id>b.id?-1:0)),keep=new Set();
  rows.forEach((task,index)=>{
    const key=task.kind+'/'+task.id;keep.add(key);
    let item=historyNodes.get(key);if(!item){item=el('li');historyNodes.set(key,item)}
    fillCard(item,task);
    if(list.children[index]!==item)list.insertBefore(item,list.children[index]||null);
  });
  for(const [key,node] of historyNodes)if(!keep.has(key)){node.remove();historyNodes.delete(key)}
  const query=$('history-search').value;
  $('history-empty').hidden=rows.length>0;
  if(!rows.length)fillNotice($('history-empty'),query?{title:'No matching tasks',text:'Nothing matches your search yet.',action:'Clear search',run:()=>{$('history-search').value='';loadHistory('fresh')}}:{title:'No tasks yet',text:'Requests you give the assistant appear here with their answers.'});
  $('history-more').hidden=!historyCursor;
}
function fillCard(item,task){
  const signature=[task.state,task.updated,task.request,task.summary,task.url].join('\u0001');
  if(item.dataset.signature===signature)return;item.dataset.signature=signature;
  const card=el('a','task-card s-'+stateTone(task.state)),tile=el('span','tile'),body=el('span','body'),foot=el('span','foot');
  card.href=/^\/tasks\/(agent|command)\/[A-Za-z0-9_-]+$/.test(task.url)?task.url:'/tasks/';
  tile.append(icon(task.kind==='command'?'bolt':'chat'));
  body.append(el('span','title',clip(task.request,240)));
  if(task.summary)body.append(el('span','snippet',clip(task.summary,320)));
  foot.append(chip(task.state),el('span','meta',when(task.updated)));
  if(task.state==='needs_input')foot.append(el('span','go','Answer'));
  body.append(foot);
  card.append(tile,body,icon('chev'));item.replaceChildren(card);
}
let searchTimer;
$('history-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadHistory('fresh'),250)};
$('history-more').onclick=()=>loadHistory('more');

// Colour mode button: Sunrise & sunset -> System -> Light -> Dark. The mode itself is applied by theme.js.
const themeApi=window.tasksTheme,modeIcon={sun:'sunrise',system:'monitor',light:'sun',dark:'moon'};
function showMode(){
  const label='Colour mode: '+themeApi.describe()+'. Change.';
  $('theme').setAttribute('aria-label',label);$('theme').title=label;
  $('theme').querySelector('use').setAttribute('href','#i-'+modeIcon[themeApi.mode()]);
}
if(themeApi){
  window.addEventListener('themechange',showMode);
  $('theme').onclick=()=>{themeApi.cycle();$('theme-status').textContent='Colour mode: '+themeApi.describe()};
  showMode();
}else $('theme').hidden=true;

$('signin').onclick=()=>{
  if(!tokens)return signIn();
  tokens=null;remove('task-login');clearTimeout(pollTimer);authButton();
  historyRows.clear();historyNodes.clear();$('task-history-list').replaceChildren();historyLoaded=false;historyCursor=null;
  $('history').replaceChildren();$('turns').replaceChildren();$('result').replaceChildren();$('followup-section').hidden=true;
  signInNotice('Signed out','Sign in again to view '+(target?'this task.':'your task history.'));
};
window.addEventListener('hashchange',()=>{const value=location.hash.slice(1);if(validTarget(value)){target=value;viewToken=read('task-view:'+target);write('task-target',target,session);authButton();resetDetail();refresh()}});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
window.addEventListener('online',()=>{setConnection('');refresh();sendPending()});
window.addEventListener('offline',()=>setConnection('You are offline. This page updates again when you reconnect.','warning'));
(async()=>{
  authButton();setMode();showView('loading');
  if(params.has('code')){
    const state=params.get('state'),expected=read('task-oauth-state:'+state)||read('task-oauth-state',session);
    if(validTarget(params.get('task')||expected?.target))target=params.get('task')||expected.target;
    history.replaceState(null,'',validTarget(target)?'/tasks/'+target:'/tasks/');remove('task-oauth-state:'+state);remove('task-oauth-state',session);
    try{if(!expected||expected.state!==state||Date.now()-expected.time>600000)throw Error('Sign-in session expired.');await exchange({grant_type:'authorization_code',code:params.get('code')})}
    catch(error){setConnection(error.message,'danger')}
    setMode();
  }
  await refresh();sendPending();
})();
