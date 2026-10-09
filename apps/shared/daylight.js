// Pure solar math shared by the web surfaces. Coordinates come from private runtime settings.
(function(root){
  'use strict';
  const DAY=86400000,RAD=Math.PI/180;
  function valid(place){return !!place&&typeof place.latitude==='number'&&typeof place.longitude==='number'&&Number.isFinite(place.latitude)&&Number.isFinite(place.longitude)&&Math.abs(place.latitude)<=90&&Math.abs(place.longitude)<=180}
  function cycle(ms,place){
    const d=ms/DAY-0.5+2440588-2451545,lw=-place.longitude*RAD,phi=place.latitude*RAD;
    const n=Math.round(d-0.0009-lw/(2*Math.PI)),ds=0.0009+lw/(2*Math.PI)+n;
    const m=RAD*(357.5291+0.98560028*ds),c=RAD*(1.9148*Math.sin(m)+0.02*Math.sin(2*m)+0.0003*Math.sin(3*m));
    const l=m+c+RAD*102.9372+Math.PI,dec=Math.asin(Math.sin(l)*Math.sin(RAD*23.4397));
    const transit=2451545+ds+0.0053*Math.sin(m)-0.0069*Math.sin(2*l);
    const cos=(Math.sin(-0.833*RAD)-Math.sin(phi)*Math.sin(dec))/(Math.cos(phi)*Math.cos(dec));
    if(cos>=1)return {polar:'night'};
    if(cos<=-1)return {polar:'day'};
    const set=2451545+0.0009+(Math.acos(cos)+lw)/(2*Math.PI)+n+0.0053*Math.sin(m)-0.0069*Math.sin(2*l);
    const rise=transit-(set-transit),epoch=j=>(j+0.5-2440588)*DAY;
    return {rise:epoch(rise),set:epoch(set)};
  }
  function dark(ms,place){
    for(let offset=-1;offset<=1;offset++){
      const t=cycle(ms+offset*DAY,place);
      if(t.rise!==undefined&&ms>=t.rise&&ms<t.set)return false;
    }
    return cycle(ms,place).polar!=='day';
  }
  function phase(ms,place){
    if(!valid(place))return null;
    let next=Infinity;
    for(let offset=-1;offset<=2;offset++){
      const t=cycle(ms+offset*DAY,place);
      for(const event of [t.rise,t.set])if(event>ms&&event<next&&dark(event-1,place)!==dark(event+1,place))next=event;
    }
    return {dark:dark(ms,place),next:Number.isFinite(next)?next:ms+3600000};
  }
  const STORAGE='assistant-daylight';
  function stored(){try{const place=JSON.parse(localStorage.getItem(STORAGE));return valid(place)?place:null}catch{return null}}
  function configure(place){try{if(valid(place))localStorage.setItem(STORAGE,JSON.stringify({latitude:place.latitude,longitude:place.longitude}));else localStorage.removeItem(STORAGE)}catch{}root.dispatchEvent(new Event('daylightchange'))}
  function create(key,eventName){
    const MODES=['sun','system','light','dark'],names={sun:'Sunrise & sunset',system:'System',light:'Light',dark:'Dark'};
    const query=root.matchMedia?root.matchMedia('(prefers-color-scheme: dark)'):null,listeners=[];
    function read(){try{const v=localStorage.getItem(key);return v===''?'system':MODES.includes(v)?v:'sun'}catch{return 'sun'}}
    let mode=read(),timer=0;
    function state(){const sun=mode==='sun'?phase(Date.now(),stored()):null;const theme=sun?(sun.dark?'dark':'light'):mode==='dark'?'dark':mode==='light'?'light':query&&query.matches?'dark':'light';return {mode,theme,resolved:theme,next:sun?sun.next:null}}
    function apply(){
      clearTimeout(timer);const current=state();document.documentElement.dataset.theme=current.theme;
      for(const meta of document.querySelectorAll('meta[name=theme-color]'))meta.content=current.theme==='dark'?'#130E1C':'#FAF5EC';
      if(current.next)timer=setTimeout(apply,Math.min(2147483647,Math.max(1,Math.ceil(current.next-Date.now()))));
      listeners.forEach(fn=>fn(current));if(eventName)root.dispatchEvent(new Event(eventName));
    }
    function set(next){if(!MODES.includes(next))return;mode=next;try{localStorage.setItem(key,next)}catch{}apply()}
    function describe(){const s=state();return names[s.mode]+(s.mode==='sun'?(s.next?' · '+s.theme+' until '+new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit'}).format(s.next):' · follows System'):'')}
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)apply()});
    for(const name of ['focus','pageshow','daylightchange'])root.addEventListener(name,apply);
    root.addEventListener('storage',event=>{if(event.key===key||event.key===STORAGE||event.key===null){mode=read();apply()}});
    if(query){const follow=()=>{if(mode==='system'||(mode==='sun'&&!stored()))apply()};if(query.addEventListener)query.addEventListener('change',follow);else query.addListener(follow)}
    apply();return {MODES,state,mode:()=>mode,resolved:()=>state().theme,set,describe,cycle:()=>set(MODES[(MODES.indexOf(mode)+1)%MODES.length]),subscribe:fn=>listeners.push(fn)};
  }
  root.AssistantDaylight={valid,phase,stored,configure,create};
  if(typeof module!=='undefined')module.exports=root.AssistantDaylight;
})(globalThis);
