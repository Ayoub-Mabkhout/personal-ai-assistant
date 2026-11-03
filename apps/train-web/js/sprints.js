// Sprint order and colours, shared by the calendar bands, the sprint list and History, so a sprint keeps one colour everywhere.
import * as store from './store.js';
import {HUE} from './core.js';

const ORDER=[HUE.violet,HUE.teal,HUE.amber,HUE.blue,HUE.pink,HUE.green];
export const inOrder=()=>store.rows('sprint').filter(r=>r.data.status!=='cancelled').sort((a,b)=>String(a.data.start).localeCompare(String(b.data.start)));
export function hue(id){const i=inOrder().findIndex(r=>r.id===id);return ORDER[Math.max(0,i)%ORDER.length]}
export const bands=()=>inOrder().map(r=>({id:r.id,from:r.data.start,to:r.data.end||r.data.start,color:hue(r.id)}));
/** Days from today to an ISO date; negative when it has passed. */
export const daysUntil=iso=>Math.round((Date.parse(iso+'T00:00:00Z')-Date.parse(store.today()+'T00:00:00Z'))/86400000);
export const span=d=>fmt(d.start)+' – '+fmt(d.end);
export const fmt=(iso,year=true)=>iso?new Date(iso+'T12:00:00Z').toLocaleDateString(undefined,{day:'numeric',month:'short',...(year?{year:'numeric'}:{}),timeZone:'UTC'}):'';
