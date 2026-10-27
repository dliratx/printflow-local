"""Local web API. UI and MCP share these operations and persistent state."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import uuid
import httpx
from fastapi import FastAPI,HTTPException,Request,UploadFile,File,Form
from fastapi.responses import FileResponse,JSONResponse,Response,StreamingResponse
from fastapi.staticfiles import StaticFiles
from .common import ROOT,DATA,Events,bridge_token,now,read_json,save_json
from .printers import ADAPTERS,normalize_host
from .spools import SpoolLedger
from . import previews
from . import colors
from . import calibration
from . import marketplace
from . import scene_preview
from . import print_strategy
from .chat_context import chat_context

events=Events(); printers={}; live={}; tasks=set()
spools=SpoolLedger()
store_path=DATA/"library.json"; job_path=DATA/"jobs.json"
files=read_json(store_path,[]); jobs=read_json(job_path,[])
folders=read_json(DATA/"folders.json",["Unsorted","Figures","Functional","Multicolor"])
host_status={"slicer":{"available":False,"process_running":False,"visible_control_available":False,"detail":"Connecting to the Windows bridge"},"codex":{"connected":False,"authenticated":False,"busy":False},"chat":[]}
HOST=os.environ.get("PRINTFLOW_HOST_URL","http://127.0.0.1:8841")
http=None
config=read_json(DATA/"printers.json",[])
for job in jobs:
    if job.get("status") in {"running","queued"}: job.update(status="interrupted",error="The service restarted; prepare this job again")

async def host(method,path,**kwargs):
    r=await http.request(method,HOST+path,headers={"X-PrintFlow-Token":bridge_token()},**kwargs)
    if not r.is_success:
        try: detail=r.json().get("detail",r.text)
        except ValueError: detail=r.text
        raise ValueError(str(detail))
    return r
async def native(name,arguments={}): return (await host("POST","/tools/call",json={"name":name,"arguments":arguments},timeout=660)).json()
def find_file(file_id):
    result=next((f for f in files if f["id"]==file_id),None)
    if not result: raise ValueError("File not found")
    return result
def find_job(job_id):
    result=next((j for j in jobs if j["id"]==job_id),None)
    if not result: raise ValueError("Job not found")
    return result
def persist_jobs(): save_json(job_path,jobs)
def activity(text): events.emit("activity",{"text":text})

async def poll():
    global host_status
    while True:
        try:
            values=await asyncio.gather(*(p.status() for p in printers.values()))
            for item in values:
                spools.observe(item)
                live[item["id"]]=item
                calibration.observe(item)
            try:
                previous=host_status.get('codex',{})
                host_status=(await host("GET","/status",timeout=4)).json()
                current=host_status.get('codex',{})
                if previous.get('busy') and not current.get('busy') and current.get('progress',{}).get('phase')=='completed':
                    started=current['progress'].get('started_at','~')
                    created=[f for f in files if f.get('created_at','')>=started]
                    if created:
                        created.sort(key=lambda f:(f.get('extension')=='.3mf',f.get('created_at','')),reverse=True)
                        colors.publish_model(created[0]['id'])
            except Exception as exc:
                host_status["slicer"].update(available=False,detail=f"Windows bridge is offline: {exc}")
                host_status["codex"].update(connected=False,error=str(exc))
            events.emit("state",{"updated":True})
        except Exception as exc: activity(str(exc))
        await asyncio.sleep(3)

async def relay_host_events():
    while True:
        try:
            async with http.stream("GET",HOST+"/events",headers={"X-PrintFlow-Token":bridge_token()},timeout=None) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        event=json.loads(line[6:]); events.emit(event["type"],event["data"])
        except asyncio.CancelledError: raise
        except Exception: await asyncio.sleep(4)

@asynccontextmanager
async def lifespan(app):
    global http
    http=httpx.AsyncClient(timeout=10,trust_env=False)
    for item in config:
        if item["kind"] in ADAPTERS: printers[item["id"]]=ADAPTERS[item["kind"]](item)
    background=[asyncio.create_task(poll()),asyncio.create_task(relay_host_events())]
    yield
    for task in [*background,*tasks]: task.cancel()
    spools.save()
    await asyncio.gather(*(p.close() for p in printers.values()),return_exceptions=True)
    await http.aclose()

app=FastAPI(title="PrintFlow Local",version="0.3.0",lifespan=lifespan)
from .designs import router as design_router
from .assemblies import router as assembly_router
app.include_router(design_router)
app.include_router(assembly_router)
app.include_router(colors.router)
app.include_router(calibration.router)
app.include_router(marketplace.router)
@app.middleware("http")
async def local_mutations(request:Request,call_next):
    # Same-origin browser custom header prevents drive-by cross-site mutations.
    if request.method in {"POST","PUT","PATCH","DELETE"} and request.headers.get("X-PrintFlow")!="local": return JSONResponse({"detail":"Same-origin PrintFlow request required"},403)
    if request.method in {"POST","PUT","PATCH","DELETE"}:
        origin=request.headers.get("Origin")
        if origin and origin.rstrip("/")!=str(request.base_url).rstrip("/"): return JSONResponse({"detail":"Origin rejected"},403)
    try:
        response=await call_next(request)
        if request.url.path=="/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"]="no-store"
        return response
    except (ValueError,KeyError,TypeError) as exc: return JSONResponse({"detail":str(exc)},400)

@app.exception_handler(ValueError)
async def invalid(request,exc): return JSONResponse({"detail":str(exc)},400)

def state():
    preferences=read_json(ROOT/"printer_preferences.json",{})
    for printer in live.values():
        for filament in printer.get("filaments",[]): filament["spool"]=spools.active_for(printer["id"],filament["slot"]-1)
    return {"calibration_alerts":[{"id":s["id"],"name":s["name"],"completed_count":len(s.get("completed_jobs",[]))} for s in calibration.records["sessions"] if s["status"]=="awaiting_photos"],"version":"0.3.0","model_ready":read_json(DATA/'model-ready.json',None),"printers":list(live.values()),"files":files,"jobs":jobs[-50:][::-1],"folders":folders,"spools":spools.spools,"spool_tracking":spools.summary(),"codex":host_status.get("codex",{}),"chat":host_status.get("chat",[]),"slicer":host_status.get("slicer",{}),"preferences":preferences,"activity":events.history[-30:],"adapters":[{"kind":"snapmaker_u1","available":True},{"kind":"flashforge","available":False,"note":"Future adapter"}]}
@app.get("/api/health")
async def health(): return {"ok":True,"service":"printflow-web","host_bridge":host_status.get("slicer",{}).get("available",False)}
@app.get("/api/state")
async def get_state(): return state()
@app.get("/api/jobs/{job_id}")
async def get_job(job_id:str,wait_seconds:int=0):
    if not 0<=wait_seconds<=25:raise ValueError('Wait must be between 0 and 25 seconds')
    job=find_job(job_id)
    deadline=asyncio.get_running_loop().time()+wait_seconds
    while job['status'] in {'queued','running'} and asyncio.get_running_loop().time()<deadline:
        await asyncio.sleep(min(.25,max(0,deadline-asyncio.get_running_loop().time())))
    # One comparison response includes its variants; no extra model round trips.
    if job.get('child_job_ids'):
        return dict(job,comparison_jobs=[find_job(key) for key in job['child_job_ids']])
    return job
@app.get("/api/events")
async def event_stream(): return StreamingResponse(events.stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
@app.post("/api/spools")
async def register_spool(request:Request):
    body=await request.json()
    if body.get("printer_id") not in printers: raise ValueError("Select a connected printer")
    spool=spools.register(body,live.get(body["printer_id"]))
    events.emit("spool",spool); return spool
@app.post("/api/spools/{spool_id}/weigh")
async def weigh_spool(spool_id:str,request:Request):
    body=await request.json(); spool=spools.weigh(spool_id,body["remaining_mass_g"])
    events.emit("spool",spool); return spool
@app.post("/api/upload")
async def upload(files_in:list[UploadFile]=File(alias="files"),folder:str=Form("Unsorted")):
    if folder not in folders: raise ValueError("Unknown folder")
    created=[]
    for upload in files_in:
        original=Path(upload.filename.replace("\\","/")).name
        suffix=Path(original).suffix.lower()
        if suffix not in {".stl",".3mf"}: raise ValueError("This version prepares STL and native 3MF projects")
        file_id=uuid.uuid4().hex[:16]
        clean=re.sub(r"[^\w .()\-]","_",original,flags=re.UNICODE)
        folder_slug=re.sub(r"[^\w\-]","_",folder)
        relative=Path("library")/folder_slug/file_id/clean
        dest=ROOT/"models"/relative; dest.parent.mkdir(parents=True,exist_ok=True)
        size=0
        with dest.open("wb") as writer:
            while chunk:=await upload.read(1024*1024):
                size+=len(chunk)
                if size>250*1024*1024:
                    writer.close(); dest.unlink(missing_ok=True); raise ValueError("The file exceeds 250 MB")
                writer.write(chunk)
        item={"id":file_id,"name":original,"folder":folder,"path":relative.as_posix(),"extension":suffix,"size":size,"created_at":now()}
        files.append(item); created.append(item)
    save_json(store_path,files); events.emit("library",created)
    return {"files":created}
@app.post("/api/folders")
async def create_folder(request:Request):
    name=str((await request.json()).get("name","")).strip()
    if not name or len(name)>60 or any(c in name for c in "\\/\x00"): raise ValueError("Invalid folder name")
    if name not in folders: folders.append(name); save_json(DATA/"folders.json",folders)
    return {"folders":folders}
@app.get("/api/files/{file_id}/content")
async def file_content(file_id:str):
    item=find_file(file_id); return FileResponse(ROOT/"models"/item["path"],filename=item["name"])
@app.get("/api/files/{file_id}/preview")
async def model_preview(file_id:str):
    find_file(file_id)
    # An already-open old tab must not rebuild giant JSON meshes on each click.
    return JSONResponse({'detail':'This tab is using an older 3D viewer. Reload PrintFlow to load large models and switch plates.','code':'viewer_update_required'},status_code=409)

@app.get('/api/files/{file_id}/summary')
async def model_summary(file_id:str):
    item=find_file(file_id)
    value=await asyncio.to_thread(previews.quick_metadata,ROOT/'models'/item['path'])
    summary={**(item.get('preview') or {}),**value}
    for key in ('geometry_format','revision','meshes','instances','buffer_bytes'):summary.pop(key,None)
    return summary

@app.get('/api/files/{file_id}/scene')
async def model_scene(file_id:str):
    item=find_file(file_id)
    value=await asyncio.to_thread(scene_preview.scene,ROOT/'models'/item['path'])
    summary={k:v for k,v in value.items() if k not in ('meshes','instances')}
    if item.get('preview')!=summary:
        item['preview']=summary;save_json(store_path,files)
    return value

@app.get('/api/files/{file_id}/scene-buffer')
async def model_scene_buffer(file_id:str,revision:str,mesh:int):
    item=find_file(file_id)
    path=scene_preview.buffer_path(ROOT/'models'/item['path'],revision,mesh)
    return FileResponse(path,media_type='application/octet-stream',headers={'Cache-Control':'private, max-age=31536000, immutable'})

@app.get("/api/files/{file_id}/thumbnail")
async def model_thumbnail(file_id:str,embedded_only:bool=False):
    item=find_file(file_id); path=ROOT/"models"/item["path"]
    embedded=await asyncio.to_thread(previews.embedded_thumbnail,path)
    if embedded:
        data,kind=embedded
        return Response(data,media_type=kind,headers={"Cache-Control":"private, max-age=3600"})
    if embedded_only:raise HTTPException(404,'This file has no saved thumbnail')
    value=await asyncio.to_thread(previews.preview,path)
    data,kind=await asyncio.to_thread(previews.thumbnail,path,value)
    return Response(data,media_type=kind,headers={"Cache-Control":"private, max-age=3600"})

@app.get("/api/profiles")
async def profiles(kind:str="filament"):
    data=await native("u1_list_profiles",{"kind":kind})
    value=data.get("result",data) if isinstance(data,dict) else data
    if kind=="filament" and isinstance(value,list):
        value=[p for p in value if not re.search(r"0\.[268] nozzle",p.get("name",""))]
    return value

def update_job(job,**kwargs):
    if kwargs.get("stage") and kwargs["stage"]!=job.get("stage"):
        job.setdefault("timeline",[]).append({"stage":kwargs["stage"],"at":now()})
    job.update(kwargs); persist_jobs(); events.emit("job",job)

def finish_changes(body):
    # Preserve the native baseline unless a UI choice, planner or experiment
    # explicitly changes it. Never assign one speed/contact recipe to every part.
    changes=dict(body.get('process_changes') or {})
    if body.get('layer_height') is not None:changes['layer_height']=float(body['layer_height'])
    if body.get('supports') is not None:changes['enable_support']=body['supports']
    return changes

@app.get('/api/print-strategy/guide')
async def print_strategy_guide():return print_strategy.guide()

@app.post('/api/files/{file_id}/strategy')
async def model_strategy(file_id:str,request:Request):
    body=await request.json();item=find_file(file_id)
    return await native('u1_print_strategy',{'model':item['path'],'filament':body.get('filament'),'purpose':body.get('purpose','display'),'orientation':body.get('orientation','auto')})

async def run_job(job,body):
    def update(**kwargs): update_job(job,**kwargs)
    try:
        item=find_file(job["file_id"])
        update(status="running",stage="Reading printer preferences and validating Orca",progress=.08)
        preferences=await native("u1_preferences")
        health=await native("u1_health")
        if not health.get("validated_binary_unchanged"):raise ValueError("Snapmaker Orca needs bridge validation before preparation")
        update(stage="Inspecting geometry and material assignments",progress=.16)
        compatibility=await asyncio.to_thread(previews.preparation_metadata,ROOT/'models'/item['path'])
        if not compatibility["preparation_supported"]:raise ValueError(compatibility["preparation_note"])
        plan=None
        if body.get('strategy')=='adaptive':
            update(stage='Evaluating orientation, bed contact, brim and supports',progress=.2)
            plan=await native('u1_print_strategy',{'model':item['path'],'filament':body.get('filament'),'purpose':body.get('purpose','display'),'orientation':body.get('orientation','auto')})
            job['print_strategy']=plan
        if item["extension"]==".stl":
            inspection=await native("u1_inspect_stl",{"model":item["path"]})
            arguments={"model":item["path"],"filament":body["filament"]}
            if plan:arguments['rotation']=plan['orientation']['selected']['rotation']
            prepared=await native("u1_prepare_stl",arguments)
            project=prepared["project"]
        else:
            inspection=await native("u1_inspect_project",{"project":item["path"]}); project=item["path"]
        job["inspection"]=inspection
        update(stage="Preparing copies with the selected finish settings",progress=.3)
        changes=(plan.get('process_changes',{}) if plan else {})|finish_changes(body)
        if body.get('profile_id'):
            if item['extension']=='.3mf' and len(colors.project_palette(ROOT/'models'/item['path']))!=1:raise ValueError('Apply measured filament profiles to single-slot projects. Multicolor assemblies retain their native per-slot profiles.')
            saved=calibration.profile(body['profile_id']);pid=body.get('printer_id');tool=int(body.get('tool_index',0))
            if pid not in printers:raise ValueError('Select the calibrated printer')
            if not calibration.match_profile(saved,await printers[pid].status(),body.get('filament'),tool):raise ValueError('The saved profile does not match the current printer, hotend and loaded material')
            calibration.validate_profile_use(saved,body,item)
            changes.update(saved['process']);job['profile_id']=saved['id']
            if body.get('calibration_session_id'):
                changes['enable_support']=calibration.recipe(body.get('calibration_test_id','benchy'))['supports']
            if saved['filament']:
                project=(await native('u1_apply_filament_calibration',{'project':project,'expected_filament':saved['context']['filament_profile'],'values':saved['filament']}))['project']
        if body.get("mode")=="compare":
            if plan and not body.get('variants'):
                current=float(changes.get('layer_height') or (inspection.get('process') or {}).get('layer_height') or .12)
                alternate=.16 if current<=.12 else .12
                variants=[{'name':'Geometry-led native baseline','changes':{}},{'name':f'Layer comparison · {alternate:.2f} mm','changes':{'layer_height':alternate}}]
            else:variants=body.get("variants") or [{"name":"Fine finish · 0.12 mm","changes":{"layer_height":.12}},{"name":"Balanced finish · 0.16 mm","changes":{"layer_height":.16}}]
            variants=[dict(v,changes=changes|v.get('changes',{})) for v in variants]
            update(stage=f"Snapmaker Orca is slicing {len(variants)} comparison variants",progress=.5)
            compared=await native("u1_compare_variants",{"project":project,"variants":variants})
            update(stage="Reviewing emitted tools, support settings and estimates",progress=.9)
            children=[]
            for result in compared["variants"]:
                if result['status']=='ok' and body.get('calibration_test_id'):
                    try:calibration.validate_emitted_test(body['calibration_test_id'],result)
                    except ValueError as exc:result=dict(result,status='error',error=str(exc))
                child={"id":uuid.uuid4().hex[:12],"file_id":item["id"],"filename":item["name"],"comparison_id":job["id"],"variant_name":result["name"],"status":"ready" if result["status"]=="ok" else "error","stage":"Ready for review" if result["status"]=="ok" else "Slicing failed","progress":1,"created_at":now(),"result":result,"error":result.get("error"),"timeline":[{"stage":"Variant sliced by Snapmaker Orca","at":now()}]}
                if job.get('profile_id'):child['profile_id']=job['profile_id']
                if plan:child['print_strategy']=plan
                jobs.append(child);children.append(child["id"])
            any_ready=any(find_job(j)['status']=='ready' for j in children)
            update(status="ready" if any_ready else "error",stage="Comparison complete · choose a variant to review" if any_ready else "No valid comparison variant",error=None if any_ready else "All comparison variants failed slicing or emitted-test validation. Review their errors and prepare again.",progress=1,child_job_ids=children,comparison_note=compared["selection_policy"],completed_at=now())
        else:
            update(stage="Snapmaker Orca is generating toolpaths",progress=.5)
            result=await native("u1_slice_project",{"project":project,"changes":changes})
            if result.get("status")!="ok":raise ValueError(result.get("error") or result.get("log_tail") or "Slicing did not complete successfully")
            update(stage="Reviewing emitted tools, support settings and estimates",progress=.9)
            if body.get("visible",True):await host("POST","/open",json={"path":result["project"]})
            update(status="ready",stage="Ready to review and print",progress=1,result=result,error=None,completed_at=now())
        activity("Prepared: "+item["name"])
    except Exception as exc:update(status="error",stage="Preparation failed",error=str(exc),progress=0)

@app.post("/api/jobs")
async def prepare_job(request:Request):
    body=await request.json();item=find_file(body["file_id"])
    if body.get("mode","single") not in {"single","compare"}:raise ValueError("Select single preparation or comparison")
    if item["extension"]==".stl" and not str(body.get("filament") or "").strip():raise ValueError("Choose the actual filament profile for this STL")
    height=float(body.get("layer_height") or .12)
    if not .08<=height<=.24:raise ValueError("Layer height must be between 0.08 and 0.24 mm for the configured U1")
    if body.get("supports") is not None and not isinstance(body["supports"],bool):raise ValueError("Support selection must be true or false")
    if body.get('strategy','manual') not in {'manual','adaptive'}:raise ValueError('Choose manual or adaptive preparation')
    if body.get('process_changes') is not None and not isinstance(body['process_changes'],dict):raise ValueError('Process changes must be an object')
    if body.get("variants") is not None and (not isinstance(body["variants"],list) or not 2<=len(body["variants"])<=4):raise ValueError("Compare two to four variants")
    if len([j for j in jobs if j["status"] in {"running","queued"}])>=3:raise ValueError("Three jobs are already being prepared")
    job={"id":uuid.uuid4().hex[:12],"file_id":item["id"],"filename":item["name"],"status":"queued","stage":"Queued","progress":0,"result":None,"error":None,"created_at":now(),"timeline":[{"stage":"Queued","at":now()}],"request":body,"comparison_parent":body.get("mode")=="compare"}
    jobs.append(job);persist_jobs()
    task=asyncio.create_task(run_job(job,body));tasks.add(task);task.add_done_callback(tasks.discard)
    events.emit("job",job);return job
@app.post("/api/slicer/open")
async def open_slicer(request:Request):
    b=await request.json()
    if b.get("file_id"):
        item=find_file(b["file_id"])
        # Host resolves relative paths against its local models bind mount.
        relative=item["path"]
        # Native bridge accepts a restricted relative model path.
        return (await host("POST","/open",json={"path":relative,"base":"models"})).json()
    return (await host("POST","/open",json={"path":b["project"]})).json()
@app.post("/api/jobs/{job_id}/open")
async def open_job(job_id:str):
    result=find_job(job_id).get("result")
    if not result: raise ValueError("This job does not have a project yet")
    return (await host("POST","/open",json={"path":result["project"]})).json()
@app.get("/api/jobs/{job_id}/download")
async def download(job_id:str,kind:str="project"):
    job=find_job(job_id); result=job.get("result") or {}
    path=result.get("project") if kind=="project" else (result.get("plates") or [{}])[0].get("gcode")
    if not path: raise ValueError("File not generated yet")
    r=await host("GET","/artifact",params={"path":path},timeout=60)
    return Response(r.content,media_type="application/octet-stream",headers={"Content-Disposition":f'attachment; filename="{job_id}.{ "3mf" if kind=="project" else "gcode"}"'})

@app.get('/api/jobs/{job_id}/print-image')
async def job_print_image(job_id:str,plate:int=0):
    result=find_job(job_id).get('result') or {};plates=result.get('plates') or []
    if not 0<=plate<len(plates) or not plates[plate].get('gcode'):raise ValueError('Select a prepared plate to see how it will print')
    r=await host('GET','/print-image',params={'path':plates[plate]['gcode']},timeout=120)
    return Response(r.content,media_type='image/png',headers={'Cache-Control':'private, max-age=3600'})

def parse_toolpaths(text):
    x=y=z=e=0.; absolute_e=True; role="Custom"; tool=0; layers={}; count=0; truncated=False
    number=r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    bounds=[float("inf"),float("inf"),float("-inf"),float("-inf")]
    for raw in text.splitlines():
        if raw.startswith(";TYPE:"): role=raw[6:].strip()
        line=raw.split(";",1)[0].strip()
        if line=="M83": absolute_e=False
        elif line=="M82": absolute_e=True
        elif re.fullmatch(r"T\d+",line): tool=int(line[1:])
        elif line.startswith("G92"):
            match=re.search(r"\bE("+number+r")",line)
            if match: e=float(match[1])
        elif re.match(r"G[0123]\s",line):
            values={key:float(value) for key,value in re.findall(r"\b([XYZE])("+number+r")",line)}
            nx,ny,nz=values.get("X",x),values.get("Y",y),values.get("Z",z)
            ne=values.get("E",e if absolute_e else 0)
            extrusion=ne-e if absolute_e else ne
            if extrusion>0 and (nx!=x or ny!=y) and role!="Custom":
                if count<150000:
                    layers.setdefault(round(nz,4),[]).append([x,y,nx,ny,role,tool]); count+=1
                    bounds=[min(bounds[0],x,nx),min(bounds[1],y,ny),max(bounds[2],x,nx),max(bounds[3],y,ny)]
                else: truncated=True
            x,y,z=nx,ny,nz
            if absolute_e and "E" in values: e=ne
    if not count: bounds=[0,0,270,270]
    return {"layers":[{"z":z,"segments":lines} for z,lines in sorted(layers.items())],"bounds":dict(zip(["min_x","min_y","max_x","max_y"],bounds)),"truncated":truncated,"note":"Simplified XY view of the actual G-code. Arcs are shown by their endpoints; travel moves and firmware macros are omitted."}

@app.get("/api/jobs/{job_id}/toolpaths")
async def toolpaths(job_id:str):
    job=find_job(job_id); result=job.get("result") or {}
    path=(result.get("plates") or [{}])[0].get("gcode")
    if not path: raise ValueError("No toolpaths available yet")
    cache=DATA/"previews"/(job["id"]+"-v2.json")
    if cache.exists(): return read_json(cache,{})
    r=await host("GET","/artifact",params={"path":path},timeout=90)
    if len(r.content)>150*1024*1024: raise ValueError("Use Orca to review G-code larger than 150 MB")
    data=await asyncio.to_thread(parse_toolpaths,r.content.decode("utf-8","replace"))
    save_json(cache,data); return data

@app.post("/api/printers")
async def add_printer(request:Request):
    b=await request.json(); kind=b.get("kind","snapmaker_u1")
    if kind not in ADAPTERS: raise ValueError("This printer type does not have an adapter yet")
    entry={"id":uuid.uuid4().hex[:8],"name":str(b.get("name","Snapmaker U1"))[:80],"host":normalize_host(b["host"]),"kind":kind}
    if b.get("api_key"): entry["api_key"]=b["api_key"]
    adapter=ADAPTERS[kind](entry); found=await adapter.status()
    if not found["connected"]:
        await adapter.close(); raise ValueError(found["status_message"])
    config.append(entry); save_json(DATA/"printers.json",config)
    printers[entry["id"]]=adapter; live[entry["id"]]=found
    return found
@app.get("/api/printers/{pid}/camera.jpg")
async def camera(pid:str):
    if pid not in printers: raise HTTPException(404)
    try:
        data,content_type=await printers[pid].camera()
        return Response(data,media_type=content_type,headers={"Cache-Control":"no-store"})
    except Exception as exc: raise HTTPException(503,"Camera unavailable: "+str(exc))

@app.post("/api/printers/{pid}/print")
async def print_job(pid:str,request:Request):
    if pid not in printers: raise ValueError("Printer not found")
    b=await request.json(); job=find_job(b["job_id"])
    if b.get('bed_clear_confirmed') is not True:raise ValueError('Confirm the bed is clear for this specific print before starting')
    if job["status"]!="ready": raise ValueError("This job is not ready to print")
    adapter=printers[pid]
    # First check prevents even uploading anything during an existing print.
    status=await adapter.require_idle()
    plates=job["result"].get("plates",[])
    if len(plates)!=1: raise ValueError("This version can start single-plate projects only")
    plate=plates[0]; tools=plate.get("tools_zero_based",[])
    mapping={int(k):int(v) for k,v in b.get("mapping",{str(t):t for t in tools}).items()}
    calibration_session=next((s for s in calibration.records['sessions'] if job['id'] in s['jobs'] or job.get('comparison_id') in s['jobs']),None)
    if calibration_session:
        calibration.validate_print_context(calibration_session,status,tools,mapping)
        trial=next((r for r in calibration_session.get('test_runs',[]) if job['id'] in r['jobs'] or job.get('comparison_id') in r['jobs']),None)
        if trial:calibration.validate_emitted_test(trial['test_id'],job['result'])
    if job.get('profile_id'):
        saved=calibration.profile(job['profile_id']);context=saved['context']
        if len(tools)!=1 or mapping.get(tools[0])!=context['tool_index'] or not calibration.match_profile(saved,status,context['filament_profile'],context['tool_index']):
            raise ValueError('This calibrated job requires its tested printer, physical hotend and loaded filament')
    if set(mapping)!=set(tools): raise ValueError("The mapping must include every tool used by the G-code")
    if len(set(mapping.values()))!=len(mapping): raise ValueError("This version requires a different physical tool for each filament slot")
    materials=[x.strip() for x in (plate.get("filament_types") or "").split(";")]
    for logical,physical in mapping.items():
        if not 0<=physical<=3: raise ValueError("Invalid physical tool")
        expected=materials[logical] if logical<len(materials) else ""
        actual=status["filaments"][physical].get("material","")
        if not expected or expected.upper()!=str(actual).upper(): raise ValueError(f"Tool material {physical+1}: expected {expected}, loaded {actual}")
    check=colors.assess(await colors.job_slots(job),status,tools,mapping)
    if check['errors']: raise ValueError(' '.join(check['errors']))
    if check['warnings'] and b.get('accept_color_substitution') is not True:
        raise ValueError('Loaded colors differ from this project. Review the mapping and explicitly accept the substitution. '+ ' '.join(check['warnings']))
    r=await host("GET","/artifact",params={"path":plate["gcode"]},timeout=90)
    filename=f'PrintFlow_{job["id"]}.gcode'
    try: result=await adapter.print_file(r.content,filename,mapping)
    except (httpx.TimeoutException,httpx.NetworkError) as exc:
        job.update(print_outcome="unknown",printer_id=pid); persist_jobs()
        raise ValueError("The connection was interrupted during upload/start; verify printer state before retrying") from exc
    job.update(status="sent",printer_id=pid,print_outcome=result); persist_jobs()
    events.emit("print",{"job_id":job["id"],"printer_id":pid}); return result
@app.post("/api/printers/{pid}/{action}")
async def printer_action(pid:str,action:str):
    if pid not in printers: raise ValueError("Printer not found")
    if action not in {"pause","resume","cancel"}: raise HTTPException(404)
    result=await printers[pid].action(action); activity("Printer: "+action); return result
@app.post("/api/chat")
async def chat(request:Request):
    b=await request.json(); message=str(b.get("message","")).strip()
    if not message or len(message)>24000: raise ValueError("Enter a message of up to 24,000 characters")
    context=chat_context(live.values(),find_file(b['file_id']) if b.get('file_id') else None,jobs,host_status.get('slicer'))
    return (await host("POST","/chat",json={"message":message,"context":context},timeout=65)).json()
@app.post("/api/chat/interrupt")
async def interrupt(): return (await host("POST","/chat/interrupt")).json()
@app.post("/api/codex/approval")
async def approval(request:Request): return (await host("POST","/chat/approval",json=await request.json())).json()
@app.post('/api/codex/approval-policy')
async def approval_policy(request:Request):return (await host('POST','/chat/approval-policy',json=await request.json())).json()
@app.get("/")
async def index(): return FileResponse(ROOT/"web/static/index.html")
app.mount("/static",StaticFiles(directory=str(ROOT/"web/static"),check_dir=False),name="static")
