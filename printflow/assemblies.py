"""Portable part plans: one bed per part, explicit preparation and physical start."""
import asyncio
import base64
import io
import json
import math
import uuid
import zipfile
from pathlib import Path
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from .common import ROOT,DATA,now,save_json,read_json,bridge_token
from .designs import CAD_URL

router=APIRouter();store=DATA/'assemblies.json';data=read_json(store,{'printers':[],'plans':[]})
for plan in data['plans']:
    if plan['status'] in {'queued','running'}:plan.update(status='interrupted',error='Create a new plan after the service restart')
def portal():
    from . import api
    return api
def persist():save_json(store,data)
def fleet():
    native=[{'id':p['id'],'name':p['name'],'volume':[270,270,270],'color_system':'independent_tools','color_count':4,'delivery':'direct_u1','nozzle':.4} for p in portal().config if p['kind']=='snapmaker_u1']
    return native+data['printers']
def find(pid):
    p=next((p for p in data['plans'] if p['id']==pid),None)
    if not p:raise ValueError('Assembly plan not found')
    return p
def update(p,**values):p.update(values);persist();portal().events.emit('assembly',p)
def validate_target(body):
    name=str(body.get('name','')).strip();volume=body.get('volume',[])
    if not name or len(name)>80 or len(volume)!=3:raise ValueError('Enter a printer name and X/Y/Z build dimensions')
    volume=[float(n) for n in volume]
    if any(not math.isfinite(n) or not 40<=n<=2000 for n in volume):raise ValueError('Build dimensions must be 40–2,000 mm')
    mode=body.get('color_system','single');count=int(body.get('color_count',1))
    if mode not in {'single','ams','independent_tools'} or not 1<=count<=16:raise ValueError('Choose a color system and capacity')
    if mode=='single':count=1
    return {'id':'export-'+uuid.uuid4().hex[:10],'name':name,'volume':volume,'color_system':mode,'color_count':count,'delivery':'export_only'}

@router.get('/api/assemblies')
async def overview():return {'printers':fleet(),'plans':data['plans'][-50:][::-1],'note':'Direct U1 preparation is available. Other printer definitions export geometry for their own slicer. No plan starts a print automatically.'}
@router.post('/api/assemblies/printers')
async def register(request:Request):
    p=validate_target(await request.json());data['printers'].append(p);persist();return p

async def run(plan,item,targets,cell,filament):
    module=portal()
    try:
        if any(t['delivery']=='direct_u1' for t in targets):
            await module.native('u1_preferences')
            if not (await module.native('u1_health')).get('validated_binary_unchanged'):raise ValueError('Validate the installed Orca binary before native preparation')
        update(plan,status='running',stage='Cutting closed solids and checking volume conservation')
        raw=(ROOT/'models'/item['path']).read_bytes()
        if len(raw)>50_000_000:raise ValueError('Splitting currently supports models up to 50 MB')
        async with httpx.AsyncClient(trust_env=False,timeout=900) as client:
            r=await client.post(CAD_URL+'/split',headers={'X-PrintFlow-Token':bridge_token()},json={'extension':item['extension'],'data':base64.b64encode(raw).decode(),'cell_mm':cell})
        if not r.is_success:raise ValueError(r.json().get('detail','Splitting failed'))
        dest=ROOT/'models'/'assemblies'/plan['id'];dest.mkdir(parents=True,exist_ok=False)
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            infos=z.infolist()
            if len(infos)>650 or sum(i.file_size for i in infos)>400_000_000 or len(set(z.namelist()))!=len(infos):raise ValueError('Worker result exceeds the assembly limits')
            for info in infos:
                if Path(info.filename).name!=info.filename or Path(info.filename).suffix not in {'.stl','.3mf','.json'}:raise ValueError('Invalid worker artifact')
            manifest=json.loads(z.read('assembly-plan.json'))
            for info in infos:(dest/info.filename).write_bytes(z.read(info))
        update(plan,stage='Building saved section projects and printer assignments')
        if 'Assemblies' not in module.folders:module.folders.append('Assemblies');save_json(DATA/'folders.json',module.folders)
        parts=[];created=[];counts={p['id']:0 for p in targets}
        for part in manifest['parts']:
            compatible=[p for p in targets if len(part['colors'])<=p['color_count']]
            if not compatible:raise ValueError('No selected printer can print this section’s color count. Use separate-color source parts or include a multicolor printer.')
            target=min(compatible,key=lambda p:counts[p['id']]);counts[target['id']]+=1
            path=dest/(part['file'] if len(part['colors'])==1 and item['extension']=='.stl' else part['color_file'])
            if target['delivery']=='direct_u1' and item['extension']=='.3mf':
                sub=dest/f"section-{part['index']:02d}";sub.mkdir()
                # Local copies give the native bridge a bounded, shared-origin assembly.
                import shutil
                shutil.copy2(dest/part['manifest'],sub/'manifest.json');shutil.copy2(dest/part['file'],sub/part['file'])
                for region in part['regions']:shutil.copy2(dest/region['file'],sub/region['file'])
                prepared=await module.native('u1_prepare_assembly',{'manifest':(sub/'manifest.json').relative_to(ROOT/'models').as_posix(),'filament':filament})
                if manifest['profiles']:
                    prepared=await module.native('u1_set_filament_slots',{'project':prepared['project'],'filaments':[x[0] for x in manifest['profiles']],'colors':manifest['colors']})
                artifact=await module.host('GET','/artifact',params={'path':prepared['project']},timeout=90);path=sub/'section.3mf';path.write_bytes(artifact.content)
            f={'id':uuid.uuid4().hex[:16],'name':Path(item['name']).stem+f" · section {part['index']:02d}"+path.suffix,'folder':'Assemblies','extension':path.suffix,'path':path.relative_to(ROOT/'models').as_posix(),'size':path.stat().st_size,'created_at':now(),'assembly_plan_id':plan['id'],'revision_of':item['id']}
            created.append(f)
            parts.append(part|{'file_id':f['id'],'printer_id':target['id'],'printer_name':target['name'],'delivery':target['delivery'],'status':'needs_preparation' if target['delivery']=='direct_u1' else 'export_ready'})
        package=dest/'assembly-package.zip'
        manifest['assignments']=parts
        (dest/'assembly-plan.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(dest/'assembly-plan.json','assembly-plan.json')
            z.writestr('ASSEMBLY.txt','Match each numbered section using grid coordinates and assembly_translation_mm. Flat cut faces need a suitable adhesive and manual alignment. These are geometry exports, not ready-to-run G-code. Review every section in the target printer slicer, including orientation, support and color mapping. Print one part per cleared bed; no automatic consecutive start. No structural strength is certified.\n')
            for part in parts:
                for name in (part['file'],part['color_file']):z.write(dest/name,name)
        module.files.extend(created);save_json(module.store_path,module.files)
        update(plan,status='ready',stage='Sections ready for review',parts=parts,geometry={k:manifest[k] for k in ('grid','source_dimensions','source_volume_mm3','split_volume_mm3','joint')},completed_at=now())
        module.events.emit('library',{'assembly_id':plan['id']})
    except Exception as exc:update(plan,status='error',stage='Assembly planning failed',error=str(exc))

@router.post('/api/assemblies')
async def create(request:Request):
    b=await request.json();item=portal().find_file(b['file_id']);ids=b.get('printer_ids',[])
    if not isinstance(ids,list) or not 1<=len(set(ids))<=8:raise ValueError('Choose one to eight target printers')
    targets=[p for p in fleet() if p['id'] in ids]
    if len(targets)!=len(set(ids)):raise ValueError('Unknown printer target')
    if any(p['status'] in {'queued','running'} for p in data['plans']):raise ValueError('Wait for the current split to finish')
    meta=await portal().model_scene(item['id']);multicolor=(meta.get('color_count') or 1)>1
    if multicolor and max(p['color_count'] for p in targets)<(meta['color_count']):raise ValueError('Select a printer with enough color slots. Separate-color assembly parts must be designed explicitly.')
    margin=float(b.get('margin_mm',10));reserve=float(b.get('tower_reserve_mm',50 if multicolor else 0))
    if not math.isfinite(margin) or not 5<=margin<=40 or not math.isfinite(reserve) or not 0<=reserve<=100:raise ValueError('Use a 5–40 mm edge margin and 0–100 mm tower reserve')
    cell=[min(p['volume'][i] for p in targets)-(2*margin+(reserve if i==0 else 0) if i<2 else 2) for i in range(3)]
    if min(cell)<10:raise ValueError('The selected build area is too small after margins')
    filament=str(b.get('filament','')).strip()
    if any(p['delivery']=='direct_u1' for p in targets) and not filament:raise ValueError('Choose the native filament profile for U1 section preparation')
    plan={'id':uuid.uuid4().hex[:16],'name':item['name'],'source_file_id':item['id'],'printer_ids':ids,'cell_mm':cell,'margin_mm':margin,'tower_reserve_mm':reserve,'status':'queued','stage':'Queued','parts':[],'created_at':now()}
    data['plans'].append(plan);persist();task=asyncio.create_task(run(plan,item,targets,cell,filament));portal().tasks.add(task);task.add_done_callback(portal().tasks.discard);return plan

@router.get('/api/assemblies/{pid}/download')
async def download(pid:str):
    p=find(pid)
    if p['status']!='ready':raise ValueError('The assembly package is not ready')
    return FileResponse(ROOT/'models'/'assemblies'/pid/'assembly-package.zip',filename='PrintFlow-assembly-'+pid+'.zip')
