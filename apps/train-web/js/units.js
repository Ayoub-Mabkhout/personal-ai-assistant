// Records are always metric. These turn them into the owner's units for display and back on entry, as on Android.
import {athlete} from './store.js';
import {clock} from './core.js';

export const LB=0.45359237,MILE=1609.344;
const swapKey='train-units-swapped';
function swapped(){try{return JSON.parse(localStorage.getItem(swapKey))||{}}catch{return {}}}
export const imperial=exercise=>(athlete().units==='imperial')!==(exercise?!!swapped()[exercise]:false);
/** Some kit is marked in the other system, so one exercise can be logged that way while everything else stays as it is. */
export function flip(exercise){const s=swapped();s[exercise]=!s[exercise];try{localStorage.setItem(swapKey,JSON.stringify(s))}catch{}}
const round=v=>Number.isInteger(v)?String(v):(Math.round(v*10)/10).toFixed(1).replace(/\.0$/,'');
export const loadLabel=ex=>imperial(ex)?'lb':'kg';
export const distanceLabel=ex=>imperial(ex)?'mi':'km';
export const loadNumber=(kg,ex)=>round(Math.round((imperial(ex)?kg/LB:kg)*10)/10);
export const load=(kg,ex)=>loadNumber(kg,ex)+' '+loadLabel(ex);
export const loadIn=(shown,ex)=>imperial(ex)?shown*LB:shown;
export const loadValue=kg=>imperial()?kg/LB:kg;
export const total=kg=>Math.round(imperial()?kg/LB:kg).toLocaleString()+' '+loadLabel();
export const distanceNumber=(m,ex)=>(imperial(ex)?m/MILE:m/1000).toFixed(2).replace(/\.?0+$/,'');
export const distance=(m,ex)=>distanceNumber(m,ex)+' '+distanceLabel(ex);
export const distanceIn=(shown,ex)=>imperial(ex)?shown*MILE:shown*1000;
export const speedValue=kmh=>imperial()?kmh*1000/MILE:kmh;
export const speedLabel=()=>imperial()?'mph':'km/h';
export const speed=kmh=>round(Math.round(speedValue(kmh)*10)/10)+' '+speedLabel();
export const speedIn=shown=>imperial()?shown*MILE/1000:shown;
/** Minutes and seconds per kilometre or mile. */
export const pace=secondsPerKm=>clock(imperial()?secondsPerKm*MILE/1000:secondsPerKm)+'/'+distanceLabel();
