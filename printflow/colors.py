"""Saved color revisions and live tool checks shared by the GUI and MCP."""
import io
import asyncio
import json
import re
import uuid
import zipfile
from pathlib import Path
from fastapi import APIRouter, Request
from .common import ROOT, DATA, now, save_json
from . import previews

router=APIRouter()
def portal():
    from . import api
    return api

def project_palette(source):
    with previews.archive(source) if isinstance(source,Path) else zipfile.ZipFile(io.BytesIO(source)) as archive:
        cfg=json.loads(previews.part(archive,'Metadata/project_settings.config',5_000_000))
        if cfg.get('printer_model')!='Snapmaker U1': raise ValueError('Save a native U1 project before editing its print colors.')
        colors=cfg.get('filament_colour',[]); profiles=cfg.get('filament_settings_id',[]); materials=cfg.get('filament_type',[])
        names={}
        if 'Metadata/model_settings.config' in archive.namelist():
            root=previews.xml(previews.part(archive,'Metadata/model_settings.config',5_000_000))
            for part in root.findall('.//part'):
                meta={n.get('key'):n.get('value') for n in part.findall('metadata')}
                try: names.setdefault(int(meta.get('extruder','1'))-1,[]).append(meta.get('name','Color region'))
                except ValueError: pass
        # Orca can save a valid material/profile without a filament_colour array.
        # Slot identity must not disappear just because no display color was saved.
        count=max(len(colors),len(profiles),len(materials))
        return [{'slot':i,'color':previews.color(colors[i]) if i<len(colors) and colors[i] else None,'profile':profiles[i] if i<len(profiles) else '',
                 'material':materials[i] if i<len(materials) else '',
                 'label':', '.join(names.get(i,[])) or f'Color {i+1}'} for i in range(count)]

def assess(slots, printer, tools=None, mapping=None):
    tools=list(range(len(slots))) if tools is None else tools
    mapping={int(k):int(v) for k,v in (mapping or {i:i for i in tools}).items()}
    errors=[]; warnings=[]; rows=[]
    if not printer.get('connected'): errors.append('The printer is offline; loaded materials cannot be verified.')
    if set(mapping)!=set(tools): errors.append('Map every tool used by the G-code.')
    if len(set(mapping.values()))!=len(mapping): errors.append('Each color needs a different physical hotend.')
    loaded={int(f.get('slot',i+1))-1:f for i,f in enumerate(printer.get('filaments',[]))}
    for logical in tools:
        expected=slots[logical] if 0<=logical<len(slots) else {}
        physical=mapping.get(logical,-1); actual=loaded.get(physical,{})
        color=str(actual.get('color','')).upper(); color=color if color.startswith('#') else '#'+color
        material_match=bool(expected.get('material')) and expected['material'].upper()==str(actual.get('material','')).upper()
        color_match=bool(expected.get('color')) and expected['color'].upper()==color
        if physical not in range(4) or not actual.get('loaded'): errors.append(f'T{logical}: select a loaded U1 hotend.')
        elif not material_match: errors.append(f'H{physical+1}: expected {expected.get("material") or "a material identified in the prepared project"}, loaded {actual.get("material") or "unknown"}.')
        if actual.get('nozzle_diameter')!=.4: errors.append(f'H{physical+1}: a confirmed 0.4 mm nozzle is required.')
        if not color_match: warnings.append(f'T{logical}: desired {expected.get("color") or "unassigned color"}; H{physical+1} reports {color}.')
        rows.append({'logical_tool':logical,'physical_tool':physical,'expected':expected,'loaded':actual,'material_match':material_match,'color_match':color_match})
    return {'rows':rows,'errors':errors,'warnings':warnings,'materials_match':not errors,'colors_match':not warnings,
            'can_print':not errors and not warnings,'checked_at':now(),
            'note':'Colors are compared with printer-reported spool codes, not measured printed colors.'}

@router.get('/api/files/{file_id}/colors')
async def model_colors(file_id:str):
    item=portal().find_file(file_id); path=ROOT/'models'/item['path']
    if item['extension']=='.stl':
        return {'slots':[{'slot':0,'color':'#B8C6DA','profile':'','material':'','label':'Entire model'}], 'editable':True,'single_color':True,
                'note':'STL has one uncolored mesh. Save a single-color 3MF, or use an assembly with separate color regions.'}
    from .previews import preparation_metadata
    preview=await asyncio.to_thread(preparation_metadata,path)
    if not preview.get('preparation_supported'):return {'slots':[],'editable':False,'note':preview.get('preparation_note')}
    return {'slots':project_palette(path),'editable':True,'single_color':False,
            'note':'Edit the existing color slots. Save a new 3MF revision to preserve the original and its region assignments.'}

def publish_model(file_id):
    value={'file_id':file_id,'at':now(),'event_id':uuid.uuid4().hex}
    save_json(DATA/'model-ready.json',value);portal().events.emit('model_ready',value)
    return value

@router.post('/api/files/{file_id}/reveal')
async def reveal(file_id:str):
    portal().find_file(file_id);return publish_model(file_id)

@router.post('/api/files/{file_id}/colors')
async def save_colors(file_id:str,request:Request):
    module=portal(); item=module.find_file(file_id); body=await request.json()
    colors=body.get('colors'); profiles=body.get('profiles')
    original=await model_colors(file_id)
    if not original.get('editable'):raise ValueError(original['note'])
    if not isinstance(colors,list) or len(colors)!=len(original['slots']) or not 1<=len(colors)<=4:raise ValueError('Preserve the existing one to four color slots.')
    if any(not isinstance(c,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',c) for c in colors):raise ValueError('Choose a valid #RRGGBB color for every slot.')
    if not isinstance(profiles,list) or len(profiles)!=len(colors) or any(not isinstance(p,str) or not p.strip() for p in profiles):raise ValueError('Choose the actual filament profile for every slot.')
    project=item['path']
    if item['extension']=='.stl':project=(await module.native('u1_prepare_stl',{'model':project,'filament':profiles[0]}))['project']
    result=await module.native('u1_set_filament_slots',{'project':project,'filaments':profiles,'colors':colors})
    response=await module.host('GET','/artifact',params={'path':result['project']},timeout=60)
    identity=uuid.uuid4().hex[:16]; folder=ROOT/'models'/'revisions'/identity;folder.mkdir(parents=True)
    path=folder/'model.3mf';path.write_bytes(response.content)
    revision={'id':identity,'name':Path(item['name']).stem+' · color revision.3mf','folder':item.get('folder','Unsorted'),
              'path':path.relative_to(ROOT/'models').as_posix(),'extension':'.3mf','size':path.stat().st_size,
              'created_at':now(),'revision_of':file_id,'assembly':item.get('assembly',False)}
    revision['preview']=previews.metadata(await asyncio.to_thread(previews.preview,path))
    module.files.append(revision);save_json(module.store_path,module.files);publish_model(identity)
    return {'file':revision,'slots':project_palette(path)}

def calibration_session_for_job(job):
    from . import calibration
    return next((s for s in calibration.records['sessions']
                 if job['id'] in s['jobs'] or job.get('comparison_id') in s['jobs']),None)


async def job_slots(job):
    if job.get('material_plan'): return job['material_plan']
    path=(job.get('result') or {}).get('project')
    if not path: raise ValueError('Prepare this model before checking print colors.')
    r=await portal().host('GET','/artifact',params={'path':path},timeout=60)
    slots=project_palette(r.content)
    session=calibration_session_for_job(job)
    plates=(job.get('result') or {}).get('plates',[])
    tools=plates[0].get('tools_zero_based',[]) if len(plates)==1 else []
    if session and len(tools)==1:
        # A calibration session records its actual spool before preparation.
        # Use that recorded target only when Orca did not save a color; never
        # overwrite a configured project color or infer one from today's spool.
        logical=tools[0];color=session['context'].get('color')
        if 0<=logical<len(slots) and not slots[logical]['color'] and re.fullmatch(r'#[0-9a-fA-F]{6}',str(color)):
            slots[logical]['color']=color.upper()
            slots[logical]['color_source']='calibration_session'
    return slots

@router.post('/api/jobs/{job_id}/check-materials')
async def check_job_materials(job_id:str,request:Request):
    body=await request.json(); module=portal();job=module.find_job(job_id);pid=body.get('printer_id')
    if pid not in module.printers:raise ValueError('Select a connected printer.')
    printer=await module.printers[pid].status()
    plates=(job.get('result') or {}).get('plates',[])
    if len(plates)!=1:raise ValueError('Select a prepared single-plate job.')
    tools=plates[0].get('tools_zero_based',[])
    if not tools or any(type(t) is not int or t not in range(4) for t in tools):
        raise ValueError('No verified emitted tool list is available. Inspect the G-code before printing.')
    result=assess(await job_slots(job),printer,tools,body.get('mapping'))
    mapping={int(k):int(v) for k,v in (body.get('mapping') or {i:i for i in tools}).items()}
    from . import calibration
    session=calibration_session_for_job(job)
    context=session['context'] if session else calibration.profile(job['profile_id'])['context'] if job.get('profile_id') else None
    if context:
        physical=context['tool_index']
        result['required_mapping']={str(t):physical for t in tools}
        result['required_context']={
            'printer_id':context['printer_id'],'physical_tool':physical,
            'material':context.get('material'),'color':context.get('color'),
            'profile':context.get('filament_profile'),
            'note':f'This calibration uses H{physical+1} on {context.get("printer_name") or context["printer_id"]}. Keep the same hotend and spool for comparable results.'}
        try:
            if session:calibration.validate_print_context(session,printer,tools,mapping)
            elif len(tools)!=1 or mapping.get(tools[0])!=physical or not calibration.match_profile({'context':context},printer,context['filament_profile'],physical):
                raise ValueError('Use the printer, hotend and loaded filament recorded in this calibrated profile.')
        except ValueError as exc:
            result['errors'].append(str(exc))
            result['materials_match']=False;result['can_print']=False
    return result
