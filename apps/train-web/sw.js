// Static app shell only. API responses, photos and anything under /train/api never enter this cache.
const CACHE='train-static-v1',ROOT=new URL('./',self.location).pathname;
const FILES=['','index.html','app.js','style.css','onest.ttf','manifest.webmanifest','icon.svg','icon-192.png','icon-512.png',
  'js/core.js','js/glyphs.js','js/api.js','js/store.js','js/units.js','js/art.js','js/chart.js','js/calendar.js','js/nav.js','js/sprints.js',
  'js/settings.js','js/setup.js','js/live.js','js/history.js','js/plan.js','js/coach.js','js/body.js','js/screen.js'];
const ASSETS=FILES.map(f=>ROOT+f),API=ROOT+'api/';
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('train-static-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);if(event.request.method!=='GET'||url.origin!==self.location.origin||url.pathname.startsWith(API))return;
  // A page load with query parameters (an invite or a reminder) still gets the shell.
  const path=event.request.mode==='navigate'&&url.pathname===ROOT?ROOT:url.pathname;if(!ASSETS.includes(path))return;
  event.respondWith(fetch(event.request).then(response=>{if(response.ok){const copy=response.clone();caches.open(CACHE).then(c=>c.put(path,copy))}return response}).catch(()=>caches.match(path)));
});
/** {title,body,tag,url,image}; the photo also shows inside Train when the system leaves it out. */
self.addEventListener('push',event=>{
  let d={};try{d=event.data?event.data.json():{}}catch{d={title:'Train',body:event.data?.text()||''}}
  const options={body:d.body||'',tag:d.tag||undefined,data:{url:d.url||ROOT},icon:ROOT+'icon-192.png',badge:ROOT+'icon-192.png',renotify:!!d.tag};
  if(d.image)options.image=d.image;
  event.waitUntil(self.registration.showNotification(d.title||'Train',options));
});
self.addEventListener('notificationclick',event=>{
  event.notification.close();
  const target=new URL(event.notification.data?.url||ROOT,self.location.origin);if(target.origin!==self.location.origin||!target.pathname.startsWith(ROOT))target.href=new URL(ROOT,self.location.origin).href;
  const reminder=target.searchParams.get('reminder');
  event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(list=>{
    const open=list.find(c=>new URL(c.url).pathname.startsWith(ROOT));
    if(open){if(reminder)open.postMessage({reminder});return open.focus()}
    return self.clients.openWindow(target.href);
  }));
});
