"""Local, non-printing validation of the installed Snapmaker slicer."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor/snapmaker-u1-mcp/src"))
os.environ.update({
    "SNAPMAKER_ORCA_BIN": r"C:\Program Files\Snapmaker_Orca\snapmaker-orca.exe",
    "SNAPMAKER_PROFILE_DIR": r"C:\Program Files\Snapmaker_Orca\resources\profiles\Snapmaker",
    "U1_MODEL_DIR": str(ROOT / "models"),
    "U1_OUTPUT_DIR": str(ROOT / "runs"),
    "SNAPMAKER_U1_MCP_HOME": str(ROOT / ".runtime"),
    "SNAPMAKER_ORCA_TIMEOUT": "90",
})
from snapmaker_u1_mcp.profiles import ProfileStore, ProfileSelection
from snapmaker_u1_mcp.slicer import u1_slice

def cube(path, x0=0, size=10):
    v = [(x0+x,y,z) for x,y,z in [(0,0,0),(size,0,0),(size,size,0),(0,size,0),(0,0,size),(size,0,size),(size,size,size),(0,size,size)]]
    faces = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    lines = ["solid cube"]
    for face in faces:
        lines += ["facet normal 0 0 0", "outer loop"] + ["vertex %g %g %g" % v[i] for i in face] + ["endloop", "endfacet"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines + ["endsolid cube"]), encoding="ascii")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    store = ProfileStore([Path(os.environ["SNAPMAKER_PROFILE_DIR"])])
    selection = ProfileSelection("Snapmaker U1 (0.4 nozzle)", "0.20mm Standard @Snapmaker U1 (0.4 nozzle)", "Snapmaker PLA Basic @U1", 0.4)
    profiles = store.validate_selection(selection)
    audit = {"profile_counts": {k:len(v) for k,v in store.list_profiles().items()}, "selection": {k:p.get("name") for k,p in profiles.items()}, "machine": {k:profiles["machine"].get(k) for k in ["printer_model","nozzle_diameter","printable_area","printable_height","printer_structure"]}, "support": {k:v for k,v in profiles["process"].items() if "support" in k}, "multicolor": {k:v for k,v in profiles["process"].items() if any(s in k for s in ["prime", "flush", "wipe", "color"])}}
    (ROOT / "validation").mkdir(exist_ok=True)
    (ROOT / "validation/installation.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps(audit, indent=2), flush=True)
    cube(ROOT / "models/validation/cube.stl")
    result = u1_slice("validation/cube.stl", selection.process_name, selection.filament_name, verbose=True)
    (ROOT / "validation/smoke.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
