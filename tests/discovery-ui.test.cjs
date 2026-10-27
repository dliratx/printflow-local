const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/static/marketplace.js','utf8');
class Element{
  constructor(tag='',cls='',text=''){this.tag=tag;this.textContent=text;this.children=[];this.value='';this.attributes={};this.classList={toggle(){},add(){},remove(){}};}
  append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;}
  setAttribute(k,v){this.attributes[k]=v;}
}
function context(){
  const c={el:(...args)=>new Element(...args),icon:()=>new Element('svg'),button:(text,cls,onclick)=>Object.assign(new Element('button',cls,text),{onclick}),
    marketState:{providers:[{id:'makerworld',name:'MakerWorld',search:'https://makerworld.com/en/search/models?keyword='}],search_engine:'Codex web search'},
    marketView:'search',marketItems:[],marketSearching:false,marketLastSearch:null,marketSelected:null,marketInspectVersion:0,
    marketResults:new Element(),marketCount:new Element(),marketNotice:new Element(),marketSearch:new Element(),marketQuery:new Element(),marketProvider:new Element(),marketBody:new Element(),
    renderMarketTabs(){},renderMarketIntro(){},setInterval(){return 1;},clearInterval(){},Date};
  vm.createContext(c);
  vm.runInContext(source.slice(source.indexOf('function marketSourceLink'),source.indexOf('async function loadMarketplace')),c);
  vm.runInContext(source.slice(source.indexOf('function renderMarketResults'),source.indexOf('function renderMarketIntro')),c);
  vm.runInContext(source.slice(source.indexOf('function appendMarketSourceLinks'),source.indexOf('marketToolbar.onsubmit')),c);
  return c;
}
function text(node){return String(node.textContent||'')+' '+node.children.map(text).join(' ');}
test('zero results and service failure never render the welcome state',()=>{
  const c=context();c.renderMarketResults();assert.match(text(c.marketResults),/What would/);
  for(const status of ['empty','error']){
    c.marketLastSearch={status,query:'tesla',provider:'all',source_links:[{name:'MakerWorld',url:'https://makerworld.com/en/search/models?keyword=tesla'}]};
    c.renderMarketResults();assert.doesNotMatch(text(c.marketResults),/What would/);assert.match(text(c.marketResults),/Retry search/);assert.match(text(c.marketResults),/MakerWorld/);
  }
});
test('search clears stale cards, shows progress, and restores controls after failure',async()=>{
  const c=context();c.marketItems=[{id:'old'}];c.marketQuery.value='tesla';c.marketProvider.value='all';
  let reject;c.api=()=>new Promise((_,r)=>reject=r);
  const pending=c.searchMarketplace();assert.equal(c.marketItems.length,0);assert.equal(c.marketSearch.disabled,true);assert.match(text(c.marketResults),/Finding models/);
  reject(new Error('Service down'));await pending;assert.equal(c.marketLastSearch.status,'error');assert.equal(c.marketSearch.disabled,false);assert.equal(c.marketResults.attributes['aria-busy'],'false');assert.match(text(c.marketResults),/Search is unavailable/);
});
test('a successful empty response keeps its query and source instead of the welcome message',async()=>{
  const c=context();c.marketQuery.value='nothing';c.marketProvider.value='makerworld';c.api=async()=>({query:'nothing',provider:'makerworld',status:'empty',items:[],source_links:[]});
  await c.searchMarketplace();assert.match(text(c.marketResults),/nothing/);assert.doesNotMatch(text(c.marketResults),/What would/);
});
test('load more keeps previous cards, deduplicates IDs and sends excluded listing URLs',async()=>{
  const c=context();c.marketItems=[{id:'first',title:'First',provider:'makerworld',url:'https://makerworld.com/en/models/12-first'}];
  c.marketLastSearch={query:'tesla',provider:'makerworld',page:1,next_page:2,has_more:true};let sent;
  c.api=async(_,b)=>{sent=b;return {query:'tesla',provider:'makerworld',page:2,status:'results',items:[c.marketItems[0],{id:'second',title:'Second',provider:'makerworld',url:'https://makerworld.com/en/models/13-second'}],source_links:[],has_more:true,next_page:3};};
  await c.searchMarketplace(true);assert.equal(sent.page,2);assert.equal(sent.exclude.length,1);assert.equal(c.marketItems.length,2);assert.match(text(c.marketResults),/Load more models/);
  c.api=async()=>({query:'tesla',provider:'makerworld',page:3,status:'empty',items:[],source_links:[],has_more:false});
  await c.searchMarketplace(true);assert.equal(c.marketItems.length,2);assert.match(text(c.marketNotice),/previous results are kept/);
});

const calibration=fs.readFileSync('web/static/calibration-ui.js','utf8');
test('calibration preparation, submission and physical completion are distinct',()=>{
  const printer={id:'u1',state:'standby',filename:''},session={context:{printer_id:'u1'}},job={id:'j',status:'ready'};
  const c={ui:{state:{printers:[printer]}},isJobReady:j=>j.status==='ready'};vm.createContext(c);
  vm.runInContext(calibration.slice(calibration.indexOf('function calibrationPrintState'),calibration.indexOf('function renderCalibrationOverview')),c);
  assert.equal(c.calibrationPrintState(session,[job]).phase,'ready');
  job.status='sent';assert.equal(c.calibrationPrintState(session,[job]).phase,'submitted');
  printer.state='printing';printer.filename='PrintFlow_j.gcode';assert.equal(c.calibrationPrintState(session,[job]).phase,'printing');
  printer.state='paused';assert.equal(c.calibrationPrintState(session,[job]).phase,'paused');
  printer.state='complete';session.completed_jobs=['j'];assert.equal(c.calibrationPrintState(session,[job]).phase,'completed');
  const other={id:'other',status:'ready'};assert.equal(c.calibrationPrintState(session,[other]).phase,'ready');
  other.status='error';assert.equal(c.calibrationPrintState(session,[other]).phase,'failed');
});

test('trial scores use only confirmed evidence from that trial and allow later failures',()=>{
  const code=fs.readFileSync('web/static/calibration-catalog.js','utf8'),c={};vm.createContext(c);
  vm.runInContext(code.slice(code.indexOf('function calibrationTrialScore'),code.indexOf('function renderCalibrationEvidence')),c);
  const s={observations:[{test_run_id:'old',source:'user_report',criteria:{bridges:'pass',surface:'pass'}},{test_run_id:'new',source:'provisional_analysis',criteria:{bridges:'pass',surface:'pass'}}]},run={id:'new'},spec={criteria:['bridges','surface']};
  assert.equal(c.calibrationTrialScore(s,run,spec).percent,0);
  s.observations.push({test_run_id:'new',source:'user_report',criteria:{bridges:'pass'}});assert.equal(c.calibrationTrialScore(s,run,spec).percent,50);
  s.observations.push({test_run_id:'new',source:'user_report',criteria:{bridges:'fail'}});assert.equal(c.calibrationTrialScore(s,run,spec).percent,0);
});

test('printing a chosen calibration variant keeps its exact job and hotend mapping',async()=>{
  let printed,requested;const c={api:async url=>{requested=url;return {recommended_job_id:'fine',printer_id:'u1',choices:[{job_id:'fine',mapping:{0:0}},{job_id:'alternate',name:'Alternate',mapping:{0:2}}]};},refresh:async()=>{},ui:{state:{jobs:[{id:'fine'},{id:'alternate'}]}},printJob:async(...args)=>{printed=args;},setText(){},toast(msg){throw Error(msg);}};vm.createContext(c);
  vm.runInContext(calibration.slice(calibration.indexOf('async function printCalibrationBenchmark'),calibration.indexOf('function calibrationPrintState')),c);
  await c.printCalibrationBenchmark({id:'s',context:{printer_name:'U1',tool_index:2}},'run','alternate');
  assert.match(requested,/test_run_id=run/);assert.equal(printed[0].id,'alternate');assert.equal(printed[2].mapping[0],2);
});
