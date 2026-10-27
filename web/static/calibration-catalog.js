'use strict';
let calibrationCatalogSelection=null,calibrationCategory='all',calibrationSearch='',calibrationEvidenceRun='',calibrationPreparing=false;
function catalogTest(id){return calibrationState?.catalog?.tests.find(t=>t.id===id);}
function catalogRun(s,testId){return [...(s?.test_runs||[])].reverse().find(r=>r.test_id===testId);}
function selectCalibrationTest(id){calibrationCatalogSelection=id;calibrationView='Test library';renderCalibrationDetail();}
function catalogLink(source){const a=el('a','button outline small',source.title+' ↗');a.href=source.url;a.target='_blank';a.rel='noopener noreferrer';return a;}
function testImage(spec){const frame=el('div','test-image');if(spec.mode==='native'){frame.classList.add('native-test');frame.append(icon('settings'),el('span','','Native calibration'));}else{const image=el('img');image.src='/api/calibration/catalog/'+spec.id+'/thumbnail?v=2-'+spec.version;image.alt=spec.name;image.loading='lazy';image.onerror=()=>{image.remove();frame.append(icon('box'),el('span','','Preview loads with the CAD service'));};frame.append(image);}return frame;}
function renderCalibrationCatalog(s,c){
  if(calibrationCatalogSelection){const spec=catalogTest(calibrationCatalogSelection);if(spec){renderCalibrationProtocol(s,spec,c);return;}calibrationCatalogSelection=null;}
  c.append(el('h3','','Find the right test'),el('p','field-help','Use Benchy for an overall comparison, then choose a focused test for the defect. Keep the same printer, hotend and filament throughout a session.'));
  const toolbar=el('div','test-catalog-toolbar'),query=textInput(calibrationSearch),category=el('select');query.placeholder='Search tests, defects or measurements…';query.setAttribute('aria-label','Filter calibration tests');options(category,[['all','All categories'],...(calibrationState.catalog?.categories||[]).map(x=>[x.id,x.name])]);category.value=calibrationCategory;category.setAttribute('aria-label','Calibration category');toolbar.append(query,category);c.append(toolbar);
  const grid=el('div','test-catalog-grid');c.append(grid);
  const render=()=>{
    grid.replaceChildren();const terms=calibrationSearch.toLowerCase();
    const specs=(calibrationState.catalog?.tests||[]).filter(t=>(calibrationCategory==='all'||t.category===calibrationCategory)&&(!terms||[t.name,t.summary,...t.measures].join(' ').toLowerCase().includes(terms)));
    if(!specs.length)grid.append(el('p','field-help','No tests match this filter. Try another term.'));
    for(const spec of specs){
      const card=el('article','test-catalog-card'),top=el('div','test-card-heading'),copy=el('div');copy.append(el('span','calibration-kicker',calibrationState.catalog.categories.find(x=>x.id===spec.category)?.name||spec.category),el('h3','',spec.name),el('p','',spec.summary));top.append(testImage(spec),copy);card.append(top,el('span','test-nominal',spec.nominal));
      const run=catalogRun(s,spec.id);if(run){const status=calibrationPrintState(s,calibrationJobs(s,run.id));card.append(el('small','test-run-state',`Latest run · ${status.phase} · ${new Date(run.created_at).toLocaleDateString()}`));}
      card.append(button(spec.mode==='native'?'View native test & guide':'View test & prepare','outline',()=>selectCalibrationTest(spec.id),'arrow'));grid.append(card);
    }
  };
  query.oninput=()=>{calibrationSearch=query.value;render();};category.onchange=()=>{calibrationCategory=category.value;render();};render();
}
async function prepareCatalogTest(s,spec,repeat=false){
  if(!s){await startCalibrationAI(null,spec.id);return;}
  if(calibrationPreparing)return;calibrationPreparing=true;renderCalibrationDetail();
  try{
    const value=await api('/api/calibration/'+s.id+'/tests/'+spec.id+'/prepare',{repeat});calibrationEvidenceRun=value.run.id;
    await refresh();await loadCalibration();toast(value.reused?'Existing comparison opened.':'Model loaded. Orca is preparing the comparison.');
  }catch(e){toast(e.message,true);}finally{calibrationPreparing=false;renderCalibrationDetail();}
}
function renderCalibrationProtocol(s,spec,c){
  c.append(button('All calibration tests','outline small',()=>{calibrationCatalogSelection=null;renderCalibrationDetail();},'arrow'));
  const hero=el('section','test-protocol-hero'),heading=el('div');heading.append(el('span','calibration-kicker',spec.mode==='native'?'NATIVE CALIBRATION':'PRINTABLE TEST · VERSION '+spec.version),el('h2','',spec.name),el('p','',spec.summary),el('strong','test-nominal',spec.nominal));hero.append(heading,testImage(spec));c.append(hero);
  const blocks=el('div','test-protocol-grid'),measures=el('section');measures.append(el('h3','','What it evaluates'));const list=el('ul');for(const text of spec.measures)list.append(el('li','',text));measures.append(list);
  const reading=el('section');reading.append(el('h3','','How to read the result'),el('p','',spec.readout));blocks.append(measures,reading);c.append(blocks,el('p','test-limit',spec.limits));
  const run=catalogRun(s,spec.id),jobs=run?calibrationJobs(s,run.id):[],state=calibrationPrintState(s,jobs),actions=el('div','test-actions'),busy=Boolean(ui.state?.codex?.busy);
  if(run&&state.phase==='ready')actions.append(button('Print this test','primary',()=>printCalibrationBenchmark(s,run.id),'print'));
  if(['printing','paused','submitted'].includes(state.phase))actions.append(button('View printer & camera','primary',()=>{ui.printerId=s.context.printer_id;showPage('overview');},'live'));
  const ai=button(busy?'View AI progress':state.phase==='ready'?'Review prepared test with AI':'Prepare with AI',run?'outline':'primary',()=>busy?openChat():startCalibrationAI(s,spec.id),'chat');ai.disabled=calibrationLaunching;actions.append(ai);
  if(spec.mode!=='native'){
    const direct=button(calibrationPreparing?'Preparing…':run?'Prepare a new trial':'Prepare comparison','outline',()=>prepareCatalogTest(s,spec,Boolean(run)),'settings');direct.disabled=calibrationPreparing||['preparing','printing','paused','submitted'].includes(state.phase);actions.append(direct);
    const preview=button('Open 3D model','outline',async()=>{const value=await action(()=>api('/api/calibration/catalog/'+spec.id+'/model',{}));if(value){await refresh();selectFile(value.id);}},'box');actions.append(preview);
  }
  if(run)actions.append(button('Photos & result','outline',()=>{calibrationEvidenceRun=run.id;calibrationView='Tests & photos';renderCalibrationDetail();},'upload'));
  c.append(actions,el('p','field-help',spec.mode==='native'?'The assistant plans this test. Generate its parameter sweep in native Orca or the official printer calibration menu.':'Preparation loads the model and compares settings. Printing uses a separate step with current material mapping and a clear build plate.'));
  if(run){
    const history=el('section','test-history');history.append(el('h3','','Trials in this session'));
    for(const trial of [...s.test_runs].reverse().filter(r=>r.test_id===spec.id)){
      const row=el('article','test-trial'),trialJobs=calibrationJobs(s,trial.id),status=calibrationPrintState(s,trialJobs),summary=calibrationTrialScore(s,trial,spec);
      row.append(el('strong','',new Date(trial.created_at).toLocaleString()),el('span','work-status',`${status.phase} · ${summary.passed}/${summary.total} goals confirmed · ${summary.percent}%`));
      for(const job of trialJobs.filter(j=>!j.comparison_parent)){
        const p=job.result?.plates?.[0],variant=el('div','test-variant');
        variant.append(el('p','field-help',`${job.variant_name||spec.name} · ${job.status}${p?' · '+(p.estimated_print_time||'')+' · '+(p.total_filament_grams??'—')+' g':''}${job.error?' · '+job.error:''}`));
        if(isJobReady(job))variant.append(button('Print variant','outline small',()=>printCalibrationBenchmark(s,trial.id,job.id),'print'));
        row.append(variant);
      }
      row.append(button('Review this trial','outline small',()=>{calibrationEvidenceRun=trial.id;calibrationView='Tests & photos';renderCalibrationDetail();}));history.append(row);
    }c.append(history);
  }
  const sources=el('div','guide-sources');sources.append(el('span','field-help','Protocol references:'));for(const source of spec.sources)sources.append(catalogLink(source));c.append(sources);
}
function calibrationTrialScore(s,run,spec){
  const latest={};for(const o of s.observations||[])if(o.test_run_id===run.id&&o.source==='user_report')Object.assign(latest,o.criteria);
  const passed=spec.criteria.filter(k=>latest[k]==='pass').length;return {passed,total:spec.criteria.length,percent:Math.round(100*passed/spec.criteria.length)};
}
function renderCalibrationEvidence(s,c){
  const runs=s.test_runs||[];if(calibrationEvidenceRun&&!runs.some(r=>r.id===calibrationEvidenceRun))calibrationEvidenceRun='';
  const select=el('select');options(select,[['','All session photos / earlier Benchy'],...runs.map((r,i)=>[r.id,`${catalogTest(r.test_id)?.name||r.test_id} · trial ${i+1} · ${new Date(r.created_at).toLocaleDateString()}`])]);select.value=calibrationEvidenceRun;select.onchange=()=>{calibrationEvidenceRun=select.value;renderCalibrationDetail();};c.append(field('Test being reviewed',select));
  const run=runs.find(r=>r.id===calibrationEvidenceRun),spec=catalogTest(run?.test_id||'benchy');
  c.append(el('h3','',run?spec.name:'Session evidence'),el('p','field-help',run?spec.readout:'Use sharp, well-lit views and identify the test. Record caliper measurements separately from photos.'));
  const upload=el('input');upload.type='file';upload.accept='image/png,image/jpeg,image/webp';upload.multiple=true;upload.setAttribute('aria-label','Upload photos of this calibration test');
  upload.onchange=async()=>{upload.disabled=true;try{for(const file of upload.files){const body=new FormData();body.append('photo',file);if(run)body.append('test_run_id',run.id);await api('/api/calibration/'+s.id+'/photos',body);}await loadCalibration();toast('Photos saved to this test.');}catch(e){toast(e.message,true);}finally{upload.disabled=false;}};c.append(upload);
  const selected=s.photos.filter(p=>!run||p.test_run_id===run.id),gallery=el('div','evidence-gallery');for(const p of selected){const img=el('img');img.src=`/api/calibration/${s.id}/photos/${p.id}`;img.alt='Calibration evidence for '+(spec?.name||'session');gallery.append(img);}c.append(gallery);
  const review=button('Evaluate these photos with AI','primary',async()=>{const result=await action(()=>api('/api/calibration/'+s.id+'/review',{test_run_id:run?.id}));if(result){openChat();scheduleRefresh();}},'chat');review.disabled=!selected.length;c.append(review,el('p','field-help','These photos are sent to your connected Codex account. Visual findings remain provisional until you confirm physical checks.'));
  if(!run){const manual=el('details','calibration-advanced');manual.append(el('summary','','Record an earlier physical observation'));const form=el('div');renderObservations(s,form);manual.append(form);c.append(manual);return;}
  const summary=calibrationTrialScore(s,run,spec);c.append(el('h3','',`${summary.passed} of ${summary.total} goals confirmed · ${summary.percent}%`),el('p','field-help','Percentage of this test’s confirmed checklist goals, not a measurement of overall print quality.'));
  const form=el('form','work-form test-result-form'),notes=el('textarea'),measurements=textInput(),physical=textInput('','checkbox');notes.required=true;notes.rows=3;notes.placeholder='Describe each result and the variant you printed.';measurements.placeholder='Example: 55° acceptable; 65° curling. Or nominal / measured / tolerance.';form.append(field('What happened?',notes),field('Measurements and selected values',measurements));
  const choices=[];for(const key of spec.criteria){const criterion=calibrationState.criteria.find(x=>x.id===key),input=el('select');options(input,[['','No update'],['pass','Passed'],['fail','Needs work'],['pending','Pending']]);form.append(field(criterion?.name||key,input));choices.push([key,input]);}
  form.append(field('I physically checked these results',physical));const submit=el('button','button primary','Save this trial’s result');submit.type='submit';form.append(submit);
  form.onsubmit=async e=>{e.preventDefault();const saved=await action(()=>api('/api/calibration/'+s.id+'/observations',{stage:spec.stage,test_run_id:run.id,notes:notes.value,measurements:measurements.value.trim()?{reported:measurements.value.trim()}:{},physically_observed:physical.checked,criteria:Object.fromEntries(choices.filter(([,v])=>v.value).map(([k,v])=>[k,v.value]))}),'Trial result saved',submit);if(saved)await loadCalibration();};c.append(form);
  for(const o of s.observations.filter(o=>o.test_run_id===run.id).slice().reverse()){const row=el('article','observation');row.append(el('strong','',o.source==='user_report'?'Your physical observation':'Provisional analysis'),el('p','',o.notes),el('small','',Object.values(o.measurements).join(' · ')));c.append(row);}
  c.append(button('Refine this test with AI','outline',()=>startCalibrationAI(s,spec.id),'chat'));
}
