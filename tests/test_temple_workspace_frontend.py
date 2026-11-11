"""Exercise workspace state and selected-temple binding without a model call."""
from pathlib import Path
import subprocess


def test_workspace_selection_replacement_restore_and_reset():
    source = (Path(__file__).resolve().parents[1] / 'static/js/temple_workspace.js').read_text()
    source = '\n'.join(line for line in source.splitlines() if not line.startswith('import '))
    source = source.replace('export function ', 'function ')
    harness = r'''
const assert = require('node:assert/strict');
function h(tag, props={}, children=[]) {
  return {tag, props, children, append(...nodes){this.children.push(...nodes);},
    replaceChildren(...nodes){this.children=nodes;},
    querySelector(){return {focus(){}};}, setAttribute(k,v){this[k]=v;}};
}
const root=h('section'), chip={}, chat=h('button'), results=h('button');
const document={body:{dataset:{}},getElementById(id){
  return {templeWorkspace:root,templeFocus:chip,workspaceChatTab:chat,workspaceResultsTab:results}[id];
}};
const icon=()=>h('svg');
let renderedDetail;
const templeCard=(entry)=>{renderedDetail=entry;return h('detail');};
function find(node, predicate) {
  if(predicate(node)) return node;
  for(const child of node.children || []) {const found=find(child,predicate);if(found)return found;}
}
const ctx={refineTemple(){}};
const entry=(names, kind='temple_recommend')=>({data:{card:{kind,items:names.map(name=>({name,district:'海淀',sources:[]}))}}});
'''
    checks = r'''
resetTempleWorkspace();
assert.equal(results.disabled,true);
assert.equal(messageWithTempleContext('它几点关门'), '它几点关门');
const first=entry(['甲寺','乙寺','丙寺']);
first.data.card.travel={temple:'甲寺',weather:{}};
first.data.card.reviews={temple:'甲寺',items:[]};
assert.ok(renderWorkspaceEntry(first,ctx), 'recommendation produces a compact chat receipt');
assert.equal(results.textContent,'候选 3');
find(root,n=>n.props?.['aria-label']==='查看乙寺详情').props.onClick();
assert.equal(chip.textContent,'正在聊 · 乙寺');
assert.deepEqual(renderedDetail.data.card.items.map(i=>i.name),['乙寺']);
assert.equal(renderedDetail.data.card.travel,null,'another temple travel must not leak into selected detail');
assert.equal(renderedDetail.data.card.reviews,null);
assert.equal(messageWithTempleContext('它几点关门？'),'关于乙寺，它几点关门？');
assert.equal(messageWithTempleContext('第二座怎么去'),'关于乙寺，第二座怎么去');
assert.equal(messageWithTempleContext('换个推荐'),'换个推荐');
assert.equal(renderWorkspaceEntry(entry(['乙寺'],'temple_detail'),ctx),null,'follow-up must not append another full card or receipt');
find(root,n=>n.props?.['aria-label']==='返回候选列表').props.onClick();
assert.ok(find(root,n=>n.props?.['aria-label']==='查看甲寺详情'));
renderWorkspaceEntry(entry(['丁寺']),ctx,{restored:true});
assert.equal(results.textContent,'候选 1');
assert.equal(chip.hidden,true);
assert.equal(messageWithTempleContext('第一座怎么去'),'关于丁寺，第一座怎么去');
assert.equal(messageWithTempleContext('它几点关门'),'它几点关门','new recommendations clear stale focus');
resetTempleWorkspace('这次没有新的候选');
assert.equal(results.disabled,true);
assert.equal(chip.hidden,true);
assert.ok(find(root,n=>n.props?.text==='这次没有新的候选'));
assert.equal(document.body.dataset.workspaceView,'chat');
assert.equal(messageWithTempleContext('第一座怎么去'),'第一座怎么去');
renderWorkspaceEntry(entry(['戊寺'],'temple_detail'),ctx,{restored:true});
assert.equal(chip.textContent,'正在聊 · 戊寺');
assert.equal(results.textContent,'候选 1');
assert.equal(messageWithTempleContext('它需要预约吗'),'关于戊寺，它需要预约吗');
'''
    result = subprocess.run(['node', '-e', harness + source + checks], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
