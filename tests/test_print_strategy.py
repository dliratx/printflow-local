import hashlib
import json
import numpy as np
import pytest
from printflow.print_strategy import metrics,stl_plan,project_plan,validate_rotation
from printflow.api import finish_changes
from pathlib import Path

def box(size=(20,20,10)):
    v=np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1]],float)*size
    f=[[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]]
    return v[np.array(f)]

def test_base_faces_are_not_unsupported_overhangs():
    p=stl_plan(box(),'PLA')
    m=p['objects'][0]['metrics']
    assert m['bed_contact_mm2']==400 and m['unsupported_downward_mm2']==0
    assert not p['process_changes']['enable_support']
    assert p['process_changes']['brim_type']=='no_brim'
    json.dumps(p) # Native MCP responses and persisted plans must be JSON serializable.

def test_tall_part_is_laid_on_a_broad_face_when_not_functionally_constrained():
    p=stl_plan(box((5,5,100)),'PLA')
    assert p['orientation']['selected']['metrics']['dimensions_mm'][2]==5
    assert p['orientation']['mode']=='geometry_candidate'
    q=stl_plan(box((5,5,100)),'PLA',purpose='functional')
    assert q['orientation']['mode']=='preserved'
    assert q['process_changes']['brim_type']=='auto_brim'

def test_disconnected_feet_do_not_get_no_brim_from_aggregate_contact():
    t=np.concatenate([box(),box()+[30,0,0]])
    p=stl_plan(t,'PLA')
    assert p['objects'][0]['connected_components']==2
    assert p['process_changes']['brim_type']=='auto_brim'

def test_warp_prone_material_retains_auto_brim():
    assert stl_plan(box(),'ABS')['process_changes']['brim_type']=='auto_brim'

def test_native_project_preserves_settings_and_original():
    path=Path(__file__).parent/'fixtures/two-color.3mf';before=hashlib.sha256(path.read_bytes()).hexdigest()
    p=project_plan(path)
    assert p['orientation']['mode']=='preserved_native_layout'
    assert p['process_changes']=={} and p['objects']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before

def test_reject_scale_or_mirror_masquerading_as_orientation():
    for r in [np.eye(3)*2,np.diag([-1,1,1]),[float('nan')]*9]:
        with pytest.raises(ValueError):validate_rotation(r)

def test_no_universal_speed_or_support_gap_override():
    assert finish_changes({})=={}
    assert finish_changes({'layer_height':.16,'supports':True})=={'layer_height':.16,'enable_support':True}
    assert finish_changes({'process_changes':{'brim_type':'no_brim'}})=={'brim_type':'no_brim'}
