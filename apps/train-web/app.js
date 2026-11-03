// Boot: who is signed in, the join screen for a first invite link, then the dashboard over this account's on-device store.
// The session lives in an HttpOnly cookie; this page only keeps the account's ID and name to start offline.
import {el,icon,button,toast} from './js/core.js';
import {api,ApiError} from './js/api.js';
import * as store from './js/store.js';
import * as screen from './js/screen.js';
import * as historyView from './js/history.js';
import * as plan from './js/plan.js';
import * as coach from './js/coach.js';
import * as settings from './js/settings.js';
import * as setup from './js/setup.js';
import {nav} from './js/nav.js';

const app=document.getElementById('app'),params=new URLSearchParams(location.search);
const KNOWN='train-account';
const known=()=>{try{return JSON.parse(localStorage.getItem(KNOWN))}catch{return null}};
const remember=a=>{try{localStorage.setItem(KNOWN,JSON.stringify({id:a.id,name:a.name}))}catch{}};
const standalone=()=>matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;
const ios=()=>/iP(hone|ad|od)/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);

Object.assign(nav,{
  setup:()=>setup.open(screen.account(),()=>screen.render()),
  exercise:historyView.exercise,pick:plan.pick,coach:coach.open,finished:screen.finished,workout:id=>historyView.session(id),
  sprint:plan.sprint,sprintList:plan.sprintList,refresh:screen.refresh,profile:screen.profile,begin:screen.begin,dashboard:screen.render,
});

async function boot(){
  if('serviceWorker' in navigator)navigator.serviceWorker.register('sw.js',{scope:'./'}).catch(()=>{});
  let account=null;
  try{account=await api('me')}
  catch(e){
    if(e instanceof ApiError&&e.status===401){try{localStorage.removeItem(KNOWN)}catch{}join();return}
    account=known();if(!account){app.replaceChildren(el('div',{class:'boot'},el('p',{text:'Connect to the internet to open Train for the first time.'})));return}
  }
  if(params.has('invite'))clean('invite');
  remember(account);start(account);
}
function clean(key){params.delete(key);const q=params.toString();history.replaceState(history.state,'',location.pathname+(q?'?'+q:''))}

/** The first visit from an invite link: a display name, then the cookie is set and the invite leaves the address bar. */
function join(){
  const invite=params.get('invite')||'';
  const name=el('input',{class:'field',autocomplete:'nickname',maxLength:80,placeholder:'Your name',attrs:{'aria-label':'Display name',enterkeyhint:'go'}});
  const go=el('button',{class:'btn primary wide',type:'submit',text:'Join Train'});
  const note=el('p',{class:'hint',attrs:{role:'status'}});
  const form=el('form',{},name,go,note);
  form.onsubmit=async e=>{e.preventDefault();const n=name.value.trim();if(!n){name.focus();return}go.disabled=true;note.textContent='Joining…';
    try{const account=await api('join',{body:{name:n,invite}});clean('invite');remember(account);start(account);
      if(ios()&&!standalone())toast('Now add Train to your Home Screen from the Share menu.')}
    catch(err){go.disabled=false;note.textContent=err instanceof ApiError?(err.status===403?'This invite is invalid or has expired. Ask for a new link.':err.status===409?'This browser is already joined. Reload Train.':err.message||'Your server refused the request.'):'No connection. Try again when you are online.'}};
  const parts=[el('span',{class:'mark'},icon('barbell')),el('h1',{text:'Train'})];
  if(invite){parts.push(el('p',{class:'hint',text:'Pick the name others see on the standings. Your workouts stay private unless you share them.'}),form);
    if(ios()&&standalone())parts.push(el('p',{class:'hint small',text:'If joining fails here, open the invite link in Safari, join there, then add Train to your Home Screen again.'}));
    else if(ios())parts.push(el('p',{class:'hint small',text:'Join here in Safari first, then add Train to your Home Screen from the Share menu so it stays signed in.'}))}
  else parts.push(el('p',{class:'hint',text:'Train is invite only. Open the link you were sent to join.'}),
    ios()&&standalone()?el('p',{class:'hint small',text:'On iPhone, open your invite link in Safari and join there before adding Train to your Home Screen.'}):null);
  app.replaceChildren(el('main',{class:'join'},...parts.filter(Boolean)));
  if(invite)setTimeout(()=>name.focus(),60);
}

let frame=0,pushTimer=0;
async function start(account){
  await store.load(account.id);
  screen.mount(app,account);
  // Repaint the dashboard on any change, and send local edits shortly after they settle.
  store.onChange(()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(screen.render);if(store.waiting()){clearTimeout(pushTimer);pushTimer=setTimeout(()=>store.sync(),1500)}});
  screen.refresh();
  settings.load().then(()=>screen.render());
  if(account.setup_complete===false)setup.open(account,()=>screen.render());
  addEventListener('online',()=>screen.refresh());
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')screen.refresh()});
  setInterval(()=>{if(document.visibilityState==='visible')store.sync()},60000);
  if(params.has('reminder')){const id=params.get('reminder');clean('reminder');screen.reminder(id)}
  navigator.serviceWorker?.addEventListener('message',e=>{if(e.data?.reminder)screen.reminder(e.data.reminder)});
}
boot();
