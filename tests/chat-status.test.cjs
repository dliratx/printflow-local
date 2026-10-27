const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const ctx = vm.createContext({});
vm.runInContext(readFileSync('web/static/chat-status.js', 'utf8') + '\nthis.view = chatStatusView;', ctx);
const now = Date.parse('2026-10-24T22:00:00Z');
const stamp = seconds => new Date(now - seconds * 1000).toISOString();
const active = {connected:true, authenticated:true, busy:true, progress:{phase:'tool',label:'Building the 3D model',started_at:stamp(80),last_event_at:stamp(2),steps:[]}};

test('shows actual phase and elapsed time, without an invented percentage', () => {
  const v = ctx.view(active, {now});
  assert.equal(v.label, 'Building the 3D model');
  assert.equal(v.elapsed, '1m 20s elapsed');
  assert.equal(v.animate, true);
});
test('a quiet request is labelled honestly and stops animating', () => {
  const v = ctx.view({...active,progress:{...active.progress,last_event_at:stamp(65)}}, {now});
  assert.equal(v.label, 'Waiting for an update');
  assert.match(v.detail, /1m 05s/);
  assert.equal(v.animate, false);
  assert.equal(v.canStop, true);
});
test('an approval wait is not confused with a slow calculation', () => {
  const v = ctx.view({...active,progress:{...active.progress,phase:'waiting',last_event_at:stamp(100)}}, {now});
  assert.equal(v.phase, 'waiting');
  assert.equal(v.animate, false);
  assert.match(v.detail, /response is needed/);
});
test('disconnection never looks like continuing work', () => {
  const v = ctx.view(active, {now,transportOffline:true});
  assert.equal(v.phase, 'disconnected');
  assert.equal(v.animate, false);
  assert.equal(v.canStop, false);
});
test('completed duration freezes and survives page reload', () => {
  const v = ctx.view({...active,busy:false,progress:{...active.progress,phase:'completed',label:'Request complete',finished_at:stamp(20)}}, {now});
  assert.equal(v.elapsed, '1m 00s elapsed');
  assert.equal(v.visible, true);
  assert.equal(v.animate, false);
});
test('failed actions remain visible after a completed response', () => {
  for(const progress of [
    {phase:'completed',steps:[{status:'failed'}]},
    {phase:'partial',label:'Response finished with issues',failed_actions:3}
  ]){
    const v=ctx.view({...active,busy:false,progress:{...active.progress,...progress,finished_at:stamp(20)}},{now});
    assert.equal(v.phase,'partial');assert.match(v.label,/issues/);
    assert.match(v.detail,/Some actions failed/);assert.equal(v.animate,false);assert.equal(v.canStop,false);
  }
});
