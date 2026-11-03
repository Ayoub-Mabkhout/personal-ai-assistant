// Account-level choices kept on the server (/reminders): reminders, Diss mode and scheduled sprints. The last known values are
// remembered on this device only so the right screens show while offline; the server stays the source of truth.
import {api} from './api.js';

const KEY='train-settings';
let value=(()=>{try{return JSON.parse(localStorage.getItem(KEY))||{}}catch{return {}}})();
const keep=()=>{try{localStorage.setItem(KEY,JSON.stringify(value))}catch{}};
export const get=()=>value;
export const scheduledSprints=()=>!!value.scheduled_sprints;
export const diss=()=>!!value.roast;
export async function load(){try{value=await api('reminders');keep()}catch{}return value}
/** Resolves true when the server accepted the change. */
export async function save(patch){try{value=await api('reminders',{method:'PATCH',body:patch});keep();return true}catch{return false}}
