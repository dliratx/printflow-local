'use strict';
let calibrationView='Overview',calibrationLaunching=false;
async function loadCalibration(){
  try{calibrationState=await api('/api/calibration',undefined,'GET');if(!activeCalibration&&calibrationState.sessions.length)activeCalibration=calibrationState.sessions.at(-1).id;renderCalibrationList();renderCalibrationDetail();}
  catch(e){calDetail.replaceChildren(el('p','work-notice',e.message));}
}
async function startCalibrationAI(session=null,testId=null){
  if(calibrationLaunching)return;const printer=selectedPrinter();
  if(!session&&!printer){toast('Select a connected printer first.',true);return;}
  calibrationLaunching=true;renderCalibrationDetail();
  try{await api('/api/calibration/assistant',{printer_id:session?.context.printer_id||printer.id,session_id:session?.id,test_id:testId});openChat();scheduleRefresh();}
  catch(e){toast(e.message,true);}
  finally{calibrationLaunching=false;renderCalibrationDetail();}
}
function renderCalibrationList(){
  calPage.classList.add('guided-calibration');calSide.replaceChildren();
  calSide.append(button('New AI calibration','primary',()=>startCalibrationAI(),'plus'),el('h3','','Your sessions'));
  if(!calibrationState.sessions.length)calSide.append(el('p','field-help','Your test history will appear here.'));
  for(const s of [...calibrationState.sessions].reverse()){
    const b=button(s.name,'session-tile'+(s.id===activeCalibration?' selected':''),()=>{activeCalibration=s.id;calibrationView='Overview';renderCalibrationList();renderCalibrationDetail();});
    b.append(el('small','',`${s.context.material} · Hotend ${s.context.tool_index+1}`),el('span','work-status',s.status==='awaiting_photos'?'Ready for your photos':`${s.results?.passed||0} / ${s.results?.total||6} goals confirmed`));calSide.append(b);
  }
  calSide.append(el('h3','','Reusable profiles'));
  if(!calibrationState.profiles.length)calSide.append(el('p','field-help','Tested settings will become reusable profiles.'));
  for(const p of [...calibrationState.profiles].reverse()){
    const card=el('div','profile-tile');card.append(el('strong','',p.name),el('span','work-status',`Revision ${p.revision||1} · ${p.status==='user_verified'?'Physically verified':'Experimental'}`),button('Refine with AI','outline',()=>refineCalibrationAI(p),'chat'));calSide.append(card);
  }
  const advanced=el('details','calibration-advanced');advanced.append(el('summary','','Manual setup'),button('Create session manually','outline',manualCalibration));calSide.append(advanced);
}
async function refineCalibrationAI(profile){
  const session=await action(()=>api('/api/calibration/profiles/'+profile.id+'/refine',{}));
  if(!session)return;activeCalibration=session.id;calibrationView='Overview';await loadCalibration();await startCalibrationAI(session);
}
function calibrationJobs(s,runId=null){const run=s?.test_runs?.find(r=>r.id===runId),ids=new Set(run?run.jobs:s?.jobs||[]);return (ui.state?.jobs||[]).filter(j=>ids.has(j.id)||ids.has(j.comparison_id));}
function benchmarkFile(s){const ids=new Set(calibrationJobs(s).map(j=>j.file_id));return ui.state?.files?.find(f=>ids.has(f.id))||ui.state?.files?.find(f=>f.path==='calibration-assets/3DBenchy.stl');}
function renderCalibrationDetail(){
  const s=calibrationState?.sessions.find(x=>x.id===activeCalibration);calDetail.replaceChildren();
  const header=el('div','work-heading'),title=el('div');title.append(el('h2','',s?.name||'Let AI guide your calibration'),el('p','field-help',s?`${s.context.printer_name} · Hotend ${s.context.tool_index+1} · ${s.context.filament_profile}`:'From the first benchmark to a reusable, tested profile.'));
  header.append(title,button('Refresh','outline',loadCalibration,'live'));calDetail.append(header);
  const tabs=el('div','work-tabs calibration-tabs'),content=el('div','work-tab-content calibration-content');
  const views={Overview:()=>renderCalibrationOverview(s,content),'Test library':()=>renderCalibrationCatalog(s,content),'Tests & photos':()=>s?renderCalibrationEvidence(s,content):renderCalibrationOverview(s,content),Results:()=>renderCalibrationResults(s,content),Profiles:()=>renderCalibrationProfiles(s,content),Guides:()=>renderGuide(content)};
  for(const [name,render] of Object.entries(views)){const b=button(name,'outline',()=>{calibrationView=name;tabs.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));content.replaceChildren();render();content.scrollTop=0;});b.classList.toggle('active',calibrationView===name);tabs.append(b);}
  calDetail.append(tabs,content);(views[calibrationView]||views.Overview)();
}
async function printCalibrationBenchmark(s,runId=null,jobId=null){
  try{
    const setup=await api('/api/calibration/'+s.id+'/print-setup'+(runId?'?test_run_id='+encodeURIComponent(runId):''),undefined,'GET');await refresh();
    const choice=setup.choices.find(x=>x.job_id===(jobId||setup.recommended_job_id)),job=ui.state.jobs.find(j=>j.id===choice?.job_id);
    if(!job)throw new Error('The prepared job is unavailable. Refresh and try again.');
    await printJob(job,null,{printerId:setup.printer_id,mapping:choice.mapping});
    setText('print-mapping-job',`${choice.name} · ${choice.time||'Time unavailable'} · ${choice.grams??'—'} g → ${s.context.printer_name} · H${s.context.tool_index+1}`);
  }catch(e){toast(e.message,true);}
}
function calibrationPrintState(s,jobs){
  const printer=ui.state?.printers?.find(p=>p.id===s?.context.printer_id),active=jobs.find(j=>printer?.filename==='PrintFlow_'+j.id+'.gcode');
  if(active&&['printing','paused'].includes(printer.state))return {phase:printer.state,printer,job:active};
  if(s?.completed_jobs?.some(id=>jobs.some(j=>j.id===id)))return {phase:'completed',printer};
  if(active&&['error','cancelled','shutdown'].includes(printer.state))return {phase:'failed',printer};
  if(jobs.some(j=>j.status==='sent'||j.print_outcome==='unknown'))return {phase:'submitted',printer};
  if(jobs.some(j=>isJobReady(j)&&!j.comparison_parent))return {phase:'ready',printer};
  if(jobs.some(j=>j.status==='error'))return {phase:'failed',printer};
  return {phase:jobs.some(j=>['queued','running','preparing','slicing'].includes(j.status))?'preparing':'new',printer};
}
function renderCalibrationOverview(s,c){
  const run=s?.test_runs?.find(r=>r.id===s.active_test_run_id)||s?.test_runs?.at(-1),spec=calibrationState.catalog?.tests.find(t=>t.id===(run?.test_id||'benchy')),testName=spec?.name||'Benchy';
  const jobs=calibrationJobs(s,run?.id),busy=Boolean(ui.state?.codex?.busy),printState=calibrationPrintState(s,jobs),ready=printState.phase==='ready',completed=printState.phase==='completed',printing=['printing','paused','submitted'].includes(printState.phase);
  const browse=el('section','calibration-browse');browse.append(el('div','','Choose the test for the problem you want to solve.'),button('Explore '+(calibrationState.catalog?.tests.length||'all')+' calibration tests','outline',()=>{calibrationView='Test library';calibrationCatalogSelection=null;renderCalibrationDetail();},'box'));c.append(browse);
  const hero=el('section','calibration-hero'),copy=el('div','calibration-hero-copy');
  copy.append(el('span','calibration-kicker','AI-GUIDED CALIBRATION'),el('h3','',printing?({printing:testName+' is printing',paused:testName+' is paused',submitted:'Print submitted · checking the printer'})[printState.phase]:completed?'Your test is ready to review':ready?testName+' is ready to print':'A better print starts with a measured test'),el('p','',printing?'Follow the live printer status. Once the print finishes, add photos and measurements here.':completed?'Add photos and describe the result. Codex will suggest the next adjustment.':ready?'Review the prepared variants and print on your selected hotend. Use the physical result to refine this profile.':'Choose a focused test or start with the original Benchy. Codex checks the loaded filament and prepares comparison settings.'));
  if(ready){copy.append(button('Print '+testName,'primary',()=>printCalibrationBenchmark(s,run?.id),'print'),el('small','field-help','Next: confirm the clear build plate and start the prepared print.'));}
  else if(printing){copy.append(button('View printer & camera','primary',()=>{ui.printerId=s.context.printer_id;showPage('overview');},'live'));}
  else if(completed){copy.append(button('Add photos & evaluate','primary',()=>{calibrationEvidenceRun=run?.id||'';calibrationView='Tests & photos';renderCalibrationDetail();},'upload'));}
  else{const start=button(calibrationLaunching?'Starting…':busy?'View AI progress':s?'Continue with AI':'Start with AI','primary',()=>busy?openChat():startCalibrationAI(s),'chat');start.disabled=calibrationLaunching;copy.append(start);}
  if(ready)copy.append(button('Discuss settings with AI','outline',()=>startCalibrationAI(s),'chat'));
  const model=el('div','calibration-benchmark'),file=run?ui.state?.files.find(f=>f.id===run.file_id):benchmarkFile(s);
  if(file){const preview=button('','benchmark-preview',()=>selectFile(file.id));const img=el('img');img.src='/api/files/'+file.id+'/thumbnail?v=4';img.alt=testName;preview.append(img,el('span','','Open 3D preview'));model.append(preview);}else model.append(icon('box'),el('strong','',testName),el('span','','Loaded automatically by the assistant'));
  model.append(el('small','',spec?.nominal||'Original scale · No supports'));hero.append(copy,model);c.append(hero);
  const steps=el('ol','calibration-journey');for(const [i,label,detail,done] of [[1,'Prepare','Check material & slice',jobs.length>0],[2,'Print',printing?'Print in progress':ready?'Ready to start':'Confirm plate & start',completed],[3,'Review','Photos & physical checks',Boolean(s?.observations?.length)],[4,'Save & refine','Keep every revision',calibrationState.profiles.some(p=>p.session_id===s?.id)]]){const item=el('li',done?'done':'');item.append(el('span','journey-number',done?'✓':String(i)),el('strong','',label),el('small','',detail));steps.append(item);}c.append(steps);
  appendCalibrationScore(c,s);
  const actions=el('div','calibration-next-actions');if(ready)actions.append(button('Review prepared tests','outline',()=>showPage('jobs'),'print'));if(completed||s?.photos?.length)actions.append(button('Add photos & review','outline',()=>{calibrationView='Tests & photos';renderCalibrationDetail();},'upload'));c.append(actions);
  if(s?.parent_profile_id){const p=calibrationState.profiles.find(p=>p.id===s.parent_profile_id);c.append(el('p','field-help',`Refining ${p?.name||'saved profile'}, revision ${p?.revision||1}. Previous settings and evidence are preserved; this test starts with pending results.`));}
}
function appendCalibrationScore(c,s){
  const r=s?.results||{passed:0,total:6,assessed:0,goals_met_percent:0,coverage_percent:0};const box=el('section','calibration-score');
  const metric=el('div','score-number');metric.append(el('strong','',r.goals_met_percent+'%'),el('span','','goals met'));
  const detail=el('div','score-detail');detail.append(el('h3','',`${r.passed} of ${r.total} goals confirmed`),el('p','',`${r.assessed} assessed · ${r.total-r.assessed} pending · ${r.coverage_percent}% test coverage`));
  const track=el('div','score-track');track.setAttribute('role','meter');track.setAttribute('aria-label','Confirmed calibration goals');track.setAttribute('aria-valuemin','0');track.setAttribute('aria-valuemax',String(r.total));track.setAttribute('aria-valuenow',String(r.passed));const fill=el('span');fill.style.width=r.goals_met_percent+'%';track.append(fill);detail.append(track,el('small','','Based on confirmed checks. Unmeasured goals stay pending.'));box.append(metric,detail);c.append(box);
}
function renderCalibrationResults(s,c){
  appendCalibrationScore(c,s);const grid=el('div','calibration-result-grid');
  for(const criterion of s?.results?.criteria||calibrationState.criteria||[]){const card=el('article','calibration-result-card');card.dataset.status=criterion.status||'pending';const heading=el('div');heading.append(el('h3','',criterion.name),el('span','result-state',({pass:'Passed',fail:'Needs work',pending:'Pending'})[criterion.status]||'Pending'));card.append(heading,el('p','',criterion.description));if(criterion.notes)card.append(el('p','result-evidence',criterion.notes));if(criterion.provisional)card.append(el('small','','AI suggestion available · awaiting physical confirmation'));grid.append(card);}c.append(grid);
  if(s){c.append(button('Discuss results with AI','primary',()=>startCalibrationAI(s),'chat'));const manual=el('details','calibration-advanced');manual.append(el('summary','','Record a physical observation'));const form=el('div');renderObservations(s,form);manual.append(form);c.append(manual);}
}
function renderCalibrationProfiles(s,c){
  c.append(el('h3','','Keep improving the same profile'),el('p','field-help','Each refinement creates a new revision. Earlier settings and their physical evidence remain available.'));
  for(const p of calibrationState.profiles.filter(p=>!s||p.context.printer_id===s.context.printer_id)){
    const card=el('article','profile-tile');card.append(el('h3','',p.name),el('p','work-status',`Revision ${p.revision||1} · ${p.status==='user_verified'?'Physically verified':'Experimental'} · ${p.results?.passed||0}/6 goals confirmed`),button('Refine with AI','primary',()=>refineCalibrationAI(p),'chat'));c.append(card);
  }
  if(!calibrationState.profiles.length)c.append(el('p','work-notice','No tested profile yet. Complete a physical benchmark and review its results with Codex.'));
  if(s){c.append(button('Review settings with AI','outline',()=>startCalibrationAI(s),'chat'));const manual=el('details','calibration-advanced');manual.append(el('summary','','Save tested settings manually'));const form=el('div');renderProfileForm(s,form);manual.append(form);c.append(manual);}
}

// Refresh the overview while preparation/review progresses; never replace editable forms.
let calibrationPolling=false,calibrationPollSignature='';
setInterval(async()=>{if(ui.page!=='calibration'||!['Overview','Test library'].includes(calibrationView)||calibrationPolling||document.hidden)return;calibrationPolling=true;try{const value=await api('/api/calibration',undefined,'GET');if(ui.page==='calibration'&&['Overview','Test library'].includes(calibrationView)){const signature=JSON.stringify([ui.state?.codex?.busy,ui.state?.printers?.map(p=>[p.id,p.state,p.filename]),calibrationJobs(value.sessions.find(s=>s.id===activeCalibration)).map(j=>[j.id,j.status])]);const changed=JSON.stringify(calibrationState)!==JSON.stringify(value);calibrationState=value;if(changed||signature!==calibrationPollSignature){const scroll=calDetail.scrollTop;renderCalibrationList();renderCalibrationDetail();calDetail.scrollTop=scroll;calibrationPollSignature=signature;}}}catch{}finally{calibrationPolling=false;}},8000);
