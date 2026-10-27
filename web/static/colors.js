'use strict';
let colorEditor={fileId:null,slots:[],loading:false};
async function loadModelColors(force=false){
  const file=selectedFile();if(!file||(!force&&colorEditor.fileId===file.id))return;
  colorEditor={fileId:file.id,slots:[],loading:true};$('model-color-slots').replaceChildren();$('save-model-colors').disabled=true;
  try{const r=await fetch('/api/files/'+encodeURIComponent(file.id)+'/colors');const data=await r.json();if(!r.ok)throw Error(data.detail||'Could not load colors.');if(selectedFile()?.id!==file.id)return;
    colorEditor={fileId:file.id,slots:data.slots||[],loading:false,editable:data.editable};setText('model-colors-note',data.note);$('save-model-colors').disabled=!data.editable;
    for(const slot of colorEditor.slots){
      const card=el('div','color-slot-card'),heading=el('div','color-slot-heading');heading.append(el('strong','',slot.label),el('span','',`T${slot.slot}`));
      const row=el('div','color-picker-row'),picker=el('input');picker.type='color';picker.value=slot.color||'#B8C6DA';picker.dataset.colorSlot=slot.slot;picker.setAttribute('aria-label',slot.label+' color');const code=el('span','color-hex',slot.color||'Choose a color');
      picker.addEventListener('input',()=>{code.textContent=picker.value.toUpperCase();slot.color=picker.value;updateColorMatch(card,slot);});row.append(picker,code);
      const profile=el('select');profile.dataset.colorProfile=slot.slot;profile.setAttribute('aria-label',slot.label+' filament profile');profile.append(el('option','','Select the actual material'));profile.firstChild.value='';
      for(const entry of ui.profiles){const name=typeof entry==='string'?entry:entry.name;if(name){const option=el('option','',name);option.value=name;profile.append(option);}}
      profile.value=slot.profile;profile.addEventListener('change',()=>{slot.profile=profile.value;const entry=ui.profiles.find(x=>x.name===profile.value);slot.material=entry?.filament_type?.[0]||(/\b(PLA|PETG|ABS|ASA|TPU|PVA)\b/.exec(profile.value)?.[1]||'');updateColorMatch(card,slot);});
      const loaded=el('select');loaded.setAttribute('aria-label','Use a loaded spool color for '+slot.label);loaded.append(el('option','','Use a loaded spool color…'));loaded.firstChild.value='';
      for(const f of selectedPrinter()?.filaments||[]){const option=el('option','',`H${f.slot} · ${f.material} · ${f.color}`);option.value=String(f.slot);loaded.append(option);}
      loaded.addEventListener('change',()=>{const f=selectedPrinter()?.filaments?.find(x=>String(x.slot)===loaded.value);if(f){picker.value=f.color;slot.color=f.color;code.textContent=f.color;updateColorMatch(card,slot);}});
      const match=el('p','color-match');card.append(heading,row,profile,loaded,match);$('model-color-slots').append(card);updateColorMatch(card,slot);
    }
    syncColorSave();
  }catch(e){setText('model-colors-note',e.message);colorEditor.fileId=null;}
}
function syncColorSave(){ $('save-model-colors').disabled=!colorEditor.editable||!colorEditor.slots.length||colorEditor.slots.some(s=>!/^#[0-9a-fA-F]{6}$/.test(String(s.color))||!s.profile); }
function updateColorMatch(card,slot){syncColorSave();const matches=(selectedPrinter()?.filaments||[]).filter(f=>f.loaded&&String(f.color).toUpperCase()===String(slot.color||'').toUpperCase()&&(!slot.material||f.material===slot.material));const p=card.querySelector('.color-match');p.textContent=matches.length?'Loaded match: '+matches.map(f=>'H'+f.slot+' · '+f.material).join(', '):'Desired color is not reported as loaded';p.classList.toggle('matches',Boolean(matches.length));}
$('model-colors-tab').addEventListener('click',()=>setModelPanelTab('colors'));
$('save-model-colors').addEventListener('click',async()=>{const file=selectedFile();if(!file||file.id!==colorEditor.fileId)return;const result=await action(()=>api('/api/files/'+encodeURIComponent(file.id)+'/colors',{colors:colorEditor.slots.map(s=>s.color),profiles:colorEditor.slots.map(s=>s.profile)}),'New color revision saved. Prepare it again before printing.',$('save-model-colors'));if(result){selectFile(result.file.id);setModelPanelTab('colors');}});

function revealReadyModel(){const value=ui.state?.model_ready;if(!value||!ui.state.files.some(f=>f.id===value.file_id))return;let previous=ui.revealedModel;try{previous=previous||sessionStorage.getItem('printflow-model-ready');}catch{}if(previous===value.event_id)return;ui.revealedModel=value.event_id;try{sessionStorage.setItem('printflow-model-ready',value.event_id);}catch{}selectFile(value.file_id);toast('Your model is ready to review.');}

let materialCheckSequence=0;
async function validatePrintColors(){
  const pending=ui.pendingPrint;if(!pending)return;const seq=++materialCheckSequence;pending.materialCheck=null;
  $('start-mapped-print').disabled=true;$('print-substitution-label').hidden=true;$('print-accept-substitution').checked=false;setText('print-color-check','Checking loaded materials and colors…');
  const mapping={};$('print-mapping-tools').querySelectorAll('select[data-logical-tool]').forEach(s=>mapping[s.dataset.logicalTool]=Number(s.value));
  try{const result=await api('/api/jobs/'+pending.job.id+'/check-materials',{printer_id:pending.printerId,mapping});if(seq!==materialCheckSequence||ui.pendingPrint!==pending)return;pending.materialCheck=result;
    const container=$('print-color-check');container.replaceChildren();
    if(result.required_context){
      const context=el('div','print-context-note');context.append(el('strong','','Calibration setup'),el('p','',result.required_context.note));
      if(result.required_context.profile)context.append(el('small','',result.required_context.profile));
      const correct=Object.entries(result.required_mapping||{}).every(([logical,physical])=>mapping[logical]===physical);
      if(!correct)context.append(button('Use calibration hotend H'+(result.required_context.physical_tool+1),'outline small',()=>{
        $('print-mapping-tools').querySelectorAll('select[data-logical-tool]').forEach(s=>{const value=result.required_mapping?.[s.dataset.logicalTool];if(value!==undefined)s.value=String(value);});validatePrintColors();
      },'check'));
      container.append(context);
    }
    for(const row of result.rows){
      const item=el('div','print-material-card'),heading=el('div','print-material-heading');
      heading.append(el('strong','',`T${row.logical_tool} → Hotend ${row.physical_tool+1}`),el('span','state-tag'+(row.material_match?'':' error'),row.material_match?'Material matches':'Check material'));
      const detail=el('p','',`Prepared: ${row.expected.material||'Unknown material'} · Loaded: ${row.loaded.material||'Unknown material'}`);
      const palette=el('div','print-color-row'),wanted=el('span','model-color'),actual=el('span','model-color');
      wanted.style.backgroundColor=row.expected.color||'transparent';actual.style.backgroundColor=row.loaded.color||'transparent';
      palette.append(wanted,el('span','',row.expected.color||'Unassigned'),icon('arrow'),actual,el('span','',row.loaded.color||'Not reported'),el('span','color-match-label',row.color_match?'Color matches':row.expected.color?'Color differs':'Review loaded color'));
      item.append(heading,detail,palette);if(row.expected.color_source==='calibration_session')item.append(el('small','field-help','Target color recorded when this calibration session was created.'));container.append(item);
    }
    for(const error of result.errors)container.append(el('p','mapping-warning',error));
    for(const warning of result.warnings)container.append(el('p','print-color-warning',warning));
    container.append(el('p','field-help',result.note));
    $('print-substitution-label').hidden=!result.warnings.length;updatePrintStartState();
  }catch(e){if(seq!==materialCheckSequence||ui.pendingPrint!==pending)return;setText('print-color-check',e.message);pending.materialCheck=null;}
}
$('print-mapping-tools').addEventListener('change',validatePrintColors);
function updatePrintStartState(){const c=ui.pendingPrint?.materialCheck;$('start-mapped-print').disabled=!c||!c.materials_match||(!c.colors_match&&!$('print-accept-substitution').checked)||!$('print-bed-clear').checked;}
$('print-accept-substitution').addEventListener('change',updatePrintStartState);
$('print-bed-clear').addEventListener('change',updatePrintStartState);
