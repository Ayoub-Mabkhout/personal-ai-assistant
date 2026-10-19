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
  // Meridian: perceptual solar palettes shared with Android. Location is runtime data, never a baked-in home city.
  const NIGHT=-12,HIGH=10;
  const KEYS={
    day:'FAF5EC FFFEFB F3ECE4 231A2E 675C73 5B35D5 FFFFFF ECE5FF E7DDD3 8E829E 17784A E0F2E7 965800 FFEFCF B3263E FCE3E7 3D52CC E3E8FF 8EA2FF 5B35D5 A23BC6 CC3F78',
    dawn:'F8EEEE FFFBFA F1E3E6 271A2C 6A5A6E 5833CF FFFFFF EEE2FA E8D8DC 908096 17754A E1F0E6 935500 FDEBD3 B02443 FADFE5 3C4FC6 E5E4FA F5A6C8 5B35D5 A83BBF D6497A',
    golden:'F7EADB FFF8EF F0DFCC 2A1B22 6E5560 5A2FC0 FFFFFF F0E0F5 E6D2BE 937A86 17734A E3EFDB 8F5200 FBE6C4 AD2440 F9DCDC 3B4CC0 E6E3F7 FFB38E 5B35D5 B8399F D9535E',
    night:'130E1C 1D1729 281F38 F5F0FB ADA3BF B39CFF 1B1230 2E2357 322849 8479A3 74DFA5 173A2A FFC766 3E2D10 FF8FA0 44192A A4B5FF 232B5C 8FA8FF 8E6BFF C46CF0 F08FC4',
    blue:'141428 1E1D35 292844 F2F1FC A9A8C6 AFA4FF 18143A 2C2A5E 34345A 8282AE 78DDB0 163A33 FFC978 3C2F18 FF93AE 431C33 A0BBFF 222E62 9FB4FF 7F70FF B56EF0 F28FC0',
    ember:'1E1220 2A1B2C 36233A FBF0F3 C0A8B6 C4A2FF 1F1228 3A2450 433048 9A7F99 7FDDA6 1D3A2A FFC46E 45301A FF96A2 4B1B2C AEB6FF 2A2A5A FF9E8A 9A6BFF D46BD8 FF9A8A'};
  const VARS=[['--bg','--background'],['--surface'],['--surface-alt'],['--text'],['--muted'],['--accent'],['--on-accent'],['--accent-soft'],['--stroke'],['--stroke-strong'],['--success'],['--success-soft'],['--warning'],['--warning-soft'],['--danger'],['--danger-soft'],['--info'],['--info-soft'],['--peri'],['--g1'],['--g2'],['--g3']];
  const RGB_VARS=[[18,'--peri-rgb'],[18,'--glow-rgb'],[19,'--g1-rgb'],[20,'--g2-rgb'],[21,'--g3-rgb']],EXTRA=['--bar','--nav-bg','--glass'];
  const lin=c=>{c/=255;return c<=0.04045?c/12.92:Math.pow((c+0.055)/1.055,2.4)},enc=v=>{v=Math.max(0,Math.min(1,v));return Math.round(255*(v<=0.0031308?12.92*v:1.055*Math.pow(v,1/2.4)-0.055))};
  function lab(hex){const n=parseInt(hex,16),r=lin(n>>16&255),g=lin(n>>8&255),b=lin(n&255);
    const l=Math.cbrt(0.4122214708*r+0.5363325363*g+0.0514459929*b),m=Math.cbrt(0.2119034982*r+0.6806995451*g+0.1073969566*b),s=Math.cbrt(0.0883024619*r+0.2817188376*g+0.6299787005*b);
    return [0.2104542553*l+0.7936177850*m-0.0040720468*s,1.9779984951*l-2.4285922050*m+0.4505937099*s,0.0259040371*l+0.7827717662*m-0.8086757660*s]}
  function hex(p){const l=Math.pow(p[0]+0.3963377774*p[1]+0.2158037573*p[2],3),m=Math.pow(p[0]-0.1055613458*p[1]-0.0638541728*p[2],3),s=Math.pow(p[0]-0.0894841775*p[1]-1.2914855480*p[2],3);
    return '#'+[4.0767416621*l-3.3077115913*m+0.2309699292*s,-1.2684380046*l+2.6097574011*m-0.3413193965*s,-0.0041960863*l-0.7034186147*m+1.7076147010*s].map(v=>enc(v).toString(16).padStart(2,'0')).join('').toUpperCase()}
  const LAB={};for(const name in KEYS){KEYS[name]=KEYS[name].split(' ');LAB[name]=KEYS[name].map(lab)}
  const clamp=v=>Number.isNaN(v)?0:Math.max(0,Math.min(1,v)),smooth=v=>{v=clamp(v);return v*v*(3-2*v)},mix=(a,b,t)=>a.map((x,i)=>x+(b[i]-x)*t);
  function sun(ms,place){
    const r=RAD,jd=ms/DAY+2440587.5,t=(jd-2451545)/36525;
    const l0=((280.46646+t*(36000.76983+t*0.0003032))%360+360)%360,m=357.52911+t*(35999.05029-0.0001537*t),e=0.016708634-t*(0.000042037+0.0000001267*t);
    const c=Math.sin(m*r)*(1.914602-t*(0.004817+0.000014*t))+Math.sin(2*m*r)*(0.019993-0.000101*t)+Math.sin(3*m*r)*0.000289;
    const omega=125.04-1934.136*t,lambda=l0+c-0.00569-0.00478*Math.sin(omega*r);
    const epsilon=23+(26+(21.448-t*(46.815+t*(0.00059-t*0.001813)))/60)/60+0.00256*Math.cos(omega*r);
    const declination=Math.asin(Math.sin(epsilon*r)*Math.sin(lambda*r)),y=Math.pow(Math.tan(epsilon*r/2),2);
    const equation=4/r*(y*Math.sin(2*l0*r)-2*e*Math.sin(m*r)+4*e*y*Math.sin(m*r)*Math.cos(2*l0*r)-0.5*y*y*Math.sin(4*l0*r)-1.25*e*e*Math.sin(2*m*r));
    let hour=((((ms%DAY)+DAY)%DAY/60000+equation+4*place.longitude)/4-180)%360;if(hour<-180)hour+=360;if(hour>=180)hour-=360;
    const phi=place.latitude*r,cos=Math.sin(phi)*Math.sin(declination)+Math.cos(phi)*Math.cos(declination)*Math.cos(hour*r);
    return {elevation:90-Math.acos(Math.max(-1,Math.min(1,cos)))/r,hourAngle:hour*r};
  }
  function palette(ms,place,weather){
    if(!valid(place))return null;const s=sun(ms,place),morning=clamp(0.5-0.5*Math.sin(s.hourAngle)),w=clamp(weather||0),t=smooth((s.elevation-NIGHT)/(HIGH-NIGHT));
    if(w===0&&t>=1)return KEYS.day.map(h=>'#'+h);if(w===0&&t<=0)return KEYS.night.map(h=>'#'+h);
    const out=KEYS.day.map((_,i)=>{
      const twilight=mix(LAB.ember[i],LAB.blue[i],morning),warm=mix(LAB.golden[i],LAB.dawn[i],morning);
      let p=mix(mix(LAB.night[i],twilight,smooth(Math.min(1,t*3))),mix(warm,LAB.day[i],smooth(Math.max(0,(t-.5)*2))),t);
      if(w>0){const f=1-0.3*w;p=[p[0]-(i<=2||i===8?.025*w:0),p[1]*f,p[2]*f]}
      return hex(p);
    });
    protect(out);return out;
  }
  const ratio=(a,b)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)};
  const colorLab=h=>lab(h.slice(1));
  function readableSurface(color,anchor,front){for(let n=1;n<=32;n++){const c=hex(mix(colorLab(color),colorLab(anchor),n/32));if(ratio(front,c)>=4.55)return c}return anchor}
  function readable(color,end,p,backgrounds){
    const ok=c=>backgrounds.every(i=>ratio(c,p[i])>=4.52);if(ok(color))return color;
    const a=colorLab(color),b=colorLab(end);let lo=0,hi=1;
    for(let n=0;n<18;n++){const mid=(lo+hi)/2;if(ok(hex(mix(a,b,mid))))hi=mid;else lo=mid}
    return hex(mix(a,b,Math.min(1,hi+.002)));
  }
  function protect(p){
    const base=luminance(p[0]),spread=Math.pow(Math.min(1,Math.abs(base-.179)/.12),2),backgrounds=[0,1,2,7,11,13,15,17];
    for(const i of backgrounds)if(i!==0)p[i]=hex(mix(colorLab(p[0]),colorLab(p[i]),spread));
    const end=base<.179?'#FFFFFF':'#000000';for(const i of backgrounds)if(ratio(end,p[i])<4.55)p[i]=readableSurface(p[i],p[0],end);
    for(const i of [3,4])p[i]=readable(p[i],end,p,backgrounds);
    p[5]=readable(p[5],end,p,[0,1,2,7]);
    for(const [fg,bg] of [[10,11],[12,13],[14,15],[16,17]])p[fg]=readable(p[fg],end,p,[0,1,2,bg]);
    const fills=[5,19,20],fillEnd=luminance(p[5])<.179?'#FFFFFF':'#000000';for(const i of fills)if(ratio(fillEnd,p[i])<4.55)p[i]=readableSurface(p[i],p[5],fillEnd);
    p[6]=readable(p[6],fillEnd,p,fills);
  }

  const luminance=h=>{const n=parseInt(h.slice(1),16);return 0.2126*lin(n>>16&255)+0.7152*lin(n>>8&255)+0.0722*lin(n&255)};
  const paletteDark=p=>luminance(p[0])<0.179,rgbOf=h=>{const n=parseInt(h.slice(1),16);return (n>>16&255)+','+(n>>8&255)+','+(n&255)};
  function paint(p){
    const style=document.documentElement.style;if(!style||typeof style.setProperty!=='function')return;
    if(!p){for(const names of VARS)for(const name of names)style.removeProperty(name);for(const [,name] of RGB_VARS)style.removeProperty(name);for(const name of EXTRA)style.removeProperty(name);return}
    VARS.forEach((names,i)=>names.forEach(name=>style.setProperty(name,p[i])));for(const [i,name] of RGB_VARS)style.setProperty(name,rgbOf(p[i]));
    style.setProperty('--bar','rgba('+rgbOf(p[0])+',.96)');style.setProperty('--nav-bg','rgba('+rgbOf(p[1])+',.97)');style.setProperty('--glass','rgba('+rgbOf(p[1])+',.15)');
  }
  // Browser location only when the site already holds geolocation permission; never prompts. Rounded, at most every 30 minutes.
  let geo=null,geoAt=0;
  function locate(done){
    const nav=root.navigator;if(!nav||!nav.permissions||!nav.geolocation||Date.now()-geoAt<1800000)return;geoAt=Date.now();
    try{nav.permissions.query({name:'geolocation'}).then(status=>{if(status.state!=='granted')return;nav.geolocation.getCurrentPosition(position=>{const place={latitude:Math.round(position.coords.latitude*100)/100,longitude:Math.round(position.coords.longitude*100)/100};if(valid(place)){geo=place;done()}},()=>{},{enableHighAccuracy:false,maximumAge:1800000,timeout:10000})}).catch(()=>{})}catch{}
  }
  function daylightPlace(){return geo||stored()||null}
  function create(key,eventName){
    const MODES=['daylight','sun','system','light','dark'],names={daylight:'Meridian',sun:'Sunrise & sunset',system:'System',light:'Light',dark:'Dark'};
    const query=root.matchMedia?root.matchMedia('(prefers-color-scheme: dark)'):null,listeners=[];
    function read(){try{const v=localStorage.getItem(key);return v===''?'system':MODES.includes(v)?v:'daylight'}catch{return 'daylight'}}
    let mode=read(),timer=0;
    function state(){if(mode==='daylight'){const place=daylightPlace(),colors=palette(Date.now(),place,0),theme=colors?(paletteDark(colors)?'dark':'light'):(query&&query.matches?'dark':'light');return {mode,theme,resolved:theme,next:null,palette:colors,place}}
      const sun=mode==='sun'?phase(Date.now(),stored()):null;const theme=sun?(sun.dark?'dark':'light'):mode==='dark'?'dark':mode==='light'?'light':query&&query.matches?'dark':'light';return {mode,theme,resolved:theme,next:sun?sun.next:null,palette:null}}
    function apply(){
      clearTimeout(timer);if(document.hidden)return;const current=state();document.documentElement.dataset.theme=current.theme;paint(current.palette);
      for(const meta of document.querySelectorAll('meta[name=theme-color]'))meta.content=current.palette?current.palette[0]:current.theme==='dark'?'#130E1C':'#FAF5EC';
      if(mode==='daylight'){locate(apply);if(current.palette)timer=setTimeout(apply,60000)}else if(current.next)timer=setTimeout(apply,Math.min(2147483647,Math.max(1,Math.ceil(current.next-Date.now()))));
      listeners.forEach(fn=>fn(current));if(eventName)root.dispatchEvent(new Event(eventName));
    }
    function set(next){if(!MODES.includes(next))return;mode=next;try{localStorage.setItem(key,next)}catch{}apply()}
    function describe(){const s=state();return names[s.mode]+(s.mode==='daylight'?(s.palette?' · follows the sun':' · follows System until configured'):s.mode==='sun'?(s.next?' · '+s.theme+' until '+new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit'}).format(s.next):' · follows System'):'')}
    document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else apply()});
    for(const name of ['focus','pageshow','daylightchange'])root.addEventListener(name,apply);
    root.addEventListener('storage',event=>{if(event.key===key||event.key===STORAGE||event.key===null){mode=read();apply()}});
    if(query){const follow=()=>{if(mode==='system'||(mode==='sun'&&!stored())||(mode==='daylight'&&!daylightPlace()))apply()};if(query.addEventListener)query.addEventListener('change',follow);else query.addListener(follow)}
    apply();return {MODES,state,mode:()=>mode,resolved:()=>state().theme,set,describe,cycle:()=>set(MODES[(MODES.indexOf(mode)+1)%MODES.length]),subscribe:fn=>listeners.push(fn)};
  }
  root.AssistantDaylight={valid,phase,stored,configure,create,sun,palette,dark:paletteDark,KEYS};
  if(typeof module!=='undefined')module.exports=root.AssistantDaylight;
})(globalThis);
