'use strict';
const $=id=>document.getElementById(id),client=location.origin+'/tasks/',params=new URLSearchParams(location.search);
function read(key,store=localStorage){try{return JSON.parse(store.getItem(key)||'null')}catch{return null}}
function write(key,value,store=localStorage){try{store.setItem(key,JSON.stringify(value))}catch{}}
function remove(key,store=localStorage){try{store.removeItem(key)}catch{}}
const validTarget=value=>/^(agent|command)\/[A-Za-z0-9_-]{8,64}$/.test(value||'');
let target=params.get('task')||(location.pathname.startsWith('/tasks/agent/')||location.pathname.startsWith('/tasks/command/')?location.pathname.slice(7):location.hash.slice(1))||'',tokens=read('task-login')||read('task-login',sessionStorage),busy=false,followupToken=null,sending=false,historyCursor=null,historyBusy=false,historyRows=new Map();
let viewToken=params.get('view')||read('task-view:'+target);
if(tokens){write('task-login',tokens);remove('task-login',sessionStorage)}
if(validTarget(target))write('task-target',target,sessionStorage);
if(params.get('view')&&validTarget(target)){write('task-view:'+target,viewToken);history.replaceState(null,'','/tasks/'+target)}
const labels={queued:'Queued',running:'In progress',completed:'Completed',failed:'Failed',needs_input:'Needs your input',cancelled:'Cancelled',expired:'Expired'};
const events={submitted:'Acknowledged and saved',claimed:'Started on the laptop',lease_expired:'Connection interrupted; returned to the queue',completed:'Completed',failed:'Failed',needs_input:'Needs your input',cancelled:'Cancelled',expired:'Expired'};
function authButton(){$('signin').hidden=!!viewToken;$('signin').textContent=tokens?'Sign out':'Sign in'}
function signIn(){const state=crypto.randomUUID();write('task-oauth-state:'+state,{state,target,time:Date.now()});const redirect=client+(validTarget(target)?'?task='+encodeURIComponent(target):'');location.href=location.origin+'/auth/authorize?'+new URLSearchParams({client_id:client,redirect_uri:redirect,response_type:'code',state})}
async function exchange(body){const response=await fetch('/auth/token',{method:'POST',body:new URLSearchParams({...body,client_id:client})});if(!response.ok){tokens=null;remove('task-login');authButton();throw Error('Sign in again to view this task.')}const next=await response.json();tokens={...next,refresh_token:next.refresh_token||body.refresh_token,expires_at:Date.now()+next.expires_in*1000};write('task-login',tokens)}
async function access(){if(!tokens)throw Error('Sign in with your Home Assistant account to view this task.');if(tokens.expires_at<Date.now()+60000)await exchange({grant_type:'refresh_token',refresh_token:tokens.refresh_token});return tokens.access_token}
async function taskResponse(){let headers=viewToken?{'X-Task-View':viewToken}:{Authorization:'Bearer '+await access()};let response=await fetch('/tasks/v1/'+target,{headers,cache:'no-store'});if(response.status===401&&viewToken){remove('task-view:'+target);viewToken=null;authButton();if(tokens)response=await fetch('/tasks/v1/'+target,{headers:{Authorization:'Bearer '+await access()},cache:'no-store'})}if(response.status===401){tokens=null;remove('task-login');authButton();throw Error('This task link is unavailable. Sign in to view the answer.')}return response}
async function refresh(){if(!target){await loadHistory();return;}if(busy||document.hidden)return;busy=true;try{if(!validTarget(target))throw Error('Invalid task link.');const response=await taskResponse();if(!response.ok)throw Error(response.status===404?'Task not found.':'Task status is temporarily unavailable.');const task=await response.json();const taskState=task.conversation_state||task.state;$('status').textContent=labels[taskState]||taskState;followupToken=task.followup_token;renderFollowups(task);$('request').textContent=task.request;$('task-id').textContent='Task '+task.id;$('connection').textContent=taskState==='queued'?(task.connection.laptop==='unavailable'?'Laptop offline. Your task is saved and waiting.':task.connection.laptop==='blocked'?'The laptop cannot run tasks right now. Your task is saved.':'Waiting to start.'):(taskState==='running'?(task.connection.laptop==='unavailable'?'Laptop disconnected. Waiting for it to reconnect.':'The laptop is working on your task.'):'Updated '+new Date((task.conversation_updated||task.updated)*1000).toLocaleString());$('result-section').hidden=!task.summary;$('result-title').textContent=task.state==='needs_input'?'Your input is needed':'Result';$('result').textContent=task.summary;$('history').replaceChildren();for(const event of task.history){const item=document.createElement('li');item.textContent=new Date(event.at*1000).toLocaleTimeString()+' · '+(events[event.kind]||event.kind);$('history').append(item)}authButton()}catch(error){$('connection').textContent=error.message}finally{busy=false}}
$('signin').onclick=()=>{if(!tokens)return signIn();tokens=null;remove('task-login');$('result').textContent='';$('request').textContent='—';$('history').replaceChildren();historyRows.clear();$('task-history-list').replaceChildren();$('turns').replaceChildren();$('followup-section').hidden=true;authButton();$('connection').textContent='Signed out.'};
window.addEventListener('hashchange',()=>{const value=location.hash.slice(1);if(validTarget(value)){target=value;viewToken=read('task-view:'+target);write('task-target',target,sessionStorage);authButton();refresh()}});document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});window.addEventListener('online',()=>{refresh();sendPending()});
(async()=>{authButton();if(!target)$('task-detail-content').hidden=true;if(params.has('code')){const state=params.get('state');const expected=read('task-oauth-state:'+state)||read('task-oauth-state',sessionStorage);if(validTarget(params.get('task')||expected?.target))target=params.get('task')||expected.target;history.replaceState(null,'',validTarget(target)?'/tasks/'+target:'/tasks/');remove('task-oauth-state:'+state);remove('task-oauth-state',sessionStorage);try{if(!expected||expected.state!==state||Date.now()-expected.time>600000)throw Error('Sign-in session expired.');await exchange({grant_type:'authorization_code',code:params.get('code')})}catch(error){$('connection').textContent=error.message}}await refresh();sendPending();setInterval(refresh,5000)})();

function renderFollowups(task){$('task-detail-content').hidden=false;$('task-history-section').hidden=true;
  $('followup-section').hidden=!task.can_followup;
  $('turns-section').hidden=!task.turns?.length;
  $('turns').replaceChildren();
  for(const turn of task.turns||[]){
    const article=document.createElement('article'),state=document.createElement('p'),text=document.createElement('p'),answer=document.createElement('pre');
    state.className='turn-status';state.textContent=(labels[turn.state]||turn.state)+' - '+new Date(turn.created*1000).toLocaleString();
    text.textContent=turn.instruction;answer.textContent=turn.summary;
    article.append(state,text,answer);$('turns').append(article);
  }
  const pending=read('task-followup-pending:'+target);
  if(pending){$('instruction').value=pending.instruction;$('instruction').disabled=true;$('send-followup').textContent='Retry sending';}
}
async function sendPending(){
  const page=target,pending=read('task-followup-pending:'+page);
  if(!pending||sending||!validTarget(page))return;
  sending=true;$('send-followup').disabled=true;
  try{
    const headers={'Content-Type':'application/json'};
    if(followupToken)headers['X-Task-Followup']=followupToken;else headers.Authorization='Bearer '+await access();
    const response=await fetch('/tasks/v1/'+page+'/followups',{method:'POST',headers,body:JSON.stringify(pending)});
    if(!response.ok){const error=await response.json().catch(()=>({}));throw Error(typeof error.detail==='string'?error.detail:'Could not save the instruction. Try again.');}
    await response.json();remove('task-followup-pending:'+page);
    if(target===page){$('instruction').disabled=false;$('instruction').value='';$('send-followup').textContent='Send instruction';$('followup-status').textContent='Instruction saved. It will continue in the same session when the laptop is ready.';await refresh();}
  }catch(error){$('followup-status').textContent=navigator.onLine?error.message:'Saved on this phone. It will send when you reconnect.';}
  finally{sending=false;$('send-followup').disabled=false;}
}
$('followup-form').onsubmit=event=>{
  event.preventDefault();
  if(!read('task-followup-pending:'+target)){
    const instruction=$('instruction').value;if(!instruction.trim())return;
    write('task-followup-pending:'+target,{id:crypto.randomUUID(),instruction});$('instruction').disabled=true;
  }
  sendPending();
};

async function loadHistory(more=false){
  if(target||historyBusy||document.hidden)return;
  historyBusy=true;$('task-detail-content').hidden=true;$('task-history-section').hidden=false;$('status').textContent='Task history';
  try{
    const params=new URLSearchParams({q:$('history-search').value,limit:'30'});
    if(more&&historyCursor)params.set('cursor',historyCursor);
    const response=await fetch('/tasks/v1/history?'+params,{headers:{Authorization:'Bearer '+await access()},cache:'no-store'});
    if(!response.ok)throw Error(response.status===401?'Sign in to view your task history.':'Task history is temporarily unavailable.');
    const data=await response.json();if(!more)historyRows.clear();
    for(const task of data.items)historyRows.set(task.kind+'/'+task.id,task);
    $('task-history-list').replaceChildren();
    for(const task of historyRows.values()){
      const article=document.createElement('article'),link=document.createElement('a'),meta=document.createElement('p'),summary=document.createElement('p');
      link.href=task.url;link.textContent=task.request.length>240?task.request.slice(0,240)+'...':task.request;
      meta.className='turn-status';meta.textContent=(labels[task.state]||task.state)+' - '+new Date(task.updated*1000).toLocaleString();
      summary.textContent=task.summary.length>320?task.summary.slice(0,320)+'...':task.summary;
      article.append(link,meta,summary);$('task-history-list').append(article);
    }
    if(!historyRows.size)$('task-history-list').textContent=$('history-search').value?'No matching tasks.':'No tasks yet.';
    historyCursor=data.next_cursor;$('history-more').hidden=!historyCursor;$('connection').textContent='Open a task to read its details or continue it.';
  }catch(error){$('connection').textContent=error.message;}
  finally{historyBusy=false;authButton();}
}
let searchTimer;
$('history-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadHistory(false),250);};
$('history-more').onclick=()=>loadHistory(true);
