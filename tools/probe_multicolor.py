import json
import subprocess
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_installation import ROOT, cube

sys.stdout.reconfigure(encoding="utf-8")
smoke = json.loads((ROOT / "validation/smoke.json").read_text())
p = Path(smoke["run_dir"]) / "profiles"
cube(ROOT / "models/validation/cube2.stl", x0=15)
out = ROOT / "validation/multicolor-probe"
out.mkdir(exist_ok=True)
cmd = [r"C:\Program Files\Snapmaker_Orca\snapmaker-orca.exe", "--debug", "3", "--load-settings", str(p/"machine.json"), "--load-settings", str(p/"process.json"), "--load-filaments", f"{p/'filament.json'};{p/'filament.json'}", "--outputdir", str(out), "--export-3mf", "two-color.3mf", str(ROOT / "models/validation/cube.stl"), str(ROOT / "models/validation/cube2.stl")]
r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
(out / "export.log").write_text(r.stdout+r.stderr, encoding="utf-8")
print("returncode", r.returncode)
print(r.stdout[-2000:])
for file in out.glob("*.3mf"):
    with zipfile.ZipFile(file) as z:
        print("ZIP", z.namelist())
        for name in ["Metadata/project_settings.config", "Metadata/model_settings.config", "3D/3dmodel.model"]:
            if name in z.namelist():
                data = z.read(name).decode("utf-8")
                (out / (name.split("/")[-1]+".txt")).write_text(data, encoding="utf-8")
                if "project_settings" in name:
                    d = json.loads(data)
                    print(json.dumps({k:v for k,v in d.items() if any(s in k for s in ["filament", "extruder", "printer_model", "printer_settings", "nozzle_diameter"])}, indent=2))
                else:
                    print(data[:4000])
