from array import array
import hashlib
import json
from pathlib import Path
import zipfile

import pytest
from printflow import scene_preview as scene,previews
from test_previews import write_model,MESH
from printflow.mesh_stream import read_model
from io import BytesIO


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch,tmp_path):monkeypatch.setattr(scene,'DATA',tmp_path/'cache')


def test_native_scene_preserves_every_triangle_and_color_without_legacy_cap(monkeypatch):
    path=Path(__file__).parent/'fixtures/two-color.3mf';digest=hashlib.sha256(path.read_bytes()).digest()
    expected=previews.three_mf_preview(path)
    monkeypatch.setattr(previews,'LIMIT',5)
    with pytest.raises(ValueError,match='interactive preview limit'):previews.three_mf_preview(path)
    result=scene.scene(path)
    assert result['triangle_count']==expected['triangle_count']==24
    assert result['dimensions']==expected['dimensions']
    assert result['colors']==expected['colors'] and not result['sampled']
    coordinates=[];colors=[];low,high=result['bounds'];extent=max(b-a for a,b in zip(low,high));center=[(a+b)/2 for a,b in zip(low,high)]
    for instance in result['instances']:
        data=array('f');data.frombytes(scene.buffer_path(path,result['revision'],instance['mesh']).read_bytes())
        for offset in range(0,len(data),9):
            point=previews.transform(data[offset:offset+3],instance['transform'])
            coordinates.append([round((v-center[k])/extent,6) for k,v in enumerate(point)])
            if offset%27==0:colors.append('#'+''.join(f'{round(v*255):02X}' for v in data[offset+6:offset+9]))
    assert coordinates==expected['vertices'] and colors==expected['face_colors']
    assert hashlib.sha256(path.read_bytes()).digest()==digest


def test_real_plate_ids_instance_indices_shared_mesh_and_empty_plates(tmp_path):
    plates='''<config>
      <plate><metadata key="plater_id" value="3"/><metadata key="plater_name" value="First parts"/><model_instance><metadata key="object_id" value="1"/><metadata key="instance_id" value="0"/></model_instance></plate>
      <plate><metadata key="plater_id" value="7"/><model_instance><metadata key="object_id" value="1"/><metadata key="instance_id" value="1"/></model_instance></plate>
      <plate><metadata key="plater_id" value="9"/></plate>
    </config>'''
    path=write_model(tmp_path/'plates.3mf',MESH,'<item objectid="1"/><item objectid="1" transform="1 0 0 0 1 0 0 0 1 400 0 0"/><item objectid="1" transform="1 0 0 0 1 0 0 0 1 800 0 0"/>',extras={'Metadata/model_settings.config':plates})
    result=scene.scene(path)
    assert len(result['meshes'])==1 and result['unique_triangle_count']==1 and result['triangle_count']==3
    assert [i['plate'] for i in result['instances']]==['3','7','unassigned']
    assert [p['object_count'] for p in result['plates']]==[1,1,0,1]
    assert result['plates'][0]['name']=='First parts'
    assert result['instances'][1]['bounds']==[[400,0,0],[401,1,0]]
    assert scene.scene(path)==result


def test_stale_revision_cannot_return_geometry_for_a_changed_file(tmp_path):
    path=write_model(tmp_path/'test.3mf',MESH,'<item objectid="1"/>');value=scene.scene(path)
    with pytest.raises(ValueError,match='not found'):scene.buffer_path(path,value['revision'],99)
    with path.open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError,match='changed'):scene.buffer_path(path,value['revision'],0)


def test_scenes_preserve_recursive_reference_and_memory_guards(tmp_path,monkeypatch):
    cycle='<object id="1"><components><component objectid="1"/></components></object>'
    path=write_model(tmp_path/'cycle.3mf',cycle,'<item objectid="1"/>')
    with pytest.raises(ValueError,match='Cyclic'):scene.scene(path)
    path=write_model(tmp_path/'bounded.3mf',MESH,'<item objectid="1"/>')
    monkeypatch.setattr(scene,'MAX_BUFFER_BYTES',100)
    with pytest.raises(ValueError,match='GPU scene budget'):scene.scene(path)


def test_stl_complete_mesh_and_float32_contract(tmp_path):
    path=tmp_path/'shape.stl'
    path.write_text('solid model\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 3 0 0\nvertex 0 2 0\nendloop\nendfacet\nendsolid model')
    result=scene.scene(path);data=scene.buffer_path(path,result['revision'],0).read_bytes()
    assert result['dimensions']==[3,2,0] and result['triangle_count']==1
    assert len(data)==3*9*4 and result['color_count'] is None


def test_embedded_thumbnail_does_not_require_loading_large_mesh(tmp_path,monkeypatch):
    from printflow import api
    import asyncio
    path=tmp_path/'models'/'preview.3mf'
    path.parent.mkdir()
    image=b'\x89PNG\r\n\x1a\nthumbnail-bytes'
    write_model(path,MESH,'<item objectid="1"/>',extras={'Metadata/plate_1.png':image})
    monkeypatch.setattr(api,'ROOT',tmp_path)
    monkeypatch.setattr(api,'find_file',lambda _:{'path':'preview.3mf'})
    def forbidden(*args):raise AssertionError('Embedded thumbnails must not expand triangle meshes')
    monkeypatch.setattr(previews,'preview',forbidden)
    assert asyncio.run(api.model_thumbnail('x')).body==image


def test_scene_streams_xml_without_the_legacy_model_part_limit(tmp_path,monkeypatch):
    path=write_model(tmp_path/'streamed.3mf',MESH,'<item objectid="1"/>')
    original=previews.part
    def metadata_only(z,name,limit=180000000):
        assert not name.endswith('.model'),'Geometry must use the streaming reader'
        return original(z,name,limit)
    monkeypatch.setattr(previews,'part',metadata_only)
    assert scene.scene(path)['triangle_count']==1


def test_streamed_xml_keeps_compact_arrays_instead_of_vertex_elements():
    root,objects,painted=read_model(BytesIO(f'<model><resources>{MESH}</resources><build/></model>'.encode()))
    assert root.findall('.//vertex')==[] and root.findall('.//triangle')==[]
    assert list(objects['1']['vertices'])==[0,0,0,1,0,0,0,1,0]
    assert list(objects['1']['indices'])==[0,1,2]
    assert not painted


@pytest.mark.parametrize('xml',[
    b'<!DOCTYPE model [<!ENTITY x "expand">]><model>&x;</model>',
    b'<!DOCTYPE model SYSTEM "file:///not-allowed"><model/>',
])
def test_streaming_reader_rejects_entities_and_doctypes(xml):
    with pytest.raises(ValueError,match='DTDs'):read_model(BytesIO(xml))


def test_quick_library_metadata_does_not_read_geometry(tmp_path,monkeypatch):
    path=write_model(tmp_path/'metadata.3mf',MESH,'<item objectid="1"/>',extras={
        'Metadata/project_settings.config':json.dumps({'printer_model':'Snapmaker U1','nozzle_diameter':['0.4'],'filament_colour':['#FFFFFF']})})
    original=previews.part
    def metadata_only(z,name,limit=180000000):
        assert name=='Metadata/project_settings.config'
        return original(z,name,limit)
    monkeypatch.setattr(previews,'part',metadata_only)
    result=previews.quick_metadata(path)
    assert result['preparation_supported'] and result['colors']==['#FFFFFF']
    assert 'vertices' not in result and 'dimensions' not in result


def test_legacy_viewer_gets_reload_instruction_without_expanding_mesh(monkeypatch):
    from printflow import api
    import asyncio
    monkeypatch.setattr(api,'find_file',lambda _: {'path':'large.3mf'})
    monkeypatch.setattr(previews,'preview',lambda _:pytest.fail('Legacy endpoint must not rebuild giant JSON meshes'))
    result=asyncio.run(api.model_preview('large'))
    assert result.status_code==409 and json.loads(result.body)['code']=='viewer_update_required'


def test_library_summary_is_never_mistaken_for_a_complete_scene(monkeypatch):
    from printflow import api
    import asyncio
    monkeypatch.setattr(api,'find_file',lambda _:{'path':'large.3mf','preview':{
        'geometry_format':'float32-position-normal-color-v1','revision':'cached',
        'triangle_count':2351952,'buffer_bytes':250000000,'colors':['#FFFFFF']}})
    monkeypatch.setattr(previews,'quick_metadata',lambda _:{'preparation_supported':True})
    result=asyncio.run(api.model_summary('large'))
    assert result['triangle_count']==2351952 and result['preparation_supported']
    assert 'geometry_format' not in result and 'revision' not in result
