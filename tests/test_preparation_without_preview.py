import asyncio
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from printflow import api, previews


def test_preview_budget_does_not_block_full_native_preparation(monkeypatch, tmp_path):
    source=tmp_path/'models'/'multi.3mf';source.parent.mkdir()
    shutil.copyfile(Path(__file__).parent/'fixtures/two-color.3mf', source)
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(previews,'LIMIT',5)
    with pytest.raises(ValueError,match='interactive preview limit'):
        previews.three_mf_preview(source)
    assert previews.preparation_metadata(source)['preparation_supported']
    item={'id':'model','path':'multi.3mf','name':'Multi.3mf','extension':'.3mf'}
    job={'id':'compare','file_id':'model'};calls=[];children=[]
    monkeypatch.setattr(api,'ROOT',tmp_path)
    monkeypatch.setattr(api,'find_file',lambda _:item)
    monkeypatch.setattr(api,'jobs',children)
    monkeypatch.setattr(api,'find_job',lambda key:next(j for j in children if j['id']==key))
    monkeypatch.setattr(api,'update_job',lambda job,**values:job.update(values))
    monkeypatch.setattr(api,'activity',lambda _:None)
    async def native(name, arguments=None):
        calls.append((name,arguments))
        if name=='u1_health':return {'validated_binary_unchanged':True}
        if name=='u1_inspect_project':return {'inspected':arguments['project']}
        if name=='u1_compare_variants':return {'variants':[{'name':v['name'],'status':'ok','project':'native-copy.3mf'} for v in arguments['variants']], 'selection_policy':'Compare physical results'}
        return {}
    async def forbidden_preview(*args):raise AssertionError('Slicing must not depend on an interactive preview')
    monkeypatch.setattr(api,'native',native)
    monkeypatch.setattr(api,'model_preview',forbidden_preview)
    asyncio.run(api.run_job(job,{'mode':'compare','supports':False}))
    assert job['status']=='ready',job.get('error')
    assert [c[0] for c in calls]==['u1_preferences','u1_health','u1_inspect_project','u1_compare_variants']
    assert calls[2][1]['project']==calls[3][1]['project']=='multi.3mf'
    assert len(children)==2
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest


@pytest.mark.parametrize('change',[
    {'printer_model':'Other printer'}, {'nozzle_diameter':['0.6']}, {'post_process':['run something']}
])
def test_preparation_metadata_keeps_printer_nozzle_and_postprocessor_guards(tmp_path,change):
    source=tmp_path/'project.3mf'
    cfg={'printer_model':'Snapmaker U1','nozzle_diameter':['0.4']*4,'post_process':[]}|change
    with zipfile.ZipFile(source,'w') as z:z.writestr('Metadata/project_settings.config',json.dumps(cfg))
    assert not previews.preparation_metadata(source)['preparation_supported']


def test_native_inspection_failure_still_stops_preparation(monkeypatch,tmp_path):
    source=tmp_path/'models'/'multi.3mf';source.parent.mkdir()
    shutil.copyfile(Path(__file__).parent/'fixtures/two-color.3mf',source)
    monkeypatch.setattr(api,'ROOT',tmp_path)
    monkeypatch.setattr(api,'find_file',lambda _:{'id':'m','path':'multi.3mf','extension':'.3mf'})
    monkeypatch.setattr(api,'update_job',lambda job,**values:job.update(values))
    calls=[]
    async def native(name,arguments=None):
        calls.append(name)
        if name=='u1_health':return {'validated_binary_unchanged':True}
        if name=='u1_inspect_project':raise ValueError('Invalid project geometry')
        return {}
    monkeypatch.setattr(api,'native',native)
    job={'id':'invalid','file_id':'m'}
    asyncio.run(api.run_job(job,{'mode':'compare'}))
    assert job['status']=='error' and job['error']=='Invalid project geometry'
    assert calls[-1]=='u1_inspect_project' and 'u1_compare_variants' not in calls

@pytest.mark.parametrize('extension',['.stl','.3mf'])
def test_adaptive_pipeline_passes_rotation_and_preserves_native_settings(monkeypatch,tmp_path,extension):
    item={'id':'model','path':'model'+extension,'extension':extension,'name':'Test model'}
    job={'id':'adaptive','file_id':'model'};calls=[];children=[]
    rotation=[1,0,0,0,0,1,0,-1,0]
    plan={'orientation':{'selected':{'rotation':rotation}},'process_changes':{'brim_type':'no_brim','enable_support':False,'layer_height':.16} if extension=='.stl' else {}}
    monkeypatch.setattr(api,'ROOT',tmp_path)
    monkeypatch.setattr(api,'find_file',lambda _:item)
    monkeypatch.setattr(api,'jobs',children)
    monkeypatch.setattr(api,'find_job',lambda key:next(j for j in children if j['id']==key))
    monkeypatch.setattr(api,'update_job',lambda job,**v:job.update(v))
    monkeypatch.setattr(api,'activity',lambda _:None)
    monkeypatch.setattr(previews,'preparation_metadata',lambda _: {'preparation_supported':True})
    async def native(name,arguments=None):
        calls.append((name,arguments))
        if name=='u1_health':return {'validated_binary_unchanged':True}
        if name=='u1_print_strategy':return plan
        if name=='u1_prepare_stl':return {'project':'oriented.3mf'}
        if name=='u1_inspect_project':return {'process':{'layer_height':'.16'}}
        if name=='u1_compare_variants':return {'variants':[{'name':v['name'],'status':'ok','plates':[]} for v in arguments['variants']],'selection_policy':'Review'}
        return {}
    monkeypatch.setattr(api,'native',native)
    asyncio.run(api.run_job(job,{'strategy':'adaptive','mode':'compare','filament':'actual material','process_changes':{'brim_type':'auto_brim'}}))
    assert job['status']=='ready',job.get('error')
    prepare=[args for name,args in calls if name=='u1_prepare_stl']
    if extension=='.stl':assert prepare[0]['rotation']==rotation
    else:assert not prepare
    variants=next(args['variants'] for name,args in calls if name=='u1_compare_variants')
    assert variants[0]['changes']['brim_type']=='auto_brim' # Explicit choice wins.
    assert variants[1]['changes']['layer_height']==.12
    assert all('outer_wall_speed' not in v['changes'] and 'support_top_z_distance' not in v['changes'] for v in variants)
    assert all(child['print_strategy']==plan for child in children)
