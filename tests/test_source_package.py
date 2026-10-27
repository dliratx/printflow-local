"""Publication must remain usable without leaking a developer's private state."""
import hashlib
import importlib.util
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def packager():
    spec=importlib.util.spec_from_file_location('source_packager',ROOT/'tools/package-source.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def test_public_archive_contains_required_assets_and_no_runtime_data(tmp_path,monkeypatch):
    m=packager();monkeypatch.setattr(m,'OUTPUT',tmp_path/'source.zip')
    m.package()
    with zipfile.ZipFile(m.OUTPUT) as archive:
        names=set(archive.namelist())
        assert 'printflow-local/README.md' in names
        assert 'printflow-local/docs/WORKFLOWS.md' in names
        raw=archive.read('printflow-local/models/calibration-assets/3DBenchy.stl')
        assert hashlib.sha256(raw).hexdigest()=='6ab57f1c3f8e86bc3cbd302c6fa6270acf06277c6335454e922419c25d42e97e'
        assert 'printflow-local/vendor/snapmaker-u1-mcp/LICENSE' in names
        assert not any('/.runtime/' in name or '/runs/' in name or '/models/library/' in name for name in names)

def test_private_files_and_nested_secrets_are_excluded():
    m=packager()
    for name in ['.env','.env.production','AGENTS.md','LEEME.md','models/private.stl',
                 'models/calibration-assets/private.stl','models/library/model.3mf',
                 '.runtime/bridge-token','backups/state.zip','tools/.env.local',
                 'tools/output.log','web/node_modules/private.js','printflow/__pycache__/file.pyc',
                 'vendor/snapmaker-u1-mcp/.git/config']:
        assert not m.allowed(ROOT/name),name
    assert m.allowed(ROOT/'.env.example')
    assert not m.allowed(ROOT.parent/'outside.py')
