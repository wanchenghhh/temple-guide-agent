"""Home starts a fresh search, while workspace follow-ups retain their thread."""
from pathlib import Path
import subprocess


def test_home_search_isolated_from_previous_visit():
    script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),{webcrypto}=require('node:crypto');
const source=name=>fs.readFileSync(`static/js/${name}.js`,'utf8');
const clean=s=>s.replace(/import\s+[\s\S]*?from\s+"[^"]+";/g,'').replace(/\bexport /g,'');
const storage=new Map([['ja.chat.thread.v1:u','old-thread']]),requests=[],shown=[];
let serial=0,selected='白云观',clears=0;
const sandbox={console,Map,Set,Date,Uint8Array,AbortController,crypto:webcrypto,
window:{setTimeout,clearTimeout,addEventListener(){}},document:{body:{dataset:{screen:'home'}}},requestAnimationFrame:fn=>fn(),
currentUserId:()=> 'u',sessionReady:()=>true,ensureSession:async()=>{},
localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
fetch:async(path,opts)=>{requests.push(JSON.parse(opts.body));return {ok:true,status:200,text:async()=>JSON.stringify({status:'chat',thread_id:'new-thread',data:{messages:[{role:'assistant',content:'本次推荐'}]}}),headers:{get:()=>''}};},
nextId:()=>`e${++serial}`,enterWorkspace:()=>{sandbox.document.body.dataset.screen='workspace';},
messageWithTempleContext:t=>selected?`关于${selected}，${t}`:t,
resetTempleWorkspace:()=>{selected=null;},clearLog:()=>{clears++;shown.length=0;},
userMessage:d=>{shown.push(d.text);},assistantMessage:t=>{shown.push(t);},
typing:()=>({done(){}}),isNewTempleSearch:()=>true};
const flows=source('flows');
for(const s of [source('api'),flows]) for(const m of s.matchAll(/import\s+\{([\s\S]*?)\}\s+from/g)) for(const n of m[1].split(',').map(n=>n.trim()).filter(Boolean)) if(!(n in sandbox))sandbox[n]=()=>{};
const ctx=vm.createContext(sandbox);
vm.runInContext(clean(source('api'))+'\nthis.api=api;',ctx);
vm.runInContext(clean(source('store'))+'\nthis.store=store;',ctx);
vm.runInContext(clean(flows),ctx);
(async()=>{
sandbox.store.add({id:'old',type:'assistant',data:{text:'之前的白云观和日期'}});
await vm.runInContext('sendComposer({text:"想找个人少安静的寺庙走走，不限区域"})',ctx);
assert.equal(requests[0].thread_id,null,'home must start a fresh server thread');
assert.equal(requests[0].message,'想找个人少安静的寺庙走走，不限区域');
assert.equal(selected,null);assert.equal(clears,1);
assert.ok(!shown.includes('之前的白云观和日期'));
await vm.runInContext('sendComposer({text:"哪个更安静？"})',ctx);
assert.equal(requests[1].thread_id,'new-thread','workspace follow-up keeps new conversation');assert.equal(clears,1);
shown.length=0;vm.runInContext('restoreTranscript()',ctx);
assert.ok(shown.includes('本次推荐'));assert.ok(!shown.includes('之前的白云观和日期'),'reload must not replay previous candidates');
assert.ok(sandbox.store.entries().some(e=>e.id==='old'),'new search does not delete saved old entries');
console.log('PASS: new home search, clean selection, follow-up continuity and reload boundary');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(["node", "-e", script],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
