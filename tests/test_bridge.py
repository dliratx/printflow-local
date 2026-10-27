from pathlib import Path
import json
import zipfile

import pytest
import u1_server as s


def test_inputs_cannot_escape_workspace():
    with pytest.raises(ValueError): s.local_file("../../printer_preferences.json",{".json"})
    with pytest.raises(ValueError): s.local_file(r"C:\Windows\win.ini",{".ini"})


@pytest.mark.parametrize("changes",[
    {"post_process":"echo unwanted"}, {"layer_height":float("nan")},
    {"layer_height":.5}, {"wall_loops":2.5}, {"support_interface_filament":4},
    {"enable_support":True,"support_top_z_distance":0},
    {"enable_support":True,"support_top_z_distance":0,"support_interface_filament":2},
])
def test_invalid_changes_rejected(changes):
    with pytest.raises(ValueError):
        s.validate_changes(changes,{"filament_settings_id":["PLA","PLA"],"filament_type":["PLA","PLA"]})


def test_native_project_copy_preserves_every_geometry_and_paint_byte(tmp_path):
    source=Path(__file__).parent/"fixtures/two-color.3mf"
    copy=tmp_path/"copy.3mf"
    before=s.sha(source)
    s.write_project_copy(source,copy,{"layer_height":.12,"support_top_z_distance":.24})
    with zipfile.ZipFile(source) as zi,zipfile.ZipFile(copy) as zo:
        for n in zi.namelist():
            if n!="Metadata/project_settings.config": assert zi.read(n)==zo.read(n)
        assert json.loads(zo.read("Metadata/project_settings.config"))["layer_height"]=="0.12"
    assert s.sha(source)==before


def test_slice_retains_saved_placement_and_does_not_disable_native_checks(tmp_path,monkeypatch):
    from types import SimpleNamespace
    source=Path(__file__).parent/'fixtures/two-color.3mf'
    def run(cmd,**kwargs):
        assert cmd[cmd.index('--arrange')+1]=='0'
        assert cmd[cmd.index('--slice')+1]=='0'
        assert cmd[-1]==str(source)
        assert not any('collision' in str(arg) or 'skip' in str(arg) for arg in cmd)
        return SimpleNamespace(returncode=1,stdout='',stderr='Collision detected')
    monkeypatch.setattr(s.subprocess,'run',run)
    result=s.slice_copy(source,tmp_path)
    assert result['status']=='error' and 'Collision detected' in result['log_tail']


def test_reject_other_machine_and_scripts(tmp_path):
    for changes in ({"printer_model":"Other"},{"post_process":["run-script"]}):
        target=tmp_path/"invalid.3mf"
        with zipfile.ZipFile(Path(__file__).parent/"fixtures/two-color.3mf") as zi,zipfile.ZipFile(target,"w") as zo:
            for n in zi.namelist():
                data=zi.read(n)
                if n=="Metadata/project_settings.config": data=json.dumps(json.loads(data)|changes).encode()
                zo.writestr(n,data)
        with pytest.raises(ValueError): s.read_project(target)


def test_configured_support_interface_allows_zero_gap_for_pla_petg():
    result=s.validate_changes({"support_top_z_distance":0,"support_interface_filament":2,"enable_support":True},{"filament_settings_id":["PLA","PETG"],"filament_type":["PLA","PETG"]})
    assert result["support_top_z_distance"]=="0"


def test_stats_use_emitted_config_not_layer_comment():
    p=Path(__file__).parent/"fixtures/native_slice_excerpt.gcode"
    stats=s.analyze(p)
    assert stats["effective_settings"]["layer_height"]=="0.2"
    assert stats["tools_zero_based"]==[0,1]
    assert stats["total_filament_grams"]>0
    assert stats["extrusion_moves_by_feature"]["Prime tower"]>0


def test_factory_hotend_uses_standard_flow_variant():
    profile={"filament_flow_support":["standard","high_flow"],"nozzle_temperature":["215","220"],"filament_max_volumetric_speed":["22","40"]}
    selected=s.standard_filament(profile)
    assert selected["nozzle_temperature"]==["215"]
    assert selected["filament_max_volumetric_speed"]==["22"]

def test_calibration_copy_preserves_geometry_and_restricts_temperature(tmp_path,monkeypatch):
    source=tmp_path/'model.3mf';run=tmp_path/'output';run.mkdir()
    monkeypatch.setattr(s,'MODELS',tmp_path);monkeypatch.setattr(s,'RUNS',run)
    fixture=Path(__file__).parent/'fixtures/two-color.3mf'
    with zipfile.ZipFile(fixture) as src,zipfile.ZipFile(source,'w') as dest:
        for name in src.namelist():
            raw=src.read(name)
            if name=='Metadata/project_settings.config':
                c=json.loads(raw);c.update(filament_settings_id=['Test PLA'],filament_flow_ratio=['.97'],nozzle_temperature=['220'],nozzle_temperature_range_low=['190'],nozzle_temperature_range_high=['240'])
                raw=json.dumps(c).encode()
            dest.writestr(name,raw)
    before=s.sha(source)
    result=s.u1_apply_filament_calibration(str(source),'Test PLA',{'filament_flow_ratio':.98,'nozzle_temperature':215})
    with zipfile.ZipFile(source) as old,zipfile.ZipFile(result['project']) as new:
        assert old.read('3D/3dmodel.model')==new.read('3D/3dmodel.model')
        c=json.loads(new.read('Metadata/project_settings.config'));assert c['filament_flow_ratio']==['0.98']
    assert s.sha(source)==before
    for expected,values in [('Other PLA',{'filament_flow_ratio':1}),('Test PLA',{'nozzle_temperature':280}),('Test PLA',{'pressure_advance':.02})]:
        with pytest.raises(ValueError):s.u1_apply_filament_calibration(str(source),expected,values)


def test_extrusion_counts_handle_fractional_e_and_ignore_retractions(tmp_path):
    p=tmp_path/"fractional.gcode"
    p.write_text(";TYPE:Outer wall\nM83\nG1 X1 E.023\nG1 X2 E-.03\nG1 E1\n"
                 "M82\nG92 E10\nG1 X3 E10.03\nG1 X4 E9\nG1 X5 E9.03\n")
    assert s.analyze(p)["extrusion_moves_by_feature"]=={"Outer wall":3}
