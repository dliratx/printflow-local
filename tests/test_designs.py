import asyncio
import importlib.util
import json
from pathlib import Path
import zipfile
import pytest
from printflow.design_schema import U1, validate_request, material_advice


PRINTER = {"id": "test", "name": "U1", **U1}


def test_roadster_requires_explicit_three_color_assembly():
    with pytest.raises(ValueError, match="three colors"):
        validate_request({"template":"roadster_2026"},PRINTER)
    colors=["#080A0D","#E72F1D","#E2DEDB"]
    result=validate_request({"template":"roadster_2026","color_mode":"multi_tool","colors":colors},PRINTER)
    assert result["colors"]==colors


def test_printer_color_capabilities_are_not_interchangeable():
    with pytest.raises(ValueError, match="does not use AMS"):
        validate_request({"template": "table", "color_mode": "ams"}, PRINTER)
    with pytest.raises(ValueError, match="4 simultaneous"):
        validate_request({"template": "table", "color_mode": "multi_tool", "colors": ["#112233"]*5}, PRINTER)
    assert len(validate_request({"template": "table", "color_mode": "separate_parts", "colors": ["#112233"]*5}, PRINTER)["colors"]) == 5


def test_cad_rejects_nonfinite_parameters_and_invalid_wall_geometry():
    for value in (float("nan"), float("inf"), -1):
        with pytest.raises(ValueError): validate_request({"template": "box", "parameters": {"width": value}}, PRINTER)
    with pytest.raises(ValueError, match="usable interior"):
        validate_request({"template": "box", "parameters": {"width": 15, "wall": 12}}, PRINTER)
    with pytest.raises(ValueError, match="Unknown design parameter"):
        validate_request({"template": "box", "parameters": {"python": "print('not executed')"}}, PRINTER)


def test_material_advice_does_not_invent_loaded_inventory():
    request = validate_request({"template": "table", "usage": {"loaded": True}}, PRINTER)
    advice = material_advice(request)
    assert advice["material"] == "PETG"
    assert any("load-rated" in question for question in advice["questions"])
    assert "not loaded inventory" in advice["note"]


def load_control():
    path = Path(__file__).resolve().parents[1] / "tools/printflowctl.py"
    spec = importlib.util.spec_from_file_location("control", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_snapshot_round_trip_preserves_data_and_refuses_overwrite(tmp_path, monkeypatch):
    ctl = load_control()
    monkeypatch.setattr(ctl, "ROOT", tmp_path)
    monkeypatch.setattr(ctl, "CONFIG", tmp_path / ".runtime/deployment.json")
    (tmp_path / "models").mkdir()
    (tmp_path / "models/part.stl").write_bytes(b"original model")
    (tmp_path / ".env").write_text("PRIVATE=test-value")
    archive = ctl.snapshot({"mcp": "sha256:test"})
    target = tmp_path / "restored"
    ctl.restore(archive, target)
    assert (target / "models/part.stl").read_bytes() == b"original model"
    assert (target / ".env").read_text() == "PRIVATE=test-value"
    assert json.loads((target / "backup-manifest.json").read_text())["images"]["mcp"] == "sha256:test"
    with pytest.raises(ValueError, match="never overwritten"):
        ctl.restore(archive, target)


def test_restore_rejects_path_escape_before_writing(tmp_path):
    ctl = load_control()
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("backup-manifest.json", "{}")
        file.writestr("../outside.txt", "not allowed")
    destination = tmp_path / "output"
    with pytest.raises(ValueError): ctl.restore(archive, destination)
    assert not destination.exists()
    assert not (tmp_path / "outside.txt").exists()


def test_failed_update_build_does_not_stop_running_services(monkeypatch):
    ctl = load_control()
    calls = []
    monkeypatch.setattr(ctl, "docker_required", lambda: None)
    monkeypatch.setattr(ctl, "ensure_idle_services", lambda: None)
    monkeypatch.setattr(ctl, "running_images", lambda: {"mcp": "sha256:old"})
    def run(args, **kwargs):
        calls.append(args)
        if "build" in args: raise RuntimeError("build failed")
    monkeypatch.setattr(ctl, "command", run)
    with pytest.raises(RuntimeError): ctl.maintain(update=True)
    assert not any("stop" in call for call in calls)


def test_failed_update_health_requests_previous_images(monkeypatch, tmp_path):
    ctl = load_control()
    (tmp_path / ".runtime").mkdir()
    monkeypatch.setattr(ctl, "ROOT", tmp_path)
    monkeypatch.setattr(ctl, "docker_required", lambda: None)
    monkeypatch.setattr(ctl, "ensure_idle_services", lambda: None)
    monkeypatch.setattr(ctl, "running_images", lambda: {"mcp": "sha256:old"})
    monkeypatch.setattr(ctl, "snapshot", lambda previous: tmp_path / "backup.zip")
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if "--wait" in args: raise RuntimeError("unhealthy")
    monkeypatch.setattr(ctl, "command", run)
    with pytest.raises(RuntimeError, match="Previous images"):
        ctl.maintain(update=True)
    assert "--pull" in calls[-1] and "never" in calls[-1]
    assert json.loads((tmp_path / ".runtime/rollback.compose.json").read_text())["services"]["mcp"]["image"] == "sha256:old"
