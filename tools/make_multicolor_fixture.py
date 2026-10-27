"""Create a tiny two-tool 3MF fixture without using GPU thumbnail export."""
from pathlib import Path
import json
import zipfile
import xml.etree.ElementTree as ET
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_installation import ROOT

NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
ET.register_namespace("", NS)
def tag(name): return f"{{{NS}}}{name}"

def make_fixture(count=2):
    smoke = json.loads((ROOT / "validation/smoke.json").read_text())
    p = Path(smoke["run_dir"]) / "profiles"
    machine, process, filament = [json.loads((p / f"{name}.json").read_text()) for name in ["machine","process","filament"]]
    cfg = {}
    for profile in [machine, process, filament]:
        cfg.update({k:v for k,v in profile.items() if k not in {"name","type","from","version","instantiation"}})
    for key,value in filament.items():
        if isinstance(value,list) and len(value)==1:
            cfg[key]=value*count
    cfg.update(printer_settings_id=machine["name"], print_settings_id=process["name"], filament_settings_id=[filament["name"]]*count, filament_colour=["#FF0000","#0000FF","#00FF00","#FFFFFF"][:count], filament_map=[str(i+1) for i in range(count)], curr_bed_type="Textured PEI Plate", enable_prime_tower="1")
    model=ET.Element(tag("model"), {"unit":"millimeter"})
    ET.SubElement(model,tag("metadata"),name="Application").text="OrcaSlicer-2.4.0"
    ET.SubElement(model,tag("metadata"),name="BambuStudio:3mfVersion").text="1"
    resources=ET.SubElement(model,tag("resources"))
    build=ET.SubElement(model,tag("build"))
    settings=ET.Element("config")
    faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    for object_id,x0 in [(i+1,50+i*20) for i in range(count)]:
        obj=ET.SubElement(resources,tag("object"),id=str(object_id),type="model")
        mesh=ET.SubElement(obj,tag("mesh"))
        vertices=ET.SubElement(mesh,tag("vertices"))
        for x,y,z in [(0,0,0),(10,0,0),(10,10,0),(0,10,0),(0,0,10),(10,0,10),(10,10,10),(0,10,10)]:
            ET.SubElement(vertices,tag("vertex"),x=str(x+x0),y=str(y+50),z=str(z))
        triangles=ET.SubElement(mesh,tag("triangles"))
        for a,b,c in faces:
            ET.SubElement(triangles,tag("triangle"),v1=str(a),v2=str(b),v3=str(c))
        ET.SubElement(build,tag("item"),objectid=str(object_id),printable="1")
        objcfg=ET.SubElement(settings,"object",id=str(object_id))
        ET.SubElement(objcfg,"metadata",key="name",value=f"Tool {object_id} cube")
        ET.SubElement(objcfg,"metadata",key="extruder",value=str(object_id))
        part=ET.SubElement(objcfg,"part",id=str(object_id),subtype="normal_part")
        ET.SubElement(part,"metadata",key="name",value=f"Tool {object_id} cube")
        ET.SubElement(part,"metadata",key="extruder",value=str(object_id))
    target=ROOT / ("models/validation/two-color.3mf" if count==2 else "models/validation/four-color.3mf")
    with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model",ET.tostring(model,encoding="utf-8",xml_declaration=True))
        z.writestr("Metadata/model_settings.config",ET.tostring(settings,encoding="utf-8",xml_declaration=True))
        z.writestr("Metadata/project_settings.config",json.dumps(cfg))
    return target

if __name__=="__main__":
    import subprocess
    sys.stdout.reconfigure(encoding="utf-8")
    path=make_fixture()
    out=ROOT / "validation/multicolor-native"
    out.mkdir(exist_ok=True)
    cmd=[r"C:\Program Files\Snapmaker_Orca\snapmaker-orca.exe","--debug","3","--outputdir",str(out),"--slice","0",str(path)]
    r=subprocess.run(cmd,capture_output=True,encoding="utf-8",errors="replace",timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
    (out / "slice.log").write_text(r.stdout+r.stderr,encoding="utf-8")
    print("returncode",r.returncode)
    print(r.stdout[-2000:])
    import re
    for g in out.glob("*.gcode"):
        t=g.read_text(encoding="utf-8",errors="replace")
        print(g,"tools",sorted(set(re.findall(r"^T(\d+)\b",t,re.M))))
