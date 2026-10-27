"""Package allowlisted source and the attributed benchmark, never private state."""
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"dist/printflow-local-source.zip"
ROOT_FILES={"README.md","INSTALL.md","MAINTENANCE.md","THIRD_PARTY.md","CONTRIBUTING.md","SECURITY.md","LICENSE","Dockerfile","compose.yaml","install.ps1","install.sh",".dockerignore",".gitignore",".gitattributes",".env.example","printer_preferences.json","requirements-design.txt","requirements-web.txt","requirements-lock.txt","u1_server.py"}
FOLDERS={"printflow","web","tests","tools","services","deploy","docs",".github","vendor/snapmaker-u1-mcp"}
ASSETS={"models/calibration-assets/3DBenchy.stl","models/calibration-assets/source.json"}
EXCLUDED_PARTS={".git","__pycache__",".pytest_cache",".venv",".venv-design",".venv-image3d",".runtime","node_modules"}

def allowed(path):
    path=Path(path)
    try: rel=path.relative_to(ROOT)
    except ValueError: return False
    # Never dereference symlinked source or directories into private locations.
    if path.is_symlink() or any(p.is_symlink() for p in path.parents if p!=ROOT and ROOT in p.parents): return False
    if any(part in EXCLUDED_PARTS or part.endswith('.egg-info') for part in rel.parts): return False
    if path.name=='.env' or (path.name.startswith('.env.') and path.name!='.env.example'): return False
    if path.suffix in {".pyc",".log",".pid",".zip"}: return False
    if rel.as_posix() in ASSETS: return True
    if len(rel.parts)==1: return rel.name in ROOT_FILES
    return any(rel.is_relative_to(Path(folder)) for folder in FOLDERS)

def source_files():
    candidates={ROOT/name for name in ROOT_FILES|ASSETS}
    for directory in FOLDERS:
        candidates.update(p for p in (ROOT/directory).rglob('*') if p.is_file())
    return sorted(p for p in candidates if p.is_file() and allowed(p))

def package():
    missing=[name for name in ROOT_FILES|ASSETS if not (ROOT/name).is_file()]
    if missing: raise ValueError('Required source files are missing: '+', '.join(sorted(missing)))
    OUTPUT.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(OUTPUT,"w",zipfile.ZIP_DEFLATED) as archive:
        for path in source_files(): archive.write(path,"printflow-local/"+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(OUTPUT) as archive:
        names=[name.removeprefix('printflow-local/') for name in archive.namelist()]
        assert all(allowed(ROOT/name) for name in names)
        assert all(not name.startswith('models/') or name in ASSETS for name in names)
        print(f"Packaged {len(names)} source files: {OUTPUT}")
    return OUTPUT

if __name__=="__main__": package()
