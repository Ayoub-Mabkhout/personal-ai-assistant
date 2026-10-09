"""Runs the groceries page's own outbox, overlay and toast code in Node's vm with stubbed browser globals."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'apps/groceries/app.js'

DRIVER = r'''
const fs=require('fs'),vm=require('vm');
const src=fs.readFileSync(process.argv[2],'utf8');
function grab(name){
  const start=src.search(new RegExp('^(?:async )?(?:function|const) '+name+'\\b','m'));
  if(start<0)throw Error('app.js no longer declares '+name);
  if(src.startsWith('const',start))return src.slice(start,src.indexOf('\n',start));
  let depth=0;
  for(let i=start+src.slice(start).search(/\)\s*\{/);i<src.length;i++){
    if(src[i]==='{')depth++;
    else if(src[i]==='}'&&--depth===0)return src.slice(start,i+1);
  }
  throw Error('unbalanced '+name);
}
const make=(names,globals,state)=>{
  const ctx=vm.createContext({console,Error,Object,Map,JSON,...globals});
  vm.runInContext(names.map(grab).join('\n')+'\n'+state,ctx);
  return ctx;
};
const out={};

// outbox policy: which HTTP statuses park a change for review and which keep it at the head of the queue
let ctx=make(['rejected','reason'],{},'');
out.parked={};
for(const status of [400,401,403,404,405,408,409,413,422,425,429,500,502,503])out.parked[status]=vm.runInContext('rejected({status:'+status+'})',ctx);
out.reason413=vm.runInContext('reason({status:413,message:"x"})',ctx);
out.reason422=vm.runInContext('reason({status:422,message:"Recipe not found."})',ctx);

// sync loop
const globals={
  navigator:{onLine:true},toast(){},setStatus(){},render(){},openReview(){},saveQueue(){},saveFailures(){},write(){},setTimeout:()=>0,
  report:e=>{out.lastReport=e.state||e.message},
  fault:(state,label,detail='')=>Object.assign(Error(label),{state,label,detail}),
};
ctx=make(['rejected','reason','park','persist','sync'],globals,'let syncing=false,again=false,ready=false,synced=false,snapshot={items:[],recipes:[]},queue=[],failures=[],tokens=null;');
async function run(ids,answers,{online=true,signedIn=true}={}){
  const sent=[];
  ctx.navigator.onLine=online;
  vm.runInContext('queue='+JSON.stringify(ids.map(id=>({id})))+';failures=[];syncing=false;tokens='+(signedIn?'{access_token:"t"}':'null'),ctx);
  ctx.api=async(path,body)=>{
    if(path==='list')return {items:[]};
    sent.push(body.id);
    if(answers[body.id])throw Object.assign(Error('status '+answers[body.id]),{status:answers[body.id]});
    return {saved:true};
  };
  await vm.runInContext('sync()',ctx);
  return {sent,...JSON.parse(vm.runInContext('JSON.stringify({queue:queue.map(x=>x.id),failures:failures.map(x=>[x.change.id,x.error])})',ctx))};
}
(async()=>{
  out.loop={
    parkedHeadDoesNotBlock:await run(['a','b'],{a:422}),
    conflict:await run(['a'],{a:409}),
    notFoundStays:await run(['a','b'],{a:404}),
    serverErrorStays:await run(['a','b'],{a:500}),
    rateLimitStays:await run(['a','b'],{a:429}),
    authStays:await run(['a','b'],{a:401}),
    offline:await run(['a'],{},{online:false}),
    signedOut:await run(['a'],{},{signedIn:false}),
    allSent:await run(['a','b'],{}),
  };

  // a staged removal stays on screen, flagged, until it is committed
  ctx=make(['overlay','bought'],{},`
    const snapshot={items:[{id:'i1',name:'Bananas',complete:0,version:1},{id:'i2',name:'Milk',complete:0,version:1},{id:'i3',name:'Eggs',complete:1,version:1}]};
    const queue=[{operation:'delete',target:'i3'}];
    const staged=new Map([['i1',{change:{operation:'delete',target:'i1'}}],['i2',{change:{operation:'complete',target:'i2',complete:true}}]]);`);
  out.overlay=JSON.parse(vm.runInContext('JSON.stringify(overlay())',ctx));
  out.bought=JSON.parse(vm.runInContext('JSON.stringify([bought({held:true,removed:true,complete:0}),bought({held:true,removed:true,complete:1}),bought({held:true,complete:1}),bought({held:true,complete:0}),bought({complete:1})])',ctx));

  // an identical toast is not shown twice in a row
  const box={className:'',classList:{add(){},remove(){}},setAttribute(){},replaceChildren(){},append(){},style:{},offsetWidth:0,hidden:true};
  ctx=make(['toast','showToast','dismissToast'],{$:()=>box,el:(tag,text)=>({tag,text}),button:label=>({label}),reduced:()=>true,setTimeout:()=>1,clearTimeout(){}},'const toasts={queue:[],current:null,timer:0,exit:0};');
  vm.runInContext("for(let i=0;i<3;i++)toast('Choose at least one ingredient.',{kind:'error'})",ctx);
  out.sameToast=vm.runInContext('toasts.queue.length',ctx);
  vm.runInContext("toast('Other.')",ctx);vm.runInContext("toast('Other.')",ctx);
  out.otherToast=vm.runInContext('toasts.queue.length',ctx);
  console.log(JSON.stringify(out));
})();
'''


@unittest.skipUnless(shutil.which('node'), 'Node is needed to run the page script')
class GroceriesPageLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as raw:
            driver = Path(raw) / 'driver.js'
            driver.write_text(DRIVER, encoding='utf-8')
            done = subprocess.run([shutil.which('node'), str(driver), str(APP)], capture_output=True, text=True, timeout=60)
        if done.returncode:
            raise AssertionError(done.stderr)
        cls.out = json.loads(done.stdout)

    def test_only_permanent_rejections_are_parked_for_review(self):
        parked = {int(status) for status, value in self.out['parked'].items() if value}
        self.assertEqual(parked, {409, 413, 422})
        self.assertIn('too large', self.out['reason413'])
        self.assertEqual(self.out['reason422'], 'Recipe not found.')

    def test_parked_change_does_not_block_those_behind_it(self):
        loop = self.out['loop']
        self.assertEqual(loop['parkedHeadDoesNotBlock'], {'sent': ['a', 'b'], 'queue': [], 'failures': [['a', 'status 422']]})
        self.assertEqual(loop['conflict']['failures'], [['a', 'status 409']])
        self.assertEqual(loop['allSent'], {'sent': ['a', 'b'], 'queue': [], 'failures': []})

    def test_transient_failures_keep_the_head_of_the_queue(self):
        for name in ('notFoundStays', 'serverErrorStays', 'rateLimitStays', 'authStays'):
            with self.subTest(name):
                self.assertEqual(self.out['loop'][name], {'sent': ['a'], 'queue': ['a', 'b'], 'failures': []})
        for name in ('offline', 'signedOut'):
            with self.subTest(name):
                self.assertEqual(self.out['loop'][name], {'sent': [], 'queue': ['a'], 'failures': []})

    def test_staged_removal_stays_visible_until_committed(self):
        rows = {row['id']: row for row in self.out['overlay']}
        self.assertEqual(sorted(rows), ['i1', 'i2'])
        self.assertTrue(rows['i1']['held'] and rows['i1']['removed'])
        self.assertTrue(rows['i2']['held'] and rows['i2']['complete'] == 1 and not rows['i2'].get('removed'))
        self.assertEqual(self.out['bought'], [False, True, False, True, True])

    def test_repeated_toast_is_not_queued_behind_itself(self):
        self.assertEqual(self.out['sameToast'], 0)
        self.assertEqual(self.out['otherToast'], 1)


if __name__ == '__main__':
    unittest.main()
