// Loaded from <head> so the colour mode applies before the first paint.
(function(){
  const KEY='groceries-theme',MODES=['sun','system','light','dark'],COLORS={light:'#FAF5EC',dark:'#130E1C'};
  const MUNICH={lat:48.137,lon:11.575};
  // Sunrise/sunset from the standard solar-position equations (upper limb at -0.833 degrees incl. refraction). Returns epoch milliseconds.
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

  const root=document.documentElement,query=window.matchMedia?matchMedia('(prefers-color-scheme: dark)'):null,listeners=[];
  let seen=stored(),mode=seen||'sun',resolved='light',next=0,timer=0;

  function stored(){
    try{
      const value=localStorage.getItem(KEY);
      // Earlier versions stored an empty string for the System choice.
      return value===''?'system':MODES.includes(value)?value:'sun';
    }catch(error){return null}
  }
  // Another tab may have changed the choice; a mode that could not be saved is kept.
  function resync(){
    const value=stored();
    if(value!==null&&value!==seen){seen=value;mode=value}
    update();
  }
  function update(){
    clearTimeout(timer);next=0;
    if(mode==='light'||mode==='dark')resolved=mode;
    else if(mode==='system')resolved=query&&query.matches?'dark':'light';
    else{
      const now=Date.now(),phase=sunPhase(now,MUNICH);
      resolved=phase.dark?'dark':'light';next=phase.next;
      timer=setTimeout(update,Math.max(1,next-now));
    }
    root.dataset.theme=resolved;
    const metas=document.querySelectorAll('meta[name=theme-color]');
    for(let i=0;i<metas.length;i++)metas[i].content=COLORS[resolved];
    listeners.forEach(listener=>listener());
  }
  function set(value){
    if(!MODES.includes(value))return;
    mode=value;
    try{localStorage.setItem(KEY,value);seen=value}catch(error){}
    update();
  }

  // Timers sleep in background tabs, so the sun phase is re-checked when the page comes back.
  document.addEventListener('visibilitychange',resync);
  addEventListener('focus',resync);
  addEventListener('pageshow',resync);
  addEventListener('storage',event=>{if(event.key===KEY||event.key===null)resync()});
  if(query){
    const follow=()=>{if(mode==='system')update()};
    if(query.addEventListener)query.addEventListener('change',follow);else query.addListener(follow);
  }

  window.groceriesTheme={
    read:()=>mode,
    set:set,
    state:()=>({mode:mode,resolved:resolved,next:next}),
    subscribe:listener=>{listeners.push(listener)}
  };
  update();
})();
