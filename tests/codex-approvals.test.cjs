const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');

function setup(reply){
  const all=[],nodes={},calls=[];
  class Element {
    constructor(tag='',className='',textContent=''){Object.assign(this,{tag,className,textContent,children:[],dataset:{},listeners:{},hidden:false});all.push(this);}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;}
    setAttribute(){} removeAttribute(name){if(name==='data-approval-id')delete this.dataset.approvalId;}
    addEventListener(type,fn){this.listeners[type]=fn;}
    scrollIntoView(){this.scrolled=true;}
    querySelector(){return this.children.find(c=>c.tag==='button');}
    focus(){}
  }
  const $=id=>nodes[id]??=new Element(),ui={approvals:new Set(),state:{codex:{connected:true,authenticated:true,busy:true,pending_approvals:[]}}};
  const context=vm.createContext({ui,$,el:(...a)=>new Element(...a),setText:(id,t)=>$(id).textContent=t,
    button:(label,cls,fn)=>Object.assign(new Element('button',cls,label),{click:fn}),
    document:{querySelectorAll:()=>all.filter(e=>'approvalId' in e.dataset),querySelector:()=>all.find(e=>'approvalId' in e.dataset)},
    api:async(path,body)=>{calls.push({path,body});return reply?reply(path,body):path.includes('approval-policy')?{approval_policy:body.policy}:{ok:true};},
    scheduleRefresh(){},toast(){}});
  vm.runInContext(fs.readFileSync('web/static/codex-approvals.js','utf8'),context);
  return {$,ui,calls,all,run:code=>vm.runInContext(code,context)};
}

test('MCP confirmation displays a real decision, sends it once and never grants on render',async()=>{
  const {run,all,calls,ui}=setup();
  run(`showApproval({id:0,kind:'mcp_confirmation',server:'printflow',reason:'Allow preparation?',tool_description:'Create local toolpaths',tool_params:{file_id:'model-1'},decisions:['accept','decline','cancel']})`);
  assert.equal(calls.length,0);assert.equal(ui.approvals.has('0'),true);
  assert.ok(all.some(e=>e.textContent==='MCP server · printflow'));
  assert.ok(all.some(e=>e.textContent==='Request details'));
  const allow=all.find(e=>e.textContent==='Allow once');assert.ok(allow);
  await allow.click();await allow.click();
  assert.equal(calls.length,1);assert.equal(calls[0].path,'/api/codex/approval');
  assert.equal(JSON.stringify(calls[0].body),JSON.stringify({id:0,decision:'accept'}));
  assert.equal(ui.approvals.size,0);
});

test('pending MCP requests survive refresh and resolved requests cannot be approved',async()=>{
  const {run,all,calls,ui}=setup();
  run(`ui.state.codex.pending_approvals=[{id:7,kind:'mcp_confirmation',reason:'Allow?',decisions:['accept','decline']}];syncCodexApprovals(ui.state.codex);syncCodexApprovals(ui.state.codex);`);
  assert.equal(all.filter(e=>e.dataset.approvalId==='7').length,1);
  const allow=all.find(e=>e.textContent==='Allow once');run('resolveCodexApproval(7)');await allow.click();
  assert.equal(calls.length,0);assert.equal(ui.approvals.size,0);
});

test('pinned permission control switches to Review request instead of changing policy during work',()=>{
  const {$,run,ui,calls}=setup();
  ui.state.codex.approval_policy='on-request';ui.state.codex.pending_approvals=[{id:0}];
  run('renderApprovalSettings(ui.state.codex)');
  assert.equal($('chat-policy-toggle').hidden,true);assert.equal($('chat-review-approval').hidden,false);
  assert.equal($('chat-policy-label').textContent,'Decision needed');assert.equal(calls.length,0);
});

test('a delayed poll cannot resurrect a resolved approval while the next request is waiting',async()=>{
  const {run,all,ui,calls}=setup();
  run(`codexApprovalsChanged({approval_session:'host-a',approval_revision:1,pending_approvals:[{id:'first',kind:'mcp_confirmation',reason:'Health check?',decisions:['accept']}]})`);
  const oldAllow=all.find(e=>e.textContent==='Allow once');
  run(`codexApprovalsChanged({approval_session:'host-a',approval_revision:3,pending_approvals:[{id:'second',kind:'mcp_confirmation',reason:'Inspect project?',decisions:['accept']}]})`);
  run(`Object.assign(ui.state.codex,{approval_session:'host-a',approval_revision:1,pending_approvals:[{id:'first',kind:'mcp_confirmation',decisions:['accept']}]});syncCodexApprovals(ui.state.codex)`);
  assert.deepEqual([...ui.approvals],['second']);await oldAllow.click();assert.equal(calls.length,0);
  assert.equal(ui.state.codex.approval_revision,3);
});

test('expired reply removes the dead buttons and keeps the current request available',async()=>{
  const {run,all,ui,calls}=setup(()=>({ok:false,status:'expired',approval_session:'host-a',approval_revision:2,pending_approvals:[]}));
  run(`codexApprovalsChanged({approval_session:'host-a',approval_revision:1,pending_approvals:[{id:'stale',kind:'mcp_confirmation',decisions:['accept']}]})`);
  const allow=all.find(e=>e.textContent==='Allow once');await allow.click();await allow.click();
  assert.equal(calls.length,1);assert.equal(ui.approvals.size,0);
  assert.ok(all.some(e=>e.textContent.startsWith('This request has ended.')));
  run(`codexApprovalsChanged({approval_session:'host-a',approval_revision:1,pending_approvals:[{id:'stale',kind:'mcp_confirmation',decisions:['accept']}]})`);
  assert.equal(ui.approvals.size,0);
});

test('a host restart replaces old prompts and late responses cannot restore the prior session',()=>{
  const {run,ui}=setup();
  run(`codexApprovalsChanged({approval_session:'old',approval_revision:100,pending_approvals:[{id:'a',kind:'mcp_confirmation',decisions:['accept']}]});codexApprovalsChanged({approval_session:'new',approval_revision:1,pending_approvals:[{id:'b',kind:'mcp_confirmation',decisions:['accept']}]});codexApprovalsChanged({approval_session:'old',approval_revision:101,pending_approvals:[]});`);
  assert.deepEqual([...ui.approvals],['b']);assert.equal(ui.state.codex.approval_session,'new');
});
