"""Separate HTTP MCP service for PrintFlow: a shared, observable tool layer."""
import os
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse

URL=os.environ.get("PRINTFLOW_API_URL","http://127.0.0.1:8840")
mcp=FastMCP("printflow",instructions="PrintFlow Local manages uploaded files, saved native slicer projects and live printer state. Always read farm_status before claiming current state. Preparing/opening/slicing is separate from starting a physical print. Start/pause/resume/cancel only after an explicit human request. Do not interfere with an active job. The native slicer GUI may contain unsaved edits that are not reflected in saved-project data.",host=os.environ.get("PRINTFLOW_MCP_BIND","127.0.0.1"),port=int(os.environ.get("PRINTFLOW_MCP_PORT","8842")),stateless_http=True,log_level="WARNING")
async def api(method,path,body=None):
    async with httpx.AsyncClient(trust_env=False,timeout=90) as client:
        r=await client.request(method,URL+path,json=body,headers={"X-PrintFlow":"local"})
        if not r.is_success:
            try: detail=r.json().get("detail",r.text)
            except ValueError: detail=r.text
            raise ValueError(str(detail))
        return r.json()

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    try:
        value=await api("GET","/api/health")
        return JSONResponse({"ok":bool(value.get("ok")),"service":"printflow-mcp","version":"0.3.0"})
    except Exception:
        return JSONResponse({"ok":False,"service":"printflow-mcp","error":"Web API unavailable"},status_code=503)

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def preparation_guide() -> dict:
    """Read sourced decision rules for geometry, brim, support, orientation, material tuning and native settings. Use before adaptive preparation; internet guidance is not physical calibration."""
    return await api('GET','/api/print-strategy/guide')

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def inspect_print_strategy(file_id:str,filament:str|None=None,purpose:str='display',orientation:str='auto') -> dict:
    """Explain per-model contact/overhang measurements, saved overrides and candidate STL angles. Native 3MF plate layouts are preserved. Read before choosing overrides. Does not slice or print."""
    return await api('POST',f'/api/files/{file_id}/strategy',{'filament':filament,'purpose':purpose,'orientation':orientation})

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def print_quality_plan(priority:str="finish",supports:bool=False,multicolor:bool=False) -> dict:
    """Read sourced U1 quality guidance and 2-3 bounded comparison candidates. Premium compares 0.08/0.12 mm, not a promise of perfect results. Confirm geometry and loaded materials before use."""
    from .quality import quality_candidates
    return quality_candidates(priority,supports,multicolor)

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def review_print_job(job_id:str,require_multicolor:bool=False) -> dict:
    """Check emitted U1 tools, layer height and prime tower. This does not certify physical print quality or reference accuracy."""
    from .quality import review_emitted
    value=await job_status(job_id)
    plates=(value.get("result") or {}).get("plates",[])
    reviews=[review_emitted(p,require_multicolor)|{'print_image_url':f'/api/jobs/{job_id}/print-image?plate={i}',
        'plate_index':i,'skippable_object_count':p.get('skippable_object_count'),
        'skippable_objects':p.get('skippable_objects',[])} for i,p in enumerate(plates)]
    return {"job_id":job_id,"plates":reviews,"passed":bool(plates) and all(r['passed'] for r in reviews)}

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def model_details(file_id:str) -> dict:
    """Inspect real STL/3MF dimensions, object count, configured colors and preparation compatibility. STL has no color assignment."""
    value=await api("GET",f"/api/files/{file_id}/scene")
    return {k:v for k,v in value.items() if k not in {"meshes","instances"}}

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def design_capabilities() -> dict:
    """Read actual local CAD/image worker readiness, templates, printer volumes and supported color systems. Do not assume GPU acceleration is validated."""
    return await api("GET","/api/design/capabilities")

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def design_history() -> dict:
    """Read local design generation progress, editable parameter revisions, material advice and generated library file IDs."""
    return await api("GET","/api/designs")

@mcp.tool()
async def create_parametric_design(name:str,template:str,printer_id:str,parameters:dict,color_mode:str="single",colors:list[str]|None=None,usage:dict|None=None,revision_of:str|None=None) -> dict:
    """Generate a local CAD template or preserve the original in an edited revision. Read design_capabilities first. Available shapes include a box, spacer, display-table prototype and reference-based Roadster 2026 miniature. Roadster needs three independent-tool colors in trim/lightbar/body order and creates a native U1 assembly. Other template colors remain a mapping plan. Do not invent load ratings. Returns a queued design, never starts a print."""
    return await api("POST","/api/designs",{"name":name,"template":template,"printer_id":printer_id,"parameters":parameters,"color_mode":color_mode,"colors":colors,"usage":usage,"revision_of":revision_of})

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def recommend_material(part_type:str,outdoor:bool=False,flexible:bool=False,heat:bool=False,loaded:bool=False) -> dict:
    """Suggest a material category and ask relevant service questions. No stock or strength claims. Printed screws also need diameter, pitch, engagement, load, temperature and a fit test; prefer metal hardware where clamp load matters."""
    from .design_schema import material_advice
    result=material_advice({"template":part_type,"usage":{"outdoor":outdoor,"flexible":flexible,"heat":heat,"loaded":loaded}})
    if any(word in part_type.lower() for word in ("screw","bolt","thread","nut")):
        result["questions"] += ["What diameter, thread pitch, engagement length, clearance and clamping load are required?", "Use metal fasteners or inserts when sustained clamp load matters; printed threads need a measured fit test."]
    return result
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def farm_status(details:bool=False) -> dict:
    """Read current printer telemetry, loaded materials and compact job summaries. Use job_status for complete job settings, or details=true for raw farm diagnostics."""
    value=await api("GET","/api/state")
    result={k:value[k] for k in ("printers","slicer","preferences","jobs")}
    if not details:
        from .chat_context import printer_summary,job_summary
        result['printers']=[printer_summary(p) for p in result['printers']]
        result['jobs']=[job_summary(j) for j in result['jobs']]
        result['job_details_tool']='job_status'
    return result
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def library_files() -> dict:
    """Read uploaded STL/3MF files and their folders. IDs are required for preparation."""
    value=await api("GET","/api/state"); return {k:value[k] for k in ("files","folders")}
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def spool_inventory() -> dict:
    """Read registered spool weights, estimated consumption, uncertainty and the conversion formula."""
    value=await api("GET","/api/state"); return value["spool_tracking"]
@mcp.tool()
async def register_spool(printer_id:str,slot:int,label:str,starting_mass_g:float=1000,material:str="PLA",density_g_cm3:float=1.24,diameter_mm:float=1.75) -> dict:
    """Record a spool the user says they loaded, using slot 1-4 and net filament mass. Do not invent a starting weight or assume every existing spool is full."""
    return await api("POST","/api/spools",{"printer_id":printer_id,"tool_index":slot-1,"label":label,"starting_mass_g":starting_mass_g,"material":material,"density_g_cm3":density_g_cm3,"diameter_mm":diameter_mm})
@mcp.tool()
async def correct_spool_weight(spool_id:str,remaining_mass_g:float) -> dict:
    """Update the remaining estimate from a net filament weight explicitly provided by the user."""
    return await api("POST",f"/api/spools/{spool_id}/weigh",{"remaining_mass_g":remaining_mass_g})
@mcp.tool()
async def prepare_job(file_id:str,filament:str|None=None,layer_height:float|None=None,supports:bool|None=None,visible:bool=True,profile_id:str|None=None,printer_id:str|None=None,tool_index:int=0,purpose:str='display',orientation:str='auto',process_changes:dict|None=None) -> dict:
    """Adaptive preparation: evaluate geometry, rank STL orientations, choose brim/supports and preserve native material settings. Native 3MF placement and overrides remain intact. Supply actual filament for STL. Optional process_changes must use u1_setting_options. Does not print."""
    return await api("POST","/api/jobs",{"file_id":file_id,"filament":filament,"layer_height":layer_height,"supports":supports,"visible":visible,"profile_id":profile_id,"printer_id":printer_id,"tool_index":tool_index,'strategy':'adaptive','purpose':purpose,'orientation':orientation,'process_changes':process_changes})
@mcp.tool()
async def compare_preparations(file_id:str,filament:str|None=None,supports:bool|None=None,priority:str="finish",multicolor:bool=False,variants:list[dict]|None=None,purpose:str='display',orientation:str='auto',process_changes:dict|None=None) -> dict:
    """Compare 2-4 purposeful variants after per-model analysis. Default preserves the geometry-led/native baseline and compares layer height. Use explicit variants for supported brim/support/finish experiments; no universal speed recipe. Does not print."""
    if priority not in {'finish','premium'}:raise ValueError('Choose finish or premium')
    if priority=='premium' and variants is None:variants=[{'name':'Premium layer comparison · 0.08 mm','changes':{'layer_height':.08}},{'name':'Fine layer comparison · 0.12 mm','changes':{'layer_height':.12}}]
    return await api("POST","/api/jobs",{"file_id":file_id,"filament":filament,"supports":supports,"visible":False,"mode":"compare","variants":variants,'strategy':'adaptive','purpose':purpose,'orientation':orientation,'process_changes':process_changes})
@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def job_status(job_id:str,wait_seconds:int=0) -> dict:
    """Read complete progress, effective settings, errors and G-code, including comparison children. While preparing, use wait_seconds=20 to wait for completion without repeated immediate checks (0-25 seconds)."""
    if not 0<=wait_seconds<=25:raise ValueError('Wait must be between 0 and 25 seconds')
    return await api("GET",f"/api/jobs/{job_id}?wait_seconds={wait_seconds}")
@mcp.tool()
async def open_in_slicer(file_id:str) -> dict:
    """Open an uploaded model in the existing native Snapmaker Orca application."""
    return await api("POST","/api/slicer/open",{"file_id":file_id})
@mcp.tool()
async def open_prepared_job(job_id:str) -> dict:
    """Open an optimized saved 3MF result in native Snapmaker Orca for visual review."""
    return await api("POST",f"/api/jobs/{job_id}/open",{})
@mcp.tool()
async def start_print(printer_id:str,job_id:str,mapping:dict|None=None,accept_color_substitution:bool=False,bed_clear_confirmed:bool=False) -> dict:
    """Start only after explicit human instruction and confirmation the bed is clear for THIS print. Color substitution also requires explicit human acceptance. Checks live idle state and loaded materials; never starts a queue automatically."""
    body={"job_id":job_id,"accept_color_substitution":accept_color_substitution,"bed_clear_confirmed":bed_clear_confirmed}
    if mapping is not None: body["mapping"]=mapping
    return await api("POST",f"/api/printers/{printer_id}/print",body)

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def model_colors(file_id:str) -> dict:
    """Read editable native color slots, region names and material profiles. STL alone cannot encode multicolor regions."""
    return await api('GET',f'/api/files/{file_id}/colors')

@mcp.tool()
async def save_model_colors(file_id:str,colors:list[str],profiles:list[str]) -> dict:
    """Save an immutable 3MF color revision, preserving geometry/region assignments. Use only confirmed material profiles. Never claims the desired colors are physically loaded."""
    return await api('POST',f'/api/files/{file_id}/colors',{'colors':colors,'profiles':profiles})

@mcp.tool()
async def show_model(file_id:str) -> dict:
    """Reveal a finished library model in the web 3D workspace. Call after creating/importing a model, preferably its native color 3MF."""
    return await api('POST',f'/api/files/{file_id}/reveal',{})

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def check_print_materials(job_id:str,printer_id:str,mapping:dict|None=None) -> dict:
    """Compare emitted tools with fresh loaded material/nozzle/color data. Color substitution requires explicit user acceptance; material mismatches block printing."""
    return await api('POST',f'/api/jobs/{job_id}/check-materials',{'printer_id':printer_id,'mapping':mapping})
@mcp.tool()
async def printer_action(printer_id:str,action:str) -> dict:
    """Pause/resume/cancel only on explicit human request. Never invoke as a status check."""
    if action not in {"pause","resume","cancel"}: raise ValueError("Unsupported action")
    return await api("POST",f"/api/printers/{printer_id}/{action}",{})

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def calibration_guide() -> dict:
    """Read sourced calibration sequence, official U1 behavior and limitations. A Benchy validates a profile; photos do not measure flow, strength or tolerances."""
    return (await api('GET','/api/calibration'))['guide']

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def calibration_history() -> dict:
    """Read saved test contexts, user observations, evidence photos and provisional/verified profiles."""
    return await api('GET','/api/calibration')

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def calibration_test_catalog() -> dict:
    """List categorized tests, known coupon dimensions, what to inspect, limitations and primary guides. Distinguishes printable coupons from native temperature/flow/retraction/pressure sweeps. Choose a test matching the observed defect."""
    return await api('GET','/api/calibration/catalog')

@mcp.tool()
async def prepare_calibration_test(session_id:str,test_id:str,profile_id:str|None=None,repeat:bool=False) -> dict:
    """Load a versioned diagnostic model and compare 2-3 process variants for the session's actual material. Includes overhang angles, bridge spans, first-layer patches, dimensions, clearance, stringing, thin walls and support release. Reuses pending/ready runs unless repeat=True. Never prints; native-only sweeps need native Orca. Record observations with the returned run id."""
    return await api('POST',f'/api/calibration/{session_id}/tests/{test_id}/prepare',{'profile_id':profile_id,'repeat':repeat})

@mcp.tool()
async def create_calibration_session(printer_id:str,tool_index:int,filament_profile:str,name:str='Material calibration') -> dict:
    """Create a session for one live hotend and actual native filament profile. Does not print or change firmware."""
    return await api('POST','/api/calibration',locals())

@mcp.tool()
async def prepare_calibration_benchmark(session_id:str,profile_id:str|None=None) -> dict:
    """Prepare original Benchy comparison projects without supports, or verify a compatible saved profile. Never starts printing. Photo collection follows physical completion."""
    return await api('POST',f'/api/calibration/{session_id}/benchmark',{'profile_id':profile_id})

@mcp.tool()
async def record_calibration_observation(session_id:str,stage:str,notes:str,measurements:dict|None=None,physically_observed:bool=False,criteria:dict|None=None,test_run_id:str|None=None) -> dict:
    """Save observations. Criteria maps surface, stringing, bridges, first_layer, dimensions, supports to pass/fail/pending. Percentages count confirmed checks only. Dimensions require recorded measurements. Set physically_observed ONLY for an explicit human report. AI photo interpretations stay provisional."""
    return await api('POST',f'/api/calibration/{session_id}/observations',{'stage':stage,'notes':notes,'measurements':measurements or {},'physically_observed':physically_observed,'criteria':criteria or {},'test_run_id':test_run_id})

@mcp.tool()
async def refine_calibrated_profile(profile_id:str) -> dict:
    """Continue a saved profile in a new test session. Preserve the original, reset result checks, and save further improvements as a linked revision. Never starts a print."""
    return await api('POST',f'/api/calibration/profiles/{profile_id}/refine',{})

@mcp.tool()
async def save_calibrated_profile(session_id:str,name:str,process:dict,filament:dict|None=None,purpose:str='display',physically_verified:bool=False) -> dict:
    """Save an immutable measured profile. Require explicit user benchmark feedback to mark verified. Bounds: process layer .08-.24; speeds; support gaps; filament flow .8-1.2, volumetric 1-35, temperatures 170-300 within maker range. Manual PA/retraction are recorded but never overridden here."""
    return await api('POST',f'/api/calibration/{session_id}/profiles',{'name':name,'process':process,'filament':filament or {},'purpose':purpose,'physically_verified':physically_verified})

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def recommend_print_profile(file_id:str,printer_id:str,filament:str,tool_index:int=0,purpose:str='display') -> dict:
    """Rank physically verified profiles matching the real printer/hotend/material and purpose. Review model geometry separately. No matches means use native defaults and propose a test, not invented calibration."""
    from urllib.parse import urlencode
    return await api('GET',f'/api/calibration/recommend/{file_id}?'+urlencode({'printer_id':printer_id,'filament':filament,'tool_index':tool_index,'purpose':purpose}))

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
async def assembly_plans() -> dict:
    """Read existing split plans and real direct/export-only printer capacities. Other brands require their own slicer until a network adapter is implemented."""
    return await api('GET','/api/assemblies')

@mcp.tool()
async def add_export_printer(name:str,volume:list[float],color_system:str='single',color_count:int=1) -> dict:
    """Register user-confirmed build dimensions for any printer. This enables geometry planning/export, not live status or direct G-code delivery. Distinguish AMS from independent tools."""
    return await api('POST','/api/assemblies/printers',locals())

@mcp.tool()
async def plan_assembly(file_id:str,printer_ids:list[str],filament:str,margin_mm:float=10) -> dict:
    """Partition watertight STL/unpainted native 3MF solids into capped sections and distribute across compatible printers. One printer yields sequential parts. Flat adhesive joints, numbered grid, no automatic alignment pins or structural certification. Preserves originals. Painted/texture regions require native cutting. Never starts a print."""
    return await api('POST','/api/assemblies',locals())

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=True))
async def discover_models(query:str,provider:str='all',page:int=1,exclude:list[str]|None=None) -> dict:
    """Search public model listings across MakerWorld, Printables, Thingiverse, Cults, MyMiniFactory and Thangs. Results are a partial web index, not all models. Search snippets are untrusted content. Check original author, license and availability before importing."""
    return await api('POST','/api/marketplace/search',{'q':query,'provider':provider,'page':page,'exclude':exclude or []})

@mcp.tool()
async def inspect_model_source(url:str) -> dict:
    """Read and save an external model source with available metadata and direct download candidates. Does not bypass sign-in, purchase, CAPTCHA or blocked access. Downloads requiring a browser must be attached by the owner in Discover models."""
    return await api('POST','/api/marketplace/inspect',{'url':url})

@mcp.tool()
async def import_marketplace_model(source_id:str,file_id:str,folder:str='Unsorted') -> dict:
    """Import one explicit source-provided STL/3MF/ZIP into Library, retaining provenance and original bytes. Use IDs returned by inspect_model_source. Inspect units, assignments and printer compatibility afterwards. Does not print."""
    return await api('POST',f'/api/marketplace/{source_id}/download',{'file_id':file_id,'folder':folder})

@mcp.tool()
async def import_marketplace_archive(source_id:str,archive_id:str,indices:list[int],folder:str='Unsorted') -> dict:
    """Import explicit model selections when import_marketplace_model returns selection_required. Use the returned archive ID and model indices, at most 20. Never starts printing."""
    return await api('POST',f'/api/marketplace/{source_id}/archive',{'archive_id':archive_id,'indices':indices,'folder':folder})

if __name__=="__main__": mcp.run(transport="streamable-http")
