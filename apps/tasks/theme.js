// Loaded from <head>: resolves the stored colour mode to light or dark before the first paint.
(function(){
  'use strict';
  const MUNICH={lat:48.137,lon:11.575},KEY='task-theme',MODES=['sun','system','light','dark'];
  const COLORS={light:'#FAF5EC',dark:'#130E1C'},NAMES={sun:'Sunrise & sunset',system:'System',light:'Light',dark:'Dark'};

  // Sunrise/sunset for a latitude/longitude, standard solar-position equations
  // (sun's upper limb at -0.833 degrees incl. refraction). Returns epoch milliseconds.
  function sunTimes(ms, lat, lon) {
    const rad = Math.PI / 180, day = 86400000, J1970 = 2440588, J2000 = 2451545, J0 = 0.0009;
    const d = ms / day - 0.5 + J1970 - J2000;
    const lw = -lon * rad, phi = lat * rad;
    const n = Math.round(d - J0 - lw / (2 * Math.PI));
    const ds = J0 + lw / (2 * Math.PI) + n;
    const M = rad * (357.5291 + 0.98560028 * ds);
    const C = rad * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M));
    const L = M + C + rad * 102.9372 + Math.PI;
    const dec = Math.asin(Math.sin(L) * Math.sin(rad * 23.4397));
    const transit = J2000 + ds + 0.0053 * Math.sin(M) - 0.0069 * Math.sin(2 * L);
    const cosW = (Math.sin(-0.833 * rad) - Math.sin(phi) * Math.sin(dec)) / (Math.cos(phi) * Math.cos(dec));
    if (cosW >= 1) return { rise: null, set: null, polar: 'night' };
    if (cosW <= -1) return { rise: null, set: null, polar: 'day' };
    const w = Math.acos(cosW);
    const set = J2000 + J0 + (w + lw) / (2 * Math.PI) + n + 0.0053 * Math.sin(M) - 0.0069 * Math.sin(2 * L);
    const rise = transit - (set - transit);
    const toMs = j => (j + 0.5 - J1970) * day;
    return { rise: toMs(rise), set: toMs(set) };
  }
  // Dark between sunset and the next sunrise; also returns when the answer next changes.
  function sunPhase(ms, place) {
    const t = sunTimes(ms, place.lat, place.lon);
    if (t.polar) return { dark: t.polar === 'night', next: ms + 3600000 };
    if (ms < t.rise) return { dark: true, next: t.rise };
    if (ms < t.set) return { dark: false, next: t.set };
    const tomorrow = sunTimes(ms + 86400000, place.lat, place.lon);
    return { dark: true, next: tomorrow.rise || ms + 3600000 };
  }

  const root=document.documentElement,system=window.matchMedia?matchMedia('(prefers-color-scheme: dark)'):null;
  const hours=new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit'});
  let mode=read(),resolved='',timer=0;

  function read(){
    try{const value=localStorage.getItem(KEY);return MODES.includes(value)?value:'sun'}catch{return 'sun'}
  }
  function apply(){
    clearTimeout(timer);
    const phase=mode==='sun'?sunPhase(Date.now(),MUNICH):null;
    resolved=phase?(phase.dark?'dark':'light'):mode==='system'?(system&&system.matches?'dark':'light'):mode;
    if(root.dataset.theme!==resolved){
      root.dataset.theme=resolved;
      for(const meta of document.querySelectorAll('meta[name=theme-color]'))meta.content=COLORS[resolved];
    }
    if(phase)timer=setTimeout(apply,Math.min(Math.max(phase.next-Date.now(),0)+50,2147483647));
    window.dispatchEvent(new Event('themechange'));
  }
  function set(next){
    if(!MODES.includes(next))return;
    mode=next;
    try{localStorage.setItem(KEY,mode)}catch{}
    apply();
  }
  function describe(){
    if(mode!=='sun')return NAMES[mode];
    const phase=sunPhase(Date.now(),MUNICH);
    return NAMES.sun+' · '+(phase.dark?'dark':'light')+' until '+hours.format(phase.next);
  }

  window.tasksTheme={mode:()=>mode,describe,cycle:()=>set(MODES[(MODES.indexOf(mode)+1)%MODES.length])};
  apply();
  const follow=()=>{if(mode==='system')apply()};
  if(system){if(system.addEventListener)system.addEventListener('change',follow);else if(system.addListener)system.addListener(follow)}
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)apply()});
  window.addEventListener('focus',apply);
  window.addEventListener('pageshow',apply);
  window.addEventListener('storage',event=>{if(event.key===KEY||event.key===null){mode=read();apply()}});
})();
