"""Check detail shortcuts share the composer's send lock without replacing drafts."""
from pathlib import Path
import subprocess


def test_detail_shortcuts_send_immediately_and_preserve_draft():
    script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements={};
for(const id of ['composerInput','composerError','btnSend','composer']) elements[id]={value:'未发送的草稿',style:{},classList:{toggle(){}},setAttribute(){},focus(){},addEventListener(){},scrollHeight:40};
const ctx=vm.createContext({$:id=>elements[id],window:{innerHeight:900,addEventListener(){}},document:{body:{dataset:{}}}});
const source=fs.readFileSync('static/js/composer.js','utf8').replace(/^import .*;\n/gm,'').replace(/export /g,'');
vm.runInContext(source,ctx);
(async()=>{
let release; const calls=[];
ctx.handler=({text})=>{calls.push(text);return new Promise(r=>release=r);};
vm.runInContext('initComposer({onSubmit:handler})',ctx);
const first=vm.runInContext('submitPrompt("白云观开放时间和预约购票要求是什么？")',ctx);
assert.deepEqual(calls,['白云观开放时间和预约购票要求是什么？']);
assert.equal(elements.composerInput.value,'未发送的草稿');
assert.equal(elements.btnSend.disabled,true);
await vm.runInContext('submitPrompt("白云观怎么去？")',ctx);
assert.equal(calls.length,1);
assert.match(elements.composerError.textContent,/上一条/);
release(); await first;
assert.equal(elements.btnSend.disabled,false);
ctx.handler=async({text})=>calls.push(text);vm.runInContext('initComposer({onSubmit:handler})',ctx);
await vm.runInContext('submit()',ctx);
assert.equal(calls[1],'未发送的草稿');assert.equal(elements.composerInput.value,'');
ctx.handler=async()=>{throw Error('failure');};vm.runInContext('initComposer({onSubmit:handler})',ctx);
await assert.rejects(vm.runInContext('submitPrompt("重试问题")',ctx),/failure/);
assert.equal(elements.btnSend.disabled,false);
const flows=fs.readFileSync('static/js/flows.js','utf8');
assert.match(flows,/refineTemple: \(text\) => \{ showConversation\(\); return submitPrompt\(text\); \}/);
console.log('PASS: immediate send, draft preserved, duplicate blocked, typed send and error recovery');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(
        ["node", "-e", script], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
