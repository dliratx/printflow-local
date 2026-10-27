/* Explicit owner decisions only. Rendering and reconnecting never grant permissions. */
// State polls can arrive after newer SSE events. Never resurrect an old prompt.
let approvalSnapshot=null;
const retiredApprovalSessions=new Set();
function applyCodexApprovalState(c) {
  if(c.approval_session&&Number.isInteger(c.approval_revision)) {
    const current=approvalSnapshot;
    if(!retiredApprovalSessions.has(c.approval_session)&&(!current||current.approval_session!==c.approval_session||c.approval_revision>=current.approval_revision)) {
      if(current&&current.approval_session!==c.approval_session)retiredApprovalSessions.add(current.approval_session);
      approvalSnapshot={approval_session:c.approval_session,approval_revision:c.approval_revision,pending_approvals:c.pending_approvals||[]};
    }
  }
  if(approvalSnapshot)Object.assign(c,approvalSnapshot);
  return c;
}
function codexApprovalsChanged(data) {
  if(!ui.state?.codex)return;
  applyCodexApprovalState(data);Object.assign(ui.state.codex,{approval_session:data.approval_session,approval_revision:data.approval_revision,pending_approvals:data.pending_approvals||[]});
  syncCodexApprovals(ui.state.codex);renderApprovalSettings(ui.state.codex);
}
function resolveCodexApproval(id, message='This request is no longer pending.') {
  const key=String(id);
  for(const card of document.querySelectorAll('[data-approval-id]')) {
    if(card.dataset.approvalId!==key)continue;
    card.replaceChildren(el('p','',message));card.removeAttribute('data-approval-id');
  }
  ui.approvals.delete(key);
}
function syncCodexApprovals(c) {
  applyCodexApprovalState(c);
  if(!c.busy||!c.connected){for(const key of [...ui.approvals])resolveCodexApproval(key);return;}
  const pending=new Set((c.pending_approvals||[]).map(p=>String(p.id)));
  for(const key of [...ui.approvals])if(!pending.has(key))resolveCodexApproval(key);
  for(const request of c.pending_approvals||[])showApproval(request);
}
function showApproval(data) {
  const key=String(data.id);if(ui.approvals.has(key))return;
  if(!['decision','questions','mcp_confirmation'].includes(data.kind))return;
  ui.approvals.add(key);
  const card=el('section','approval-card');card.dataset.approvalId=key;
  card.append(el('h4','',data.kind==='questions'?'Your decision is needed':'Review this action'));
  const error=el('p','approval-error');error.setAttribute('role','alert');error.hidden=true;
  const controls=[],readers=new Map();let sending=false;
  async function reply(payload) {
    if(sending||!ui.approvals.has(key))return;
    sending=true;controls.forEach(c=>c.disabled=true);error.hidden=true;
    try {
      const result=await api('/api/codex/approval',{id:data.id,...payload});
      if(result.status==='expired') {
        const message='This request has ended. No decision was sent. Use the current request, or send your message again.';
        resolveCodexApproval(key,message);card.replaceChildren(el('p','',message));
        codexApprovalsChanged(result);scheduleRefresh();return;
      }
      if(result.ok!==true)throw new Error('The server did not confirm your decision. Refresh the request before trying again.');
      if(ui.state?.codex)ui.state.codex.pending_approvals=(ui.state.codex.pending_approvals||[]).filter(p=>String(p.id)!==key);
      const message=payload.decision==='accept'?'Your approval was sent for this action.':payload.decision==='decline'?'Request declined.':payload.decision==='cancel'?'Request cancelled.':'Your decision was sent.';
      resolveCodexApproval(key,message);card.replaceChildren(el('p','',message));
      if(result.approval_session)codexApprovalsChanged(result);
      scheduleRefresh();
    } catch(e) {
      if(e.message==='Approval request not found'){resolveCodexApproval(key,'This request has ended. No decision was sent.');scheduleRefresh();}
      else {error.textContent=e.message;error.hidden=false;scheduleRefresh();}
    }
    finally {sending=false;controls.forEach(c=>c.disabled=false);}
  }
  const actions=el('div','approval-actions');
  if(data.kind!=='questions') {
    if(data.server)card.append(el('p','approval-source','MCP server · '+data.server));
    card.append(el('p','',data.reason||'Review the requested action.'));
    if(data.tool_description)card.append(el('p','',data.tool_description));
    if(data.tool_params&&Object.keys(data.tool_params).length){const details=el('details','approval-parameters');details.append(el('summary','','Request details'),el('pre','approval-command',JSON.stringify(data.tool_params,null,2)));card.append(details);}
    if(data.command)card.append(el('pre','approval-command',Array.isArray(data.command)?data.command.join(' '):data.command));
    if(data.cwd)card.append(el('p','approval-path','Working directory: '+data.cwd));
    if(data.grant_root)card.append(el('p','approval-path','Requested path: '+data.grant_root));
    for(const decision of data.decisions||[]) {
      const label={accept:'Allow once',decline:'Decline',cancel:'Cancel'}[decision];if(!label)continue;
      const b=button(label,decision==='accept'?'primary small':'outline small',()=>reply({decision}));controls.push(b);actions.append(b);
    }
  } else {
    for(const [index,q] of (data.questions||[]).entries()) {
      const group=el('fieldset','approval-question');group.append(el('legend','',q.question));
      const radios=[];let free=null;
      for(const option of q.options||[]) {
        const label=el('label','approval-option'),radio=el('input');radio.type='radio';radio.name='approval-'+key+'-'+index;radio.value=option.label;
        const words=el('span');words.append(el('strong','',option.label));if(option.description)words.append(el('small','',option.description));
        label.append(radio,words);group.append(label);radios.push(radio);controls.push(radio);
      }
      if(!q.options?.length||q.isOther) {
        const label=el('label','approval-free',q.options?.length?'Or enter your answer':'Your answer');
        free=el('input');free.type=q.isSecret?'password':'text';free.maxLength=4000;free.autocomplete='off';
        free.addEventListener('input',()=>{if(free.value)radios.forEach(r=>r.checked=false);});
        radios.forEach(r=>r.addEventListener('change',()=>free.value=''));
        label.append(free);group.append(label);controls.push(free);
      }
      readers.set(q.id,()=>radios.find(r=>r.checked)?.value||free?.value||'');card.append(group);
    }
    const submit=button('Send decision','primary small',()=>{
      const answers=Object.fromEntries([...readers].map(([id,read])=>[id,read()]));
      if(!readers.size||Object.values(answers).some(a=>!a.trim())){error.textContent='Choose or enter an answer for each question.';error.hidden=false;return;}
      return reply({answers});
    });
    const decline=button('Decline','outline small',()=>reply({decision:'decline'}));controls.push(submit,decline);actions.append(submit,decline);
  }
  card.append(error,actions);$('chat-messages').append(card);ui.chatPinned=true;card.scrollIntoView({block:'nearest'});
}
let changingApprovalPolicy=false;
function renderApprovalSettings(c) {
  applyCodexApprovalState(c);
  const enabled=c.approval_policy==='on-request',toggle=$('chat-policy-toggle'),pending=Boolean(c.pending_approvals?.length);
  setText('chat-policy-label',pending?'Decision needed':enabled?'Ask before actions':'Prompts off');
  setText('chat-policy-detail',pending?'A tool is waiting for your decision.':enabled?'You decide when an action needs permission. Managed restrictions still apply.':'Actions needing permission are blocked. Enable prompts before sending a new request.');
  toggle.textContent=changingApprovalPolicy?'Saving…':enabled?'Turn off prompts':'Enable prompts';
  toggle.disabled=changingApprovalPolicy||Boolean(c.busy)||!c.connected||!c.authenticated||Boolean(ui.stateUnavailable);
  toggle.hidden=pending;$('chat-review-approval').hidden=!pending;
  if(c.approval_error){setText('chat-policy-error',c.approval_error);$('chat-policy-error').hidden=false;}
}
$('chat-review-approval').addEventListener('click',()=>{
  const card=document.querySelector('[data-approval-id]');if(!card)return;
  card.scrollIntoView({block:'start'});card.querySelector('button,input')?.focus({preventScroll:true});
});
$('chat-policy-toggle').addEventListener('click',async()=>{
  const c=ui.state?.codex;if(!c||c.busy||changingApprovalPolicy)return;
  changingApprovalPolicy=true;$('chat-policy-error').hidden=true;renderApprovalSettings(c);
  try {
    const result=await api('/api/codex/approval-policy',{policy:c.approval_policy==='on-request'?'never':'on-request'});
    if(!['never','on-request'].includes(result.approval_policy))throw new Error('The permission setting could not be confirmed.');
    c.approval_policy=result.approval_policy;
    toast(result.approval_policy==='on-request'?'Approval prompts enabled for your next request. Send the preparation request again.':'Approval prompts turned off.');
    scheduleRefresh();
  } catch(e) {setText('chat-policy-error',e.message);$('chat-policy-error').hidden=false;}
  finally {changingApprovalPolicy=false;renderApprovalSettings(c);}
});
