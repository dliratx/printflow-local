const {test}=require('node:test');const assert=require('node:assert/strict');
const {resolveModelLink,textModels,completedModel}=require('../web/static/model-links.js');
const files=[{id:'steve',name:'Minecraft Steve - black mouth v2.3mf',path:'library/Figures/steve/Minecraft Steve - black mouth v2.3mf'},{id:'portrait',name:'Portrait.stl',path:'designs/portrait/image_model.stl'}];
const message='[Preview](<C:/models/steve/preview.png>) Â· [Updated 3MF](<C:/Users/Example/Documents/PrintFlow/models/steve/Minecraft Steve - black mouth v2.3mf>)';
test('Windows markdown links map to imported library copies',()=>{assert.equal(textModels(message,files)[0].id,'steve');assert.equal(resolveModelLink('/api/files/portrait/preview',files).id,'portrait');});
test('unknown, external and ambiguous file paths never map to a guessed model',()=>{assert.equal(resolveModelLink('javascript:alert(1)',files),null);assert.equal(resolveModelLink('https://other.example/Portrait.stl',files),null);assert.equal(resolveModelLink('C:/foo/Portrait.stl',[...files,{id:'dup',name:'Portrait.stl',path:'elsewhere/p.stl'}]),null);});
test('request complete opens that chat model, not an unrelated newer upload',()=>{const state={files,chat:[{role:'user',text:'Fix Steve'},{role:'assistant',text:message}],codex:{busy:false,progress:{phase:'completed',started_at:'2026-10-24T16:40:00Z',finished_at:'2026-10-24T16:42:00Z'}},model_ready:{file_id:'portrait',at:'2026-10-24T16:47:00Z'}};assert.equal(completedModel(state).id,'steve');state.chat=[{role:'user',text:'Check status'}];assert.equal(completedModel(state),null);state.codex.busy=true;assert.equal(completedModel(state),null);});

test('prepared calibration links resolve the exact job and its library preview',()=>{
  const {resolveJobLink,completedJob}=require('../web/static/model-links.js');
  const jobs=[{id:'j',file_id:'steve',status:'ready',result:{project:'runs/run1/project.3mf'}},{id:'other',file_id:'portrait',result:{project:'runs/run2/project.3mf'}}];
  assert.equal(resolveJobLink('C:/Users/Owner/Print/runs/run1/project.3mf',jobs).id,'j');
  assert.equal(resolveJobLink('/api/jobs/j/download?kind=project',jobs).id,'j');
  for(const path of ['https://example.com/runs/run1/project.3mf','C:/unknown/project.3mf','javascript:/api/jobs/j/download'])assert.equal(resolveJobLink(path,jobs),null);
  const state={files,jobs,chat:[{role:'user',text:'Prepare overhangs'},{role:'assistant',text:'Existing [prepared 3MF](/api/jobs/j/download?kind=project) is ready.'}],codex:{busy:false,progress:{phase:'partial'}}};
  assert.equal(completedJob(state).id,'j');assert.equal(completedModel(state).id,'steve');
  state.chat.push({role:'user',text:'Different request'});assert.equal(completedJob(state),null);
});
