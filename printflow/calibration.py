"""Evidence-based calibration records. No route starts or modifies a printer."""
import asyncio
import copy
import io
import math
import hashlib
import shutil
import uuid
from pathlib import Path
from PIL import Image
import httpx
from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, Response
from .common import DATA, ROOT, now, read_json, save_json, bridge_token
from .calibration_catalog import catalog, get_test, recipe, validate_emitted_test, VERSION

router = APIRouter()
store = DATA / 'calibration.json'
records = read_json(store, {'sessions': [], 'profiles': []})
asset_lock=asyncio.Lock()
preparation_locks={}
GUIDE = {
    'reviewed_at': '2026-10-24',
    'summary': 'Tune one variable at a time, then verify the complete profile on the same benchmark. Photos support visual diagnosis; they do not measure flow, strength or dimensions.',
    'steps': [
        {'id':'baseline','name':'Official printer calibration','instruction':'Check the plate, dry filament and run the manufacturer calibration when indicated. On U1, use official Dynamic Flow Calibration for the loaded filament. Unloading resets its K value. Do not replace firmware.'},
        {'id':'temperature','name':'Temperature','instruction':'Use the native Orca temperature calibration within the filament maker’s range. Inspect bonding, bridges and stringing; record the selected temperature. A plain tower mesh does not change temperature.'},
        {'id':'volumetric','name':'Volumetric flow limit','instruction':'Use the native maximum volumetric speed test. Record the first visible failure and choose a conservative limit below it; the Orca guide suggests a 10–20% margin.'},
        {'id':'pressure','name':'Pressure advance','instruction':'Use the supported native calibration. For U1, prefer official Dynamic Flow Calibration. Keep manual K as an observation; PrintFlow does not override the firmware calibration.'},
        {'id':'flow','name':'Flow ratio','instruction':'Use Orca’s flow test and record the selected patch and resulting ratio. Recheck pressure advance after a substantial flow change.'},
        {'id':'retraction','name':'Retraction','instruction':'Test stringing after temperature, pressure and flow. Keep native defaults unless the test shows a benefit. Record results; automatic retraction override is not enabled.'},
        {'id':'fit','name':'Fit and support removal','instruction':'Measure a fit coupon with calipers and physically remove a support sample. Record clearance and removal effort. Do not infer removability from a photo alone.'},
        {'id':'benchmark','name':'Benchmark and verify','instruction':'Print the unchanged 3DBenchy without supports for comparison, then upload front, side, rear and underside photos. Use a separate supported sample to judge support removal. Keep the original scale and record the complete settings.'}
    ],
    'sources': [
        {'title':'Snapmaker U1 FAQ', 'url':'https://wiki.snapmaker.com/en/FAQ/u1'},
        {'title':'OrcaSlicer calibration guide', 'url':'https://github.com/OrcaSlicer/OrcaSlicer/wiki/calibration_guide'},
        {'title':'OrcaSlicer flow ratio', 'url':'https://github.com/OrcaSlicer/OrcaSlicer/wiki/flow_ratio_calib'},
        {'title':'3DBenchy original model', 'url':'https://www.3dbenchy.com/download/'},
        {'title':'3DBenchy inspection features', 'url':'https://www.3dbenchy.com/features/'},
        {'title':'3DBenchy license', 'url':'https://www.3dbenchy.com/license/'}
    ],
    'limits': 'Native calibration menus depend on the installed Snapmaker Orca version. PrintFlow can prepare benchmarks and apply saved process/temperature/flow limits; special calibration sweeps and official firmware calibration remain native operations.'
}
PROCESS = {'layer_height':(.08,.24),'initial_layer_print_height':(.16,.24),'initial_layer_speed':(10,80),'initial_layer_infill_speed':(10,80),'bridge_speed':(10,100),'outer_wall_speed':(10,200),'top_surface_speed':(10,150),'wall_loops':(1,12),'sparse_infill_density':(0,100),'support_top_z_distance':(0,.6),'support_bottom_z_distance':(0,.6),'support_object_xy_distance':(.1,1),'support_interface_top_layers':(0,8),'support_interface_spacing':(0,1)}
FILAMENT = {'filament_flow_ratio':(.8,1.2),'filament_max_volumetric_speed':(1,35),'nozzle_temperature':(170,300),'nozzle_temperature_initial_layer':(170,300)}
CRITERIA = [
    {'id':'surface','name':'Surface finish','description':'Inspect the hull and top surfaces for gaps, ringing and uneven extrusion.'},
    {'id':'stringing','name':'Clean details','description':'Inspect windows and the chimney for unwanted strings or blobs.'},
    {'id':'bridges','name':'Bridges & overhangs','description':'Inspect the cabin roof and openings for sagging or collapsed lines.'},
    {'id':'first_layer','name':'First layer','description':'Check the underside and bed contact for gaps, lifting and excessive squashing.'},
    {'id':'dimensions','name':'Dimensional fit','description':'Use calipers and record the agreed nominal size, measured size and tolerance.'},
    {'id':'supports','name':'Support removal','description':'Print a separate supported sample and report removal effort and the underside finish. Benchy has no supports.'},
]

def result_summary(s):
    """Checklist attainment, never a fabricated percentage of physical print quality."""
    results=[]
    for criterion in CRITERIA:
        observations=[o for o in s.get('observations',[]) if criterion['id'] in o.get('criteria',{})]
        confirmed=[o for o in observations if o.get('source')=='user_report']
        latest=confirmed[-1] if confirmed else None
        results.append(criterion|{'status':latest['criteria'][criterion['id']] if latest else 'pending',
            'evidence_id':latest['id'] if latest else None,'notes':latest.get('notes','') if latest else '',
            'provisional':observations[-1]['criteria'][criterion['id']] if observations and observations[-1].get('source')!='user_report' else None})
    passed=sum(c['status']=='pass' for c in results);assessed=sum(c['status']!='pending' for c in results)
    return {'criteria':results,'passed':passed,'assessed':assessed,'total':len(results),
        'goals_met_percent':round(100*passed/len(results)), 'coverage_percent':round(100*assessed/len(results)),
        'pass_rate_percent':round(100*passed/assessed) if assessed else None,
        'meaning':'Goals met = user-confirmed passed criteria / all six goals. Coverage = assessed criteria / all goals. Pending checks are unmeasured, not failed. This is not a quality certification.'}
def portal():
    from . import api
    return api
def persist(): save_json(store, records)
def session(identifier):
    value=next((r for r in records['sessions'] if r['id']==identifier),None)
    if not value: raise ValueError('Calibration session not found')
    return value
def bounded(values, limits):
    if not isinstance(values,dict) or set(values)-set(limits):raise ValueError('Unsupported calibration setting')
    result={}
    for key,value in values.items():
        if isinstance(value,bool):raise ValueError('Use numeric calibration values')
        value=float(value); low,high=limits[key]
        if not math.isfinite(value) or not low<=value<=high:raise ValueError(f'{key} must be between {low} and {high}')
        if key in {'wall_loops','support_interface_top_layers'} and not value.is_integer():raise ValueError(f'{key} must be an integer')
        result[key]=value
    return result
def profile(identifier):
    value=next((r for r in records['profiles'] if r['id']==identifier),None)
    if not value:raise ValueError('Saved profile not found')
    return value

def validate_profile_use(saved,body,item):
    if saved['status']=='user_verified':return
    sid=body.get('calibration_session_id')
    s=session(sid) if sid else None
    # Experimental values may only be tested on the original benchmark, in their
    # own session or a refinement with the same printer/material context.
    test_id=body.get('calibration_test_id','benchy')
    expected='calibration-assets/3DBenchy.stl' if test_id=='benchy' else f'calibration-assets/v{VERSION}/{get_test(test_id)["id"]}.stl'
    if (not s or item.get('path')!=expected
        or s['context']!=saved['context']
        or (saved.get('session_id')!=sid and s.get('parent_profile_id')!=saved['id'])):
        raise ValueError('Verify the profile with a physical benchmark before using it for model preparation')
def match_profile(p,printer,filament,tool):
    loaded=next((f for f in printer.get('filaments',[]) if int(f.get('slot',0))-1==tool),{})
    c=p['context']
    return (printer.get('connected') and c['printer_id']==printer.get('id') and c['tool_index']==tool
        and c['filament_profile']==filament and loaded.get('loaded')
        and (not c.get('firmware') or c['firmware']==printer.get('firmware_version'))
        and all(str(c.get(k,'')).casefold()==str(loaded.get(k,'')).casefold() for k in ('material','brand','color','nozzle_diameter'))
        and (not c.get('series') or c['series']==loaded.get('series')))

@router.get('/api/calibration')
async def overview():return records|{'sessions':[s|{'results':result_summary(s)} for s in records['sessions']],'guide':GUIDE,'criteria':CRITERIA,'catalog':catalog()}

@router.get('/api/calibration/catalog')
async def test_catalog():return catalog()

async def ensure_test_asset(test_id):
    t=get_test(test_id)
    if t['mode']=='native':raise ValueError('This test uses a native calibration generator. Follow its guide.')
    path=ROOT/'models'/'calibration-assets'/('3DBenchy.stl' if test_id=='benchy' else f'v{VERSION}/{test_id}.stl')
    if path.is_file():return path
    if test_id=='benchy':raise ValueError('The original 3DBenchy asset is missing; restore the bundled calibration asset')
    async with asset_lock:
        if path.is_file():return path
        from .designs import CAD_URL
        from . import previews
        try:
            async with httpx.AsyncClient(timeout=90,trust_env=False) as client:
                r=await client.post(CAD_URL+'/calibration/'+test_id,headers={'X-PrintFlow-Token':bridge_token()})
                r.raise_for_status()
        except httpx.HTTPError as exc:raise ValueError('The CAD service could not create this test. Check the CAD service and try again.') from exc
        if len(r.content)>5*1024**2:raise ValueError('The calibration model exceeds the expected size')
        path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.pending.stl');temp.write_bytes(r.content)
        try:
            value=await asyncio.to_thread(previews.preview,temp)
            if not value.get('triangle_count'):raise ValueError('The generated test has no mesh')
            temp.replace(path)
        finally:temp.unlink(missing_ok=True)
    return path

@router.get('/api/calibration/catalog/{test_id}/thumbnail')
async def test_thumbnail(test_id:str):
    from . import previews
    path=await ensure_test_asset(test_id)
    value=await asyncio.to_thread(previews.preview,path)
    data,kind=await asyncio.to_thread(previews.thumbnail,path,value)
    return Response(data,media_type=kind,headers={'Cache-Control':'private, max-age=86400'})

async def load_test_model(test_id):
    t=get_test(test_id);src=await ensure_test_asset(test_id);module=portal();relative=src.relative_to(ROOT/'models').as_posix()
    existing=next((f for f in module.files if f.get('path')==relative),None)
    if not existing:
        existing={'id':uuid.uuid4().hex[:16],'name':t['name']+'.stl','folder':'Calibration','extension':'.stl','path':relative,
                  'size':src.stat().st_size,'created_at':now(),'calibration_test_id':test_id,'sha256':hashlib.sha256(src.read_bytes()).hexdigest()}
        module.files.append(existing)
        if 'Calibration' not in module.folders:module.folders.append('Calibration');save_json(DATA/'folders.json',module.folders)
        save_json(module.store_path,module.files);module.events.emit('library',{'file_id':existing['id']})
    return existing

@router.post('/api/calibration/catalog/{test_id}/model')
async def load_catalog_model(test_id:str):return await load_test_model(test_id)

@router.post('/api/calibration/{sid}/tests/{test_id}/prepare')
async def prepare_test(sid:str,test_id:str,request:Request):
    s=session(sid);t=get_test(test_id);plan=recipe(test_id);b=await request.json();module=portal()
    lock=preparation_locks.setdefault(sid,asyncio.Lock())
    async with lock:
        pid=s['context']['printer_id']
        if pid not in module.printers:raise ValueError('Select an available calibration printer')
        printer=await module.printers[pid].status()
        if not printer.get('connected'):raise ValueError('Connect the printer to verify its loaded material')
        validate_print_context(s,printer,[0],{0:s['context']['tool_index']})
        profile_id=b.get('profile_id') or s.get('parent_profile_id')
        if profile_id:
            p=profile(profile_id)
            if p['context']!=s['context']:raise ValueError('The profile does not match this calibration session')
        trials=s.setdefault('test_runs',[])
        if test_id=='benchy' and not trials and not profile_id and not b.get('repeat'):
            legacy=next((j for j in reversed(module.jobs) if j['id'] in s['jobs'] and j.get('status') in {'ready','queued','running'} and j.get('comparison_parent')),None)
            if legacy:
                trials.append({'id':uuid.uuid4().hex[:12],'test_id':'benchy','test_version':VERSION,'file_id':legacy['file_id'],
                               'jobs':[legacy['id']],'profile_id':None,'recipe':plan,'created_at':legacy.get('created_at',now())})
        for trial in reversed(trials):
            if trial['test_id']!=test_id or trial.get('profile_id')!=profile_id:continue
            linked=[j for j in module.jobs if j['id'] in trial['jobs']]
            if any(j['status'] in {'queued','running'} for j in linked) or (b.get('repeat') is not True and trial.get('recipe')==plan and any(j['status']=='ready' for j in linked)):
                s['active_test_run_id']=trial['id'];persist();return {'run':trial,'job':linked[-1],'reused':True}
        item=await load_test_model(test_id)
        body={'file_id':item['id'],'filament':s['context']['filament_profile'],'supports':plan['supports'],
              'layer_height':plan['layer_height'],'visible':False,'mode':'compare','variants':plan['variants'],
              'calibration_session_id':sid,'calibration_test_id':test_id,'printer_id':pid,'tool_index':s['context']['tool_index']}
        if profile_id:body['profile_id']=profile_id
        class Body:
            async def json(self):return body
        job=await module.prepare_job(Body())
        trial={'id':uuid.uuid4().hex[:12],'test_id':test_id,'test_version':VERSION,'file_id':item['id'],'jobs':[job['id']],
               'profile_id':profile_id,'recipe':plan,'created_at':now()}
        trials.append(trial);s['active_test_run_id']=trial['id'];s['jobs'].append(job['id']);persist()
        return {'run':trial,'job':job,'reused':False}

@router.post('/api/calibration/assistant')
async def assistant(request:Request):
    b=await request.json();module=portal();pid=b.get('printer_id');sid=b.get('session_id');s=session(sid) if sid else None
    if s:pid=s['context']['printer_id']
    if pid not in module.printers:raise ValueError('Select a connected printer to calibrate')
    c=module.host_status.get('codex',{})
    if c.get('busy'):raise ValueError('Codex is already working. Follow its progress in the chat.')
    if not c.get('connected') or not c.get('authenticated'):raise ValueError('Connect your Codex account to start guided calibration')
    printer=await module.printers[pid].status()
    if not printer.get('connected'):raise ValueError('The printer must be online to read its loaded materials')
    chosen=get_test(b['test_id']) if b.get('test_id') else None
    active=next((r for r in s.get('test_runs',[]) if r['id']==s.get('active_test_run_id')),None) if s else None
    if not chosen and active:chosen=get_test(active['test_id'])
    trial=next((r for r in reversed(s.get('test_runs',[])) if r['test_id']==chosen['id']),None) if s and chosen else None
    linked=set(trial['jobs'] if trial else s['jobs'] if s and not chosen else [])
    prepared=[{'job_id':j['id'],'file_id':j.get('file_id'),'status':j['status'],'variant':j.get('variant_name'),
               'plates':(j.get('result') or {}).get('plates',[]),
               'project_link':f"/api/jobs/{j['id']}/download?kind=project"}
              for j in getattr(module,'jobs',[]) if not j.get('comparison_parent') and
              (j['id'] in linked or j.get('comparison_id') in linked) and j['status'] in {'ready','queued','running'}]
    context={'workflow':'guided_calibration','printer':printer,'calibration':s,'guide':GUIDE,'criteria':CRITERIA,'test_catalog':catalog(),'selected_test':chosen,
             'available_preparations':prepared,'results':result_summary(s) if s else None,'profiles':records['profiles'],'requested_action':b.get('action','continue')}
    message=(f"{'Continue' if s else 'Start'} guided calibration for {printer.get('name',pid)}. "
        "Take care of model loading and preparation through the connected tools. Read u1_preferences, calibration_guide, "
        "calibration_history and the live loaded materials. Reuse the selected session when provided; otherwise choose an unambiguous "
        "loaded hotend and matching installed filament profile, then create a session. If the exact brand or series cannot be determined, "
        "ask only for that missing fact. Read calibration_test_catalog. If selected_test is present, prioritize THAT test: use prepare_calibration_test for a coupon, or explain the native generator for a native-only test. Do not replace a requested overhang or bridge test with Benchy. Otherwise load the original 3DBenchy via prepare_calibration_benchmark at original scale without supports; "
        "reuse an existing queued or ready comparison for this session instead of duplicating it. Inspect emitted G-code and compare time "
        "and grams, then recommend a baseline for best finish. Keep native U1 priming. Display the benchmark and leave the prepared job "
        "ready for the print setup. Starting a print requires the owner's current clear-bed confirmation and material mapping; this request "
        "does not confirm those facts. Never interrupt a print. When completed, request front, side, rear and underside photos plus measured "
        "results. Record photo findings as provisional, and only mark criteria passed after actual user confirmation. Percentages describe "
        "checklist attainment, never guaranteed quality. Benchy cannot validate support removal; plan a separate supported sample. "
        "Record results through record_calibration_observation with criteria keys surface, stringing, bridges, first_layer, dimensions and supports, "
        "using pass, fail or pending. Physically observed is true only for explicit human reports. Propose one variable to change at a time. "
        "Save tested settings as an immutable profile revision and preserve previous versions. "
        "Use refine_calibrated_profile to continue an existing profile. Stay with official firmware; explain native-only calibration steps. "
        "If available_preparations already contains this test, review those jobs without calling preparation again. "
        "Link the chosen job using its project_link so the interface can open the model and print setup. "
        "If a tool is denied, report that action as blocked and do not retry through a different tool or command. "
        "Distinguish an already prepared job from actions completed during this request. "
        "Show concise English progress and the next action in the web chat.")
    return (await module.host('POST','/chat',json={'message':message,'context':context},timeout=65)).json()

@router.post('/api/calibration')
async def create(request:Request):
    b=await request.json();module=portal();pid=b.get('printer_id');tool=int(b.get('tool_index',0))
    if pid not in module.printers or tool not in range(4):raise ValueError('Select a connected printer and hotend')
    printer=await module.printers[pid].status();loaded=next((f for f in printer.get('filaments',[]) if f.get('slot')==tool+1),{})
    if not printer.get('connected') or not loaded.get('loaded'):raise ValueError('Read the loaded filament before calibrating')
    filament=str(b.get('filament_profile','')).strip()
    available=await module.profiles()
    if filament not in {p['name'] for p in available}:raise ValueError('Select an installed native filament profile')
    settings=await module.native('u1_get_profile',{'name':filament,'kind':'filament'})
    material=settings.get('filament_type',[''])[0]
    if str(material).casefold()!=str(loaded.get('material','')).casefold():raise ValueError('The native profile material does not match the loaded spool')
    parent=profile(b['parent_profile_id']) if b.get('parent_profile_id') else None
    if parent and not match_profile(parent,printer,filament,tool):raise ValueError('The profile does not match this printer, hotend and loaded filament')
    # A session describes one physical tool and one real filament; it is not a global printer optimum.
    value={'id':uuid.uuid4().hex[:16],'name':str(b.get('name','Material calibration'))[:100], 'created_at':now(),'status':'in_progress',
           'context':{'printer_id':pid,'printer_name':printer.get('name'),'tool_index':tool,'filament_profile':filament,
                      **{k:loaded.get(k) for k in ('material','brand','series','color','nozzle_diameter')},'firmware':printer.get('firmware_version')},
           'observations':[],'photos':[],'jobs':[], 'parent_profile_id':parent['id'] if parent else None}
    records['sessions'].append(value);persist();return value

@router.post('/api/calibration/profiles/{profile_id}/refine')
async def refine(profile_id:str):
    p=profile(profile_id)
    # Resume an unfinished refinement, rather than duplicating it on repeated clicks.
    existing=next((s for s in reversed(records['sessions']) if s.get('parent_profile_id')==profile_id
                   and not any(v.get('session_id')==s['id'] for v in records['profiles'])),None)
    if existing:return existing
    class Body:
        async def json(self):return {'name':p['name']+' · refinement','printer_id':p['context']['printer_id'],
            'tool_index':p['context']['tool_index'],'filament_profile':p['context']['filament_profile'],'parent_profile_id':profile_id}
    return await create(Body())

@router.post('/api/calibration/{sid}/benchmark')
async def benchmark(sid:str,request:Request):
    return (await prepare_test(sid,'benchy',request))['job']


def validate_print_context(s,printer,tools,mapping):
    c=s['context'];tool=c['tool_index']
    loaded=next((f for f in printer.get('filaments',[]) if f.get('slot')==tool+1),{})
    if printer.get('id')!=c['printer_id'] or not loaded.get('loaded') or len(tools)!=1 or mapping.get(tools[0])!=tool:
        raise ValueError('This calibration must use its selected printer and physical hotend. Create a new session for a different setup.')
    for key in ('material','brand','series','color','nozzle_diameter'):
        if c.get(key) is not None and str(c[key]).casefold()!=str(loaded.get(key,'')).casefold():
            raise ValueError('The loaded filament or nozzle changed since calibration preparation. Start a new session for the current material.')


@router.get('/api/calibration/{sid}/print-setup')
async def print_setup(sid:str,test_run_id:str|None=None):
    s=session(sid);module=portal();pid=s['context']['printer_id']
    if pid not in module.printers:raise ValueError('The calibration printer is unavailable')
    printer=await module.printers[pid].status()
    if not printer.get('connected'):raise ValueError('Connect the calibration printer before printing')
    if printer.get('state') not in {'standby','ready','idle','complete','completed'}:raise ValueError('The printer is not ready for a new calibration print')
    trial=next((r for r in s.get('test_runs',[]) if r['id']==test_run_id),None) if test_run_id else None
    if test_run_id and not trial:raise ValueError('Calibration test run not found')
    job_ids=trial['jobs'] if trial else s['jobs'];choices=[]
    for job in module.jobs:
        if job.get('comparison_parent') or (job['id'] not in job_ids and job.get('comparison_id') not in job_ids):continue
        if job.get('status')!='ready':continue
        plates=job.get('result',{}).get('plates',[])
        if len(plates)!=1:continue
        if trial:
            try:validate_emitted_test(trial['test_id'],job['result'])
            except ValueError:continue
        tools=plates[0].get('tools_zero_based',[])
        mapping={t:s['context']['tool_index'] for t in tools}
        validate_print_context(s,printer,tools,mapping)
        choices.append({'job_id':job['id'],'name':job.get('variant_name','Prepared benchmark'),
                        'time':plates[0].get('estimated_print_time'),'grams':plates[0].get('total_filament_grams'),
                        'mapping':{str(k):v for k,v in mapping.items()}})
    if not choices:raise ValueError('No ready variant is available. Prepare this test first.')
    recommended=next((x for x in choices if '0.12' in x['name']),choices[0])
    return {'session_id':sid,'printer_id':pid,'recommended_job_id':recommended['job_id'],'choices':choices,
            'reason':'Compare the prepared variants using this test protocol. A prepared baseline is not a physically verified optimum.',
            'context':s['context'],'bed_clear_confirmation_required':True}

@router.post('/api/calibration/{sid}/observations')
async def observation(sid:str,request:Request):
    s=session(sid);b=await request.json();stage=b.get('stage')
    if stage not in {x['id'] for x in GUIDE['steps']}:raise ValueError('Choose a calibration stage')
    note=str(b.get('notes','')).strip()
    if not note or len(note)>5000:raise ValueError('Describe the observed result (up to 5,000 characters)')
    values=b.get('measurements',{})
    if not isinstance(values,dict) or len(values)>20:raise ValueError('Use up to 20 measurements')
    for key,value in values.items():
        if len(str(key))>80 or not isinstance(value,(str,int,float)) or len(str(value))>200:raise ValueError('Invalid measurement')
    criteria=b.get('criteria',{})
    if not isinstance(criteria,dict) or set(criteria)-{c['id'] for c in CRITERIA} or any(v not in ('pass','fail','pending') for v in criteria.values()):raise ValueError('Choose valid result criteria and pass, fail or pending states')
    if criteria.get('dimensions') in ('pass','fail') and not values:raise ValueError('Record nominal size, measured size and tolerance before assessing dimensional fit')
    run_id=b.get('test_run_id');trial=next((r for r in s.get('test_runs',[]) if r['id']==run_id),None)
    if run_id and not trial:raise ValueError('Calibration test run not found')
    if trial:
        spec=get_test(trial['test_id'])
        if set(criteria)-set(spec['criteria']):raise ValueError('Only assess the goals covered by this test')
        stage=spec['stage']
    row={'id':uuid.uuid4().hex[:12],'stage':stage,'notes':note,'measurements':values,'criteria':criteria,'at':now(),'source':'user_report' if b.get('physically_observed') is True else 'provisional_analysis','test_run_id':run_id,'test_id':trial['test_id'] if trial else None}
    s['observations'].append(row);persist();return row

@router.post('/api/calibration/{sid}/photos')
async def photos(sid:str,photo:UploadFile=File(),test_run_id:str|None=Form(None)):
    s=session(sid)
    if not isinstance(test_run_id,str):test_run_id=None
    if test_run_id and not any(r['id']==test_run_id for r in s.get('test_runs',[])):raise ValueError('Calibration test run not found')
    if len(s['photos'])>=20:raise ValueError('A session supports up to 20 photos')
    raw=await photo.read(12*1024*1024+1)
    if len(raw)>12*1024*1024:raise ValueError('Use an image smaller than 12 MB')
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in {'PNG','JPEG','WEBP'} or im.width*im.height>24_000_000:raise ValueError('Use a JPEG, PNG or WebP up to 24 megapixels')
            im.load();im=im.convert('RGB');im.thumbnail((2400,2400));out=io.BytesIO();im.save(out,format='JPEG',quality=90)
    except (OSError,Image.DecompressionBombError) as exc:raise ValueError('Invalid photo') from exc
    key=uuid.uuid4().hex[:16];dest=ROOT/'models'/'calibration'/sid/(key+'.jpg');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(out.getvalue())
    row={'id':key,'path':dest.relative_to(ROOT/'models').as_posix(),'at':now(),'test_run_id':test_run_id};s['photos'].append(row);s['status']='reviewing_results';persist();return row

@router.get('/api/calibration/{sid}/photos/{photo_id}')
async def get_photo(sid:str,photo_id:str):
    p=next((p for p in session(sid)['photos'] if p['id']==photo_id),None)
    if not p:raise ValueError('Photo not found')
    return FileResponse(ROOT/'models'/p['path'])

@router.post('/api/calibration/{sid}/review')
async def review(sid:str,request:Request):
    s=session(sid)
    b=await request.json();run_id=b.get('test_run_id');trial=next((r for r in s.get('test_runs',[]) if r['id']==run_id),None)
    if run_id and not trial:raise ValueError('Calibration test run not found')
    selected=[p for p in s['photos'] if not run_id or p.get('test_run_id')==run_id]
    if not selected:raise ValueError('Upload photos of the selected finished test first')
    if portal().host_status.get('codex',{}).get('busy'):raise ValueError('Wait for the current Codex request to finish')
    context={'calibration':s,'guide':GUIDE,'criteria':CRITERIA,'results':result_summary(s),'test_run':trial,'test':get_test(trial['test_id']) if trial else None}
    return (await portal().host('POST','/chat',json={'message':'Review these calibration photos against the selected test protocol. Identify visible defects with uncertainty. Read the calibration session and guide. Suggest one next test, not a guaranteed optimum. Link observations to test_run_id when provided. Do not infer dimensions, strength, support removal or final flow values from photos; use my measurements. Do not start printing or mark profiles verified.','context':context,'image_paths':[p['path'] for p in selected[-6:]]},timeout=65)).json()

@router.post('/api/calibration/{sid}/profiles')
async def save_profile(sid:str,request:Request):
    s=session(sid);b=await request.json();name=str(b.get('name','')).strip()
    if not name or len(name)>100:raise ValueError('Name the reusable profile')
    process=bounded(b.get('process',{}),PROCESS);filament=bounded(b.get('filament',{}),FILAMENT)
    if not process and not filament:raise ValueError('Enter the settings you tested')
    verified=b.get('physically_verified') is True
    if verified and not any(x['source']=='user_report' and x['stage']=='benchmark' for x in s['observations']):raise ValueError('Record your physical benchmark result before verifying a profile')
    purpose=b.get('purpose','display')
    if purpose not in {'display','functional','supports','general'}:raise ValueError('Choose a supported purpose')
    parent=profile(s['parent_profile_id']) if s.get('parent_profile_id') else None
    if parent:
        process=copy.deepcopy(parent['process'])|process;filament=copy.deepcopy(parent['filament'])|filament
    identifier=uuid.uuid4().hex[:16];family=parent.get('family_id',parent['id']) if parent else identifier
    revision=max((p.get('revision',1) for p in records['profiles'] if p.get('family_id',p['id'])==family),default=0)+1
    value={'id':identifier,'name':name,'context':dict(s['context']),'session_id':sid,'process':process,'filament':filament,'purpose':purpose,'status':'user_verified' if verified else 'experimental','created_at':now(),'evidence_ids':[x['id'] for x in s['observations']], 'photo_ids':[p['id'] for p in s['photos']],
        'family_id':family,'revision':revision,'parent_profile_id':parent['id'] if parent else None,'results':result_summary(s)}
    records['profiles'].append(value);persist();return value

@router.get('/api/calibration/recommend/{file_id}')
async def recommend(file_id:str,printer_id:str,filament:str,tool_index:int=0,purpose:str='display'):
    module=portal();module.find_file(file_id)
    if printer_id not in module.printers:raise ValueError('Select a connected printer')
    printer=await module.printers[printer_id].status();meta=await module.model_scene(file_id)
    if (meta.get('color_count') or 1)>1:return {'profiles':[],'model':{'dimensions':meta.get('dimensions')},'note':'Measured filament profiles apply to single-slot projects. Preserve native per-slot settings in this multicolor assembly and calibrate each material separately.'}
    matches=[p for p in records['profiles'] if p['status']=='user_verified' and match_profile(p,printer,filament,tool_index)]
    matches.sort(key=lambda p:(p['purpose']==purpose,p['created_at']),reverse=True)
    return {'profiles':matches,'model':{k:meta.get(k) for k in ('dimensions','color_count','object_count')},'note':'Ranked by matching printer, hotend, reported material/brand/color, native filament profile and purpose. Geometry and support orientation still need review. Multicolor overrides require a separate profile for each material.'}

def observe(printer):
    changed=False
    for s in records['sessions']:
        for jid in s['jobs']:
            parent=next((j for j in portal().jobs if j['id']==jid),{})
            for job in [parent,*[j for j in portal().jobs if j.get('comparison_id')==jid]]:
                if printer.get('id')!=s['context']['printer_id'] or job.get('printer_id')!=printer.get('id'):continue
                expected=f'PrintFlow_{job.get("id")}.gcode'
                if printer.get('filename')==expected and printer.get('state') in {'complete','completed'} and job['id'] not in s.get('completed_jobs',[]):
                    s.setdefault('completed_jobs',[]).append(job['id']);s['status']='awaiting_photos';changed=True
                    portal().events.emit('calibration_ready',{'session_id':s['id'],'message':'Calibration print complete. Upload photos and measurements for review.'})
    if changed:persist()
