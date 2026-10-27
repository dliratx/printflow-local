"""Windows MCP bridge for the installed Snapmaker Orca, using project copies.

No remote service, no printer commands. Stdio is reserved for MCP messages.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor/snapmaker-u1-mcp/src"))
BIN = Path(os.environ.get("SNAPMAKER_ORCA_BIN", r"C:\Program Files\Snapmaker_Orca\snapmaker-orca.exe"))
PROFILES = BIN.parent / "resources/profiles/Snapmaker"
MODELS, RUNS = ROOT / "models", ROOT / "runs"
os.environ.update(SNAPMAKER_ORCA_BIN=str(BIN), SNAPMAKER_PROFILE_DIR=str(PROFILES), U1_MODEL_DIR=str(MODELS), U1_OUTPUT_DIR=str(RUNS), SNAPMAKER_U1_MCP_HOME=str(ROOT / ".runtime"))

from mcp.server.fastmcp import FastMCP
from snapmaker_u1_mcp.models import _stl_triangles, u1_mesh_printability
from snapmaker_u1_mcp.paths import safe_file
from snapmaker_u1_mcp.profiles import ProfileStore, ProfileSelection
from printflow import print_strategy

INSTRUCTIONS = """Use Snapmaker Orca U1 project copies. User prioritizes maximum finish and easy support removal. Read u1_preferences and u1_inspect_project first. Material is unknown until specified. Compare 2-4 variants, retain 3MF colors, tool assignments and native U1 G-code. Never claim physically optimal settings from estimates. This server works on saved projects, not the live GUI. It cannot upload/start prints. Full Spectrum painting must be prepared/reviewed in the native GUI; it is preserved, not automatically painted by this server. Review generated projects before printing."""
mcp = FastMCP("snapmaker-u1-windows", instructions=INSTRUCTIONS, log_level="WARNING")

# Bounds restrict routine process editing; machine, temperature and custom G-code
# remain in the native profiles. Limits are configurable only by editing this code.
NUMBERS = {
    "layer_height": (.08,.24), "initial_layer_print_height": (.16,.24), "initial_layer_speed": (10,80), "initial_layer_infill_speed": (10,80), "wall_loops": (1,12), "top_shell_layers": (0,20),
    "bottom_shell_layers": (0,20), "sparse_infill_density": (0,100),
    "support_top_z_distance": (0,.6), "support_bottom_z_distance": (0,.6),
    "support_object_xy_distance": (.1,1), "support_interface_top_layers": (0,8),
    "support_interface_bottom_layers": (0,8), "support_interface_spacing": (0,1),
    "support_base_pattern_spacing": (1,6), "support_threshold_angle": (0,80),
    "support_speed": (10,200), "support_interface_speed": (10,120),
    "support_filament": (0,4), "support_interface_filament": (0,4),
    "tree_support_branch_angle": (20,65), "tree_support_branch_diameter": (1,6),
    "outer_wall_speed": (10,200), "inner_wall_speed": (10,350),
    "top_surface_speed": (10,150), "bridge_speed": (10,100),
    "prime_volume": (15,100), "prime_tower_width": (20,80),
    "prime_tower_brim_width": (0,15), "brim_width": (0,15),
    "brim_object_gap": (0,.5), "seam_gap": (0,30),
}
INTEGER_KEYS = {"wall_loops","top_shell_layers","bottom_shell_layers","support_interface_top_layers","support_interface_bottom_layers","support_filament","support_interface_filament"}
BOOLEANS = {"enable_support","support_on_build_plate_only","enable_prime_tower","flush_into_infill","flush_into_support"}
ENUMS = {
    "support_type": {"tree(auto)","normal(auto)","tree(manual)","normal(manual)"},
    "support_style": {"default","organic","slim","strong","snug","grid"},
    "support_interface_pattern": {"auto","rectilinear","concentric","interlacedrectilinear","grid"},
    "sparse_infill_pattern": {"gyroid","cubic","adaptivecubic","rectilinear","grid","lightning"},
    "brim_type": {"auto_brim","no_brim","outer_only","inner_only","outer_and_inner","brim_ears"},
    "seam_position": {"aligned","back","nearest","random"},
    "ironing_type": {"no ironing","top","topmost","all solid layer"},
}
NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
CONTENT_TYPES = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'
RELATIONSHIPS = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/3dmodel"/></Relationships>'
# Use the namespace required by native Orca/Bambu 3MF projects.
RELATIONSHIPS = RELATIONSHIPS.replace('/2013/3dmodel','/2013/01/3dmodel')
ET.register_namespace("",NS)
def tag(name): return f"{{{NS}}}{name}"
def dump(path: Path, data): path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def standard_filament(profile):
    """Select standard-flow values from profiles that bundle standard/HF variants."""
    result=dict(profile)
    variants=profile.get("filament_flow_support",["standard"])
    if "standard" not in variants: raise ValueError("The factory hotends need a standard-flow filament profile")
    index=variants.index("standard")
    for key,value in profile.items():
        if not isinstance(value,list) or key in {"compatible_printers","compatible_prints"}: continue
        if len(value)==len(variants): result[key]=[value[index]]
        elif len(value)!=1: raise ValueError(f"Unsupported filament array {key!r}")
    return result

def local_file(name: str, extensions={".3mf",".stl",".gcode"}):
    # Inputs may be supplied in models/ or be outputs from previous tools.
    for base in (MODELS,RUNS):
        try: return safe_file(base,name,extensions)
        except Exception: pass
    raise ValueError("File must exist under models/ or runs/ and use an allowed extension")

def read_project(path):
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist()) > 1_000_000_000:
            raise ValueError("3MF expanded size exceeds 1 GB")
        if len(set(z.namelist())) != len(z.namelist()):
            raise ValueError("3MF contains duplicate entries")
        if "Metadata/project_settings.config" not in z.namelist():
            raise ValueError("Save this model as a U1 project in Snapmaker Orca first; project settings are missing")
        cfg=json.loads(z.read("Metadata/project_settings.config"))
        model=str(cfg.get("printer_model",""))
        if model != "Snapmaker U1":
            raise ValueError(f"Expected Snapmaker U1 project, found {model!r}")
        if any(str(x).strip() for x in (cfg.get("post_process") or [])):
            raise ValueError("Project has post-processing scripts; remove them before automated slicing")
        nozzles=cfg.get("nozzle_diameter",[])
        if not nozzles or any(float(n)!=.4 for n in nozzles):
            raise ValueError("This installation is validated for the factory 0.4 mm U1 only")
        return cfg

def validate_changes(changes: dict, cfg: dict):
    if not isinstance(changes,dict): raise ValueError("changes must be an object")
    result={}
    for key,val in changes.items():
        if key in BOOLEANS:
            if val not in (True,False,0,1,"0","1"): raise ValueError(f"{key} must be boolean")
            result[key]="1" if val in (True,1,"1") else "0"
        elif key in ENUMS:
            if val not in ENUMS[key]: raise ValueError(f"{key}: choose from {sorted(ENUMS[key])}")
            result[key]=val
        elif key in NUMBERS:
            n=float(str(val).rstrip("%"))
            lo,hi=NUMBERS[key]
            if not math.isfinite(n) or not lo<=n<=hi: raise ValueError(f"{key} must be between {lo} and {hi}")
            if key in INTEGER_KEYS and not n.is_integer(): raise ValueError(f"{key} must be an integer")
            result[key]=f"{n:g}"+("%" if key in {"sparse_infill_density","seam_gap"} else "")
        else: raise ValueError(f"Unsupported process key {key!r}; call u1_setting_options")
    merged=cfg|result
    count=len(merged.get("filament_settings_id",[]))
    for key in ("support_filament","support_interface_filament"):
        if int(merged.get(key,0))>count: raise ValueError(f"{key} refers to an unloaded filament")
    if float(merged.get("support_top_z_distance",.2))==0 and merged.get("enable_support")=="1":
        slot=int(merged.get("support_interface_filament",0))
        materials=merged.get("filament_type",[])
        pair={str(materials[0]).upper(), str(materials[slot-1]).upper()} if slot and len(materials)>=slot else set()
        if not slot or not (pair in ({"PLA","PETG"},{"PLA","TPU"}) or str(materials[slot-1]).upper() in {"PVA","BVOH","SUPPORT"}):
            raise ValueError("Zero support gap needs an explicitly assigned, compatible support interface filament")
    return result

def new_run():
    run=RUNS / uuid.uuid4().hex[:12]
    run.mkdir(parents=True)
    return run

def write_project_copy(source, dest, changes):
    cfg=read_project(source)
    validated=validate_changes(changes,cfg)
    cfg.update(validated)
    with zipfile.ZipFile(source) as zi,zipfile.ZipFile(dest,"w",zipfile.ZIP_DEFLATED) as zo:
        for info in zi.infolist():
            if info.filename.endswith((".gcode",".md5")) or info.filename=="Metadata/slice_info.config": continue
            data=json.dumps(cfg,indent=2).encode() if info.filename=="Metadata/project_settings.config" else zi.read(info.filename)
            zo.writestr(info,data)
    return validated

def rewrite_entries(source, dest, replacements):
    with zipfile.ZipFile(source) as zi,zipfile.ZipFile(dest,"w",zipfile.ZIP_DEFLATED) as zo:
        for info in zi.infolist():
            if info.filename.endswith((".gcode",".md5")) or info.filename=="Metadata/slice_info.config": continue
            zo.writestr(info,replacements.pop(info.filename,zi.read(info.filename)))
        for name,data in replacements.items(): zo.writestr(name,data)

def analyze(path):
    text=path.read_text(encoding="utf-8",errors="replace")
    matches=re.findall(r"^;\s*(\w+)\s*=\s*(.*)$",text,re.M)
    config={k:v.strip() for k,v in matches}
    def metric(label):
        found=re.search(r"^; "+re.escape(label)+r"\s*=\s*(.+)$",text,re.M)
        return found.group(1).strip() if found else None
    weight=metric("filament used [g]")
    masses=[float(x) for x in re.findall(r"\d+(?:\.\d+)?",weight or "")]
    duration=metric("estimated printing time (normal mode)")
    seconds=sum(float(n)*{"d":86400,"h":3600,"m":60,"s":1}[u] for n,u in re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])",duration or "")) or None
    tools=sorted(set(int(x) for x in re.findall(r"^T(\d+)\b",text,re.M)))
    features={}
    role="unknown"
    relative_e=True
    last_e=0.0
    for line in text.splitlines():
        if line.startswith("; FEATURE: "): role=line[11:].strip()
        elif line.startswith(";TYPE:"): role=line[6:].strip()
        command=line.split(";",1)[0].strip()
        if command=="M83": relative_e=True
        elif command=="M82": relative_e=False
        elif re.match(r"G(?:92|0?[123])\s",command):
            value=re.search(r"\bE\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))",command)
            if value:
                e=float(value.group(1))
                delta=e if relative_e else e-last_e
                last_e=e
                if not command.startswith("G92") and delta>0 and re.search(r"\b[XY]\s*[+\-.\d]",command):
                    features[role]=features.get(role,0)+1
    skippable=sorted(set(re.findall(r'^EXCLUDE_OBJECT_DEFINE\s+NAME=([^\s]+)',text,re.M)))
    return {"skippable_object_count":len(skippable),"skippable_objects":skippable,"gcode":str(path),"file_size":path.stat().st_size,"estimated_print_time":duration,"estimated_seconds":seconds,"filament_grams_per_slot":masses,"total_filament_grams":round(sum(masses),3) if masses else None,"tools_zero_based":tools,"tool_command_count":len(re.findall(r"^T\d+\b",text,re.M)),"extrusion_moves_by_feature":features,"effective_settings":{k:config.get(k) for k in sorted(NUMBERS.keys()|BOOLEANS|ENUMS.keys()) if k in config},"printer_model":config.get("printer_model"),"filament_types":config.get("filament_type"),"notes":["Time and material are slicer estimates; finish and support removability need physical feedback."]}

def slice_copy(path,run):
    # A saved project already owns its placement and plates. Orca's automatic
    # rearrangement can move a dense layout into the native prime tower.
    cmd=[str(BIN),"--debug","3","--arrange","0","--outputdir",str(run),"--slice","0",str(path)]
    dump(run/"command.json",cmd)
    try:
        proc=subprocess.run(cmd,capture_output=True,encoding="utf-8",errors="replace",timeout=600,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    except subprocess.TimeoutExpired as exc:
        dump(run/"result.json",{"status":"error","error":"Slice exceeded 600 seconds","project":str(path)})
        raise ValueError("Slice exceeded 600 seconds; no output is approved") from exc
    (run/"stdout.log").write_text(proc.stdout,encoding="utf-8")
    (run/"stderr.log").write_text(proc.stderr,encoding="utf-8")
    files=sorted(run.glob("*.gcode"),key=lambda p:(int(re.search(r'plate_(\d+)',p.name).group(1)) if re.search(r'plate_(\d+)',p.name) else 0,p.name))
    result={"status":"ok" if proc.returncode==0 and files else "error","returncode":proc.returncode,"run_id":run.name,"project":str(path),"plates":[analyze(p) for p in files],"review_required":True}
    if result["status"]=="error": result["log_tail"]=(proc.stdout+proc.stderr)[-5000:]
    cfg=read_project(path)
    for plate in result["plates"]:
        if plate["printer_model"]!="Snapmaker U1": result.update(status="error",error="Output does not identify Snapmaker U1")
        slot_count=len(cfg.get("filament_settings_id",[]))
        if any(t>=slot_count or t>3 for t in plate["tools_zero_based"]): result.update(status="error",error="Unexpected tool assignment")
    dump(run/"result.json",result)
    return result

@mcp.tool()
def u1_preferences() -> dict:
    """Read the owner's hardware, material uncertainties and quality priorities."""
    return json.loads((ROOT/"printer_preferences.json").read_text(encoding="utf-8"))

@mcp.tool()
def u1_health() -> dict:
    """Check installed executable and the evidence from real validation, without opening a GUI."""
    evidence=ROOT/"validation/bridge-results.json"
    test=json.loads(evidence.read_text()) if evidence.exists() else {}
    current=sha(BIN) if BIN.exists() else None
    return {"binary":str(BIN),"exists":BIN.exists(),"profile_directory":str(PROFILES),"validated_binary_unchanged":test.get("binary_sha256")==current if test else False,"validation":test,"control_mode":"saved project copies + native CLI; no live GUI control","full_spectrum_painting":"GUI preparation/review required; not validated for automated creation"}

@mcp.tool()
def u1_list_files() -> list[dict]:
    """List STL and saved U1 3MF inputs in models/."""
    return [{"path":str(p.relative_to(MODELS)),"bytes":p.stat().st_size} for p in MODELS.rglob("*") if p.is_file() and p.suffix.lower() in {".stl",".3mf"}]

@mcp.tool()
def u1_list_profiles(kind: str="process", query: str="") -> list[dict]:
    """List installed U1 machine/process/filament presets; use exact returned names."""
    store=ProfileStore([PROFILES])
    return [{"name":p.name,"inherits":p.inherits} for p in store.list_profiles(kind)[kind] if query.lower() in p.name.lower()]

@mcp.tool()
def u1_get_profile(name: str, kind: str) -> dict:
    """Resolve factory profile inheritance and return its actual settings."""
    return ProfileStore([PROFILES]).resolve_profile(name,kind)

@mcp.tool()
def u1_setting_options() -> dict:
    """Show editable process settings and limits. Native slicer validates enum compatibility."""
    return {"numbers":NUMBERS,"integer_keys":sorted(INTEGER_KEYS),"booleans":sorted(BOOLEANS),"enums":{k:sorted(v) for k,v in ENUMS.items()}}

@mcp.tool()
def u1_print_strategy(model:str,filament:str|None=None,purpose:str='display',orientation:str='auto') -> dict:
    """Read geometry and saved overrides, rank STL orientations and explain brim/support decisions. Never slices or prints. Native multicolor layouts remain aligned. Scores are hypotheses, not physical quality ratings."""
    if purpose not in {'display','functional','fit'} or orientation not in {'auto','preserve'}:raise ValueError('Choose a supported purpose and orientation policy')
    path=local_file(model,{'.stl','.3mf'})
    from printflow.common import DATA,read_json,save_json
    stat=path.stat();key=hashlib.sha256(f'{path}|{stat.st_size}|{stat.st_mtime_ns}|{filament}|{purpose}|{orientation}|{print_strategy.VERSION}'.encode()).hexdigest()
    cache=DATA/'print-strategies'/f'{key}.json'
    cached=read_json(cache,None)
    if cached:return cached
    if path.suffix.lower()=='.3mf':
        read_project(path)
        plan=print_strategy.project_plan(path)
    else:
        if not filament:raise ValueError('Choose the actual native filament profile before planning this STL')
        profile=standard_filament(ProfileStore([PROFILES]).resolve_profile(filament,'filament'))
        material=(profile.get('filament_type') or ['Unknown'])[0]
        plan=print_strategy.stl_plan(_stl_triangles(path),material,purpose,orientation)
    result=print_strategy.finish_plan(plan);save_json(cache,result);return result

@mcp.tool()
def u1_inspect_project(project: str) -> dict:
    """Read U1 settings, per-object overrides, painted-color presence, slots and mesh hashes."""
    path=local_file(project,{".3mf"})
    cfg=read_project(path)
    with zipfile.ZipFile(path) as z:
        meshes={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.endswith(".model")}
        modelcfg=z.read("Metadata/model_settings.config").decode() if "Metadata/model_settings.config" in z.namelist() else ""
        painting=any(b"paint_color" in z.read(n) or b"mmu_segmentation" in z.read(n) for n in meshes)
    return {"path":str(path),"printer_model":cfg["printer_model"],"nozzle_diameter":cfg.get("nozzle_diameter"),"filament_profiles":cfg.get("filament_settings_id"),"filament_types":cfg.get("filament_type"),"filament_colors":cfg.get("filament_colour"),"filament_map":cfg.get("filament_map"),"painted_facets_present":painting,"mesh_sha256":meshes,"object_settings_xml":modelcfg[:24000],"process":{k:cfg.get(k) for k in sorted(NUMBERS.keys()|BOOLEANS|ENUMS.keys()) if k in cfg},"warning":"Per-object/plate overrides can take precedence; inspect effective G-code settings and preview."}

@mcp.tool()
def u1_inspect_stl(model: str) -> dict:
    """Estimate STL dimensions, contact and overhangs. Geometry metrics are heuristic."""
    path=local_file(model,{".stl"})
    if not path.is_relative_to(MODELS): raise ValueError("STL inspections require a model under models/")
    return u1_mesh_printability(str(path.relative_to(MODELS)))

@mcp.tool()
def u1_prepare_stl(model: str, filament: str, process: str="0.12mm Standard @Snapmaker U1 (0.4 nozzle)", rotation:list[float]|None=None) -> dict:
    """Create an editable, centered, single-color U1 3MF using explicit native profiles. No slice or GUI export."""
    path=local_file(model,{".stl"})
    profiles=ProfileStore([PROFILES]).validate_selection(ProfileSelection("Snapmaker U1 (0.4 nozzle)",process,filament,.4))
    profiles["filament"]=standard_filament(profiles["filament"])
    cfg={}
    for p in (profiles["machine"],profiles["process"],profiles["filament"]): cfg.update({k:v for k,v in p.items() if k not in {"name","type","from","version","instantiation"}})
    cfg.update(printer_settings_id=profiles["machine"]["name"],print_settings_id=process,filament_settings_id=[filament],filament_map=["1"],curr_bed_type="Textured PEI Plate")
    triangles=_stl_triangles(path)
    if not triangles: raise ValueError("STL contains no triangles")
    if rotation is not None:
        r=print_strategy.validate_rotation(rotation)
        import numpy as np
        triangles=[tuple(tuple(v) for v in tri) for tri in np.asarray(triangles)@r]
    points=[v for tri in triangles for v in tri]
    low=[min(v[i] for v in points) for i in range(3)]
    high=[max(v[i] for v in points) for i in range(3)]
    if any(not math.isfinite(n) for v in points for n in v) or any(high[i]-low[i]>270 for i in range(3)): raise ValueError("Model exceeds U1 volume or contains nonfinite coordinates")
    offset=[135.5-(low[0]+high[0])/2,136-(low[1]+high[1])/2,-low[2]]
    root=ET.Element(tag("model"),unit="millimeter")
    ET.SubElement(root,tag("metadata"),name="Application").text="OrcaSlicer-2.4.0"
    ET.SubElement(root,tag("metadata"),name="BambuStudio:3mfVersion").text="1"
    resources=ET.SubElement(root,tag("resources"))
    mesh=ET.SubElement(ET.SubElement(resources,tag("object"),id="1",type="model"),tag("mesh"))
    verts=ET.SubElement(mesh,tag("vertices")); tris=ET.SubElement(mesh,tag("triangles"))
    indices={}
    for tri in triangles:
        face=[]
        for v in tri:
            if v not in indices:
                indices[v]=len(indices)
                ET.SubElement(verts,tag("vertex"),**{axis:f"{v[i]+offset[i]:.9g}" for i,axis in enumerate("xyz")})
            face.append(indices[v])
        ET.SubElement(tris,tag("triangle"),**{f"v{i+1}":str(n) for i,n in enumerate(face)})
    ET.SubElement(ET.SubElement(root,tag("build")),tag("item"),objectid="1",printable="1")
    run=new_run(); dest=run/"prepared.3mf"
    with zipfile.ZipFile(dest,"w",zipfile.ZIP_DEFLATED) as zo:
        zo.writestr("[Content_Types].xml",CONTENT_TYPES)
        zo.writestr("_rels/.rels",RELATIONSHIPS)
        zo.writestr("3D/3dmodel.model",ET.tostring(root,encoding="utf-8",xml_declaration=True))
        zo.writestr("Metadata/project_settings.config",json.dumps(cfg))
        zo.writestr("Metadata/model_settings.config",'<config><object id="1"><metadata key="extruder" value="1"/></object></config>')
    return {"project":str(dest),"source":str(path),"filament":filament,"process":process,"placement_translation":offset,"orientation_rotation":rotation,"note":"Single-color STL import. Use saved native 3MF to preserve painting and multicolor assemblies."}

@mcp.tool()
def u1_prepare_assembly(manifest: str, filament: str) -> dict:
    """Create a native U1 multicolor project from bounded, shared-origin CAD solids. Never starts printing."""
    source=local_file(manifest,{".json"})
    if source.name!="manifest.json": raise ValueError("Use a generated design manifest")
    assembly=json.loads(source.read_text(encoding="utf-8")).get("assembly",{})
    parts=assembly.get("parts",[]); colors=assembly.get("colors",[])
    if not 1<=len(parts)<=16 or not 1<=len(colors)<=4: raise ValueError("Invalid assembly part/color count")
    combined=source.parent/str(assembly.get("source",""))
    if combined.parent!=source.parent or combined.suffix.lower()!=".stl": raise ValueError("Invalid assembly source")
    base=u1_prepare_stl(str(combined),filament)
    materials=u1_set_filament_slots(base["project"],[filament]*len(colors),colors)
    cfg=read_project(materials["project"])
    root=ET.Element(tag("model"),unit="millimeter")
    ET.SubElement(root,tag("metadata"),name="Application").text="OrcaSlicer-2.4.0"
    ET.SubElement(root,tag("metadata"),name="BambuStudio:3mfVersion").text="1"
    resources=ET.SubElement(root,tag("resources")); modelcfg=ET.Element("config")
    parent_id=len(parts)+1; parent=ET.SubElement(modelcfg,"object",id=str(parent_id))
    ET.SubElement(parent,"metadata",key="name",value=str(assembly.get("name","Generated assembly")))
    ET.SubElement(parent,"metadata",key="extruder",value="1")
    offset=base["placement_translation"]
    for index,part in enumerate(parts,1):
        path=source.parent/str(part["file"])
        if path.parent!=source.parent or path.suffix.lower()!=".stl" or not part.get("preserve_assembly_origin"):
            raise ValueError("Assembly parts must be local shared-origin STL files")
        path=local_file(str(path),{".stl"})
        slot=int(part["planned_tool"])+1
        if slot<1 or slot>len(colors):raise ValueError("Invalid part filament slot")
        obj=ET.SubElement(resources,tag("object"),id=str(index),type="model")
        mesh=ET.SubElement(obj,tag("mesh")); verts=ET.SubElement(mesh,tag("vertices")); tris=ET.SubElement(mesh,tag("triangles")); indices={}
        for triangle in _stl_triangles(path):
            face=[]
            for vertex in triangle:
                if not all(math.isfinite(v) for v in vertex):raise ValueError("Nonfinite assembly coordinate")
                if vertex not in indices:
                    indices[vertex]=len(indices)
                    ET.SubElement(verts,tag("vertex"),**{axis:f"{vertex[i]+offset[i]:.9g}" for i,axis in enumerate("xyz")})
                face.append(indices[vertex])
            ET.SubElement(tris,tag("triangle"),**{f"v{i+1}":str(n) for i,n in enumerate(face)})
        volume=ET.SubElement(parent,"part",id=str(index),subtype="normal_part")
        ET.SubElement(volume,"metadata",key="name",value=str(part["name"]))
        ET.SubElement(volume,"metadata",key="extruder",value=str(slot))
    components=ET.SubElement(ET.SubElement(resources,tag("object"),id=str(parent_id),type="model"),tag("components"))
    for index in range(1,len(parts)+1):ET.SubElement(components,tag("component"),objectid=str(index))
    ET.SubElement(ET.SubElement(root,tag("build")),tag("item"),objectid=str(parent_id),printable="1")
    # Keep the official U1 prime-tower/temperature/machine defaults intact.
    run=new_run();dest=run/"assembly.3mf"
    with zipfile.ZipFile(dest,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",CONTENT_TYPES);z.writestr("_rels/.rels",RELATIONSHIPS)
        z.writestr("3D/3dmodel.model",ET.tostring(root,encoding="utf-8",xml_declaration=True))
        z.writestr("Metadata/project_settings.config",json.dumps(cfg))
        z.writestr("Metadata/model_settings.config",ET.tostring(modelcfg,encoding="utf-8",xml_declaration=True))
    return {"project":str(dest),"parts":len(parts),"colors":colors,"note":"Review object parts, tool usage and emitted G-code before printing."}

@mcp.tool()
def u1_apply_filament_calibration(project: str, expected_filament: str, values: dict) -> dict:
    """Apply bounded measured temperature/flow values to a single-slot copy. Never overrides firmware PA or machine G-code."""
    from printflow.calibration import bounded, FILAMENT
    source=local_file(project,{'.3mf'});cfg=read_project(source)
    if cfg.get('filament_settings_id')!=[expected_filament]:raise ValueError('Calibration requires a single-slot project with the exact tested filament profile')
    checked=bounded(values,FILAMENT)
    low=float(cfg.get('nozzle_temperature_range_low',[170])[0]);high=float(cfg.get('nozzle_temperature_range_high',[300])[0])
    for key in ('nozzle_temperature','nozzle_temperature_initial_layer'):
        if key in checked and not low<=checked[key]<=high:raise ValueError(f'Temperature must remain within the native filament range {low:g}–{high:g} °C')
    for key,value in checked.items():
        if key not in cfg or not isinstance(cfg[key],list) or len(cfg[key])!=1:raise ValueError(f'The installed profile does not support {key}')
        cfg[key]=[str(value)]
    run=new_run();dest=run/'calibrated.3mf'
    rewrite_entries(source,dest,{'Metadata/project_settings.config':json.dumps(cfg).encode()})
    return {'project':str(dest),'applied':checked,'note':'Measured single-filament overrides. Official machine settings and pressure advance remain unchanged.'}

@mcp.tool()
def u1_slice_project(project: str, changes: dict | None=None) -> dict:
    """Copy a saved U1 3MF, apply bounded process edits, preserve meshes/painting/tools, slice with installed Snapmaker Orca."""
    source=local_file(project,{".3mf"})
    run=new_run(); dest=run/"project.3mf"
    applied=write_project_copy(source,dest,changes or {})
    dump(run/"request.json",{"source":str(source),"source_sha256":sha(source),"changes":applied})
    return slice_copy(dest,run)

@mcp.tool()
def u1_set_filament_slots(project: str, filaments: list[str], colors: list[str]) -> dict:
    """Replace 1-4 filament slots with explicit native U1 profiles/colors in a project copy. Confirm real loaded spools before printing."""
    source=local_file(project,{".3mf"}); cfg=read_project(source)
    count=len(filaments)
    if not 1<=count<=4 or len(colors)!=count: raise ValueError("Provide 1-4 profiles and one #RRGGBB color per slot")
    if any(not re.fullmatch(r"#[0-9A-Fa-f]{6}",c) for c in colors): raise ValueError("Colors must use #RRGGBB")
    old_count=len(cfg.get("filament_settings_id",[]))
    if count<old_count: raise ValueError("Slot removal could invalidate painted facets; preserve the slot count or start from a single-color project")
    store=ProfileStore([PROFILES])
    profiles=[standard_filament(store.resolve_profile(n,"filament")) for n in filaments]
    for p in profiles:
        # Compatibility is checked against the native process and factory machine.
        from snapmaker_u1_mcp.profiles import validate_profiles
        validate_profiles(store.resolve_profile("Snapmaker U1 (0.4 nozzle)","machine"),cfg,p,.4)
        if "0.6 nozzle" in p["name"] or "0.8 nozzle" in p["name"] or "0.2 nozzle" in p["name"]: raise ValueError("Use 0.4 mm filament profiles")
    excluded={"compatible_printers","compatible_prints","bed_type"}
    keys={k for p in profiles for k,v in p.items() if isinstance(v,list) and k not in excluded}
    for key in keys:
        if any(not isinstance(p.get(key),list) or len(p[key])!=1 for p in profiles):
            raise ValueError(f"Unsupported per-slot array {key!r}; no profile has been written")
        cfg[key]=[p[key][0] for p in profiles]
    cfg.update(filament_settings_id=filaments,filament_colour=colors,filament_map=[str(i+1) for i in range(count)])
    run=new_run(); dest=run/"materials.3mf"
    rewrite_entries(source,dest,{"Metadata/project_settings.config":json.dumps(cfg).encode()})
    return {"project":str(dest),"filaments":filaments,"colors":colors,"note":"Object/facet assignments are preserved. Confirm each physical tool's loaded material. Existing calibration overrides are replaced with the selected factory filament presets."}

@mcp.tool()
def u1_assign_object_filament(project: str, object_id: int, filament_slot: int) -> dict:
    """Assign a whole object and its parts to an existing 1-based filament slot in a copy. Painted facets may override the base assignment."""
    source=local_file(project,{".3mf"}); cfg=read_project(source)
    if not 1<=filament_slot<=len(cfg.get("filament_settings_id",[])): raise ValueError("Slot is not loaded")
    with zipfile.ZipFile(source) as z:
        xml=ET.fromstring(z.read("Metadata/model_settings.config"))
    obj=xml.find(f"object[@id='{int(object_id)}']")
    if obj is None: raise ValueError("Object ID was not found; inspect the project first")
    for element in [obj,*obj.findall("part")]:
        meta=element.find("metadata[@key='extruder']")
        if meta is None: meta=ET.SubElement(element,"metadata",key="extruder")
        meta.set("value",str(filament_slot))
    run=new_run(); dest=run/"assigned.3mf"
    rewrite_entries(source,dest,{"Metadata/model_settings.config":ET.tostring(xml,encoding="utf-8",xml_declaration=True)})
    return {"project":str(dest),"object_id":object_id,"filament_slot":filament_slot,"note":"Painted facets are preserved and can override object assignment; review native preview."}

@mcp.tool()
def u1_compare_variants(project: str, variants: list[dict]) -> dict:
    """Slice 2-4 named {name, changes} variants from the same original project. Return quality-neutral numeric comparisons."""
    if not 2<=len(variants)<=4: raise ValueError("Compare 2-4 variants")
    results=[]
    for variant in variants:
        result=u1_slice_project(project,variant.get("changes",{}))
        results.append({"name":variant.get("name","variant"),**result})
    return {"variants":results,"selection_policy":"Maximum finish/easy support removal first. Time/material alone do not measure surface quality or support removability. Review warning logs, overrides and toolpaths before choosing."}

@mcp.tool()
def u1_quality_plan(project: str) -> dict:
    """Suggest comparison candidates for this owner's priority; do not blindly enable supports or reduce priming."""
    cfg=read_project(local_file(project,{".3mf"}))
    strategy=u1_print_strategy(project)
    height=float(cfg.get('layer_height') or .12)
    alternate=.16 if height<=.12 else .12
    variants=[{"name":"saved_native_baseline","changes":{}},{"name":f"layer_comparison_{alternate:.2f}","changes":{"layer_height":alternate}}]
    return {"variants":variants,"print_strategy":strategy,"support_policy":"Minimize supports by orientation first; enable only for actual overhangs. Increased support gap eases removal but can roughen undersides. Separate-material interface needs confirmed compatibility and a physical test.","multicolor_policy":"Preserve painting, tool mapping and priming by default. Compare tower reductions only after a successful baseline. Do not use infill flushing for translucent/light outer shells without checking show-through.","material_status":u1_preferences()["material"],"quality_is_unmeasured":True,"next":"u1_compare_variants, preview in Snapmaker Orca, then record print outcome"}

@mcp.tool()
def u1_analyze_gcode(gcode: str) -> dict:
    """Read actual emitted settings, tools, time, mass and feature moves from generated G-code."""
    return analyze(local_file(gcode,{".gcode"}))

@mcp.tool()
def u1_record_outcome(run_id: str, finish: int, support_removal: int, notes: str) -> dict:
    """Store owner's physical-print feedback. Ratings 1=poor, 5=excellent; do not fabricate results."""
    if not re.fullmatch(r"[a-f0-9]{12}",run_id): raise ValueError("Invalid run ID")
    run=RUNS/run_id
    if not (run/"result.json").exists(): raise ValueError("Unknown run")
    if not 1<=finish<=5 or not 1<=support_removal<=5: raise ValueError("Ratings must be 1-5")
    record={"run_id":run_id,"finish":finish,"support_removal":support_removal,"notes":notes}
    dump(run/"physical_feedback.json",record)
    return record

@mcp.tool()
def u1_recent_results(limit: int=10) -> list[dict]:
    """Read previous slicer results and physical feedback to improve future choices."""
    if not 1<=limit<=50: raise ValueError("limit must be 1-50")
    files=sorted(RUNS.glob("*/result.json"),key=lambda p:p.stat().st_mtime,reverse=True)[:limit]
    return [{"result":json.loads(p.read_text()),"physical_feedback":json.loads((p.parent/"physical_feedback.json").read_text()) if (p.parent/"physical_feedback.json").exists() else None} for p in files]

if __name__=="__main__":
    MODELS.mkdir(exist_ok=True); RUNS.mkdir(exist_ok=True)
    mcp.run(transport="stdio")
