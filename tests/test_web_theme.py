"""Shared daylight controller and owner-only web preferences, using isolated data."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from personal_assistant.relay.store import Queue
from personal_assistant.relay.task_links import TaskLinks
from personal_assistant.relay.tasks import task_router

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
SETUP = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(SOURCE,'utf8');
function environment(now=Date.parse('2026-03-20T12:00:00Z'),dark=false){
  const values=new Map(),events=new Map(),documentEvents=new Map(),timers=new Map();let timerId=0;
  const query={matches:dark,addEventListener:(name,fn)=>query.listener=fn};
  class Clock extends Date { static now(){return now} }
  class Event {constructor(type){this.type=type}}
  const context={Date:Clock,Intl,Event,Math,Number,JSON,module:{exports:{}},
    localStorage:{getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)},
    document:{hidden:false,documentElement:{dataset:{}},querySelectorAll:()=>[],addEventListener:(name,fn)=>documentEvents.set(name,fn)},
    matchMedia:()=>query,addEventListener:(name,fn)=>{const list=events.get(name)||[];list.push(fn);events.set(name,list)},
    dispatchEvent:event=>(events.get(event.type)||[]).forEach(fn=>fn(event)),
    setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,at:now+delay});return id},clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(source,context);
  return {api:context.AssistantDaylight,context,values,query,timers,
    system:value=>{query.matches=value;query.listener?.()},
    event:(name,properties={})=>context.dispatchEvent({type:name,...properties}),
    advance:time=>{now=time;for(const [id,timer] of [...timers])if(timer.at<=now){timers.delete(id);timer.fn()}},
    visible:()=>{context.document.hidden=false;documentEvents.get('visibilitychange')?.()}};
}
'''


@unittest.skipUnless(NODE, 'Node runs the isolated shared JavaScript controller')
class WebThemeTests(unittest.TestCase):
    def run_js(self, body):
        setup = SETUP.replace('SOURCE', json.dumps(str(ROOT / 'apps/shared/daylight.js')))
        result = subprocess.run([NODE], input=setup+'\n'+body, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_neutral_solar_boundaries_and_polar_conditions(self):
        self.run_js(r'''
const e=environment(),a=e.api,place={latitude:0,longitude:0},noon=Date.parse('2026-03-20T12:00:00Z');
const phase=a.phase(noon,place);assert.equal(phase.dark,false);assert.ok(phase.next>noon);
assert.equal(a.phase(phase.next-1,place).dark,false);assert.equal(a.phase(phase.next+1,place).dark,true);
assert.ok(a.phase(phase.next+1,place).next>phase.next);
assert.equal(a.phase(Date.parse('2026-06-21T12:00:00Z'),{latitude:89.9,longitude:0}).dark,false);
assert.equal(a.phase(Date.parse('2026-12-21T12:00:00Z'),{latitude:89.9,longitude:0}).dark,true);
for(const p of [null,{}, {latitude:true,longitude:0},{latitude:'0',longitude:0},{latitude:91,longitude:0},{latitude:0,longitude:Infinity}])assert.equal(a.phase(noon,p),null);
''')

    def test_missing_preferences_follow_system_and_explicit_modes_persist(self):
        self.run_js(r'''
const e=environment(undefined,true),controller=e.api.create('isolated-theme','themechange');
assert.equal(controller.state().mode,'sun');assert.equal(controller.resolved(),'dark');assert.equal(controller.state().next,null);
assert.match(controller.describe(),/follows System/);e.system(false);assert.equal(controller.resolved(),'light');
controller.set('dark');assert.equal(e.values.get('isolated-theme'),'dark');e.system(false);assert.equal(controller.resolved(),'dark');
controller.set('light');assert.equal(controller.resolved(),'light');controller.set('unsupported');assert.equal(controller.mode(),'light');
controller.set('system');e.system(true);assert.equal(controller.resolved(),'dark');
''')

    def test_storage_changes_legacy_mode_and_private_configuration_whitelist(self):
        self.run_js(r'''
const e=environment(),controller=e.api.create('isolated-theme','themechange');
e.values.set('isolated-theme','');e.event('storage',{key:'isolated-theme'});assert.equal(controller.mode(),'system');
e.values.set('isolated-theme','dark');e.event('storage',{key:'isolated-theme'});assert.equal(controller.resolved(),'dark');
e.api.configure({latitude:0,longitude:0,private_label:'synthetic'});
assert.deepEqual(JSON.parse(e.values.get('assistant-daylight')),{latitude:0,longitude:0});
e.api.configure(null);assert.equal(e.values.has('assistant-daylight'),false);
''')

    def test_next_boundary_timer_and_foreground_refresh(self):
        self.run_js(r'''
const e=environment(),controller=e.api.create('isolated-theme','themechange');let notifications=0;
controller.subscribe(()=>notifications++);e.api.configure({latitude:0,longitude:0});
assert.equal(controller.resolved(),'light');const boundary=controller.state().next;
assert.equal(e.timers.size,1);e.advance(Math.ceil(boundary)+2);assert.equal(controller.resolved(),'dark');
assert.ok(controller.state().next>boundary);assert.ok(notifications>=2);
e.advance(Date.parse('2026-03-22T12:00:00Z'));e.visible();assert.equal(controller.resolved(),'light');assert.equal(e.timers.size,1);
''')

    def test_blocked_browser_storage_keeps_system_fallback(self):
        self.run_js(r'''
const e=environment(undefined,true);e.context.localStorage.getItem=()=>{throw Error('blocked')};e.context.localStorage.setItem=()=>{throw Error('blocked')};
const controller=e.api.create('isolated-theme','themechange');assert.equal(controller.resolved(),'dark');
controller.set('light');assert.equal(controller.resolved(),'light');e.event('focus');assert.equal(controller.resolved(),'light');
''')


class TaskWebPreferenceTests(unittest.TestCase):
    def test_owner_preferences_are_read_only_scoped_and_not_in_public_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings=root/'preferences.json'
            settings.write_text(json.dumps({'daylight':{'latitude':0,'longitude':0,'private_label':'synthetic'},'private_setting':'synthetic'}))
            queue=Queue(root/'queue.sqlite3',serial=True)
            links=TaskLinks(b'x'*32)
            def authorize(token):
                if token!='synthetic-owner': raise OSError('Rejected')
            app=FastAPI();app.include_router(task_router({'agent':queue,'command':queue},'https://example.com',ROOT/'apps/tasks',
                user_verifier=authorize,task_links=links,mobile_settings_file=settings))
            with TestClient(app) as client:
                endpoint='/tasks/v1/preferences'
                self.assertEqual(client.get(endpoint).status_code,401)
                for headers in ({'X-Task-View':links.token('agent','synthetic-task')},
                                {'X-Task-Followup':links.followup_token('agent','synthetic-task')},
                                {'Authorization':'Bearer synthetic-invalid'}):
                    self.assertEqual(client.get(endpoint,headers=headers).status_code,401)
                auth={'Authorization':'Bearer synthetic-owner'}
                response=client.get(endpoint,headers=auth)
                self.assertEqual(response.json(),{'daylight':{'latitude':0,'longitude':0}})
                self.assertEqual(response.headers['cache-control'],'private, no-store')
                self.assertNotIn(str(settings),response.text)
                self.assertNotIn('private_label',response.text)
                self.assertEqual(client.post(endpoint,headers=auth,json={'daylight':None}).status_code,405)
                before=settings.read_bytes();public=client.get('/tasks/daylight.js')
                self.assertEqual(public.status_code,200)
                self.assertNotIn('private_label',public.text)
                self.assertEqual(settings.read_bytes(),before)
                settings.unlink()
                self.assertEqual(client.get(endpoint,headers=auth).json(),{'daylight':None})


if __name__=='__main__': unittest.main()
