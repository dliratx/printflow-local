from pathlib import Path
import hashlib,zipfile
import pytest
from printflow.previews import three_mf_preview,stl_preview,thumbnail

CORE='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
def write_model(path,objects,build,unit='millimeter',extras=None):
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('3D/3dmodel.model',f'<model xmlns="{CORE}" unit="{unit}"><resources>{objects}</resources><build>{build}</build></model>')
        for name,value in (extras or {}).items():z.writestr(name,value)
    return path
MESH='<object id="1" type="model"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="0"/></vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object>'

def test_3mf_units_build_instances_and_no_unreferenced_objects(tmp_path):
    p=write_model(tmp_path/'model.3mf',MESH+MESH.replace('id="1"','id="99"'),'<item objectid="1"/><item objectid="1" transform="1 0 0 0 1 0 0 0 1 2 0 0"/>','inch')
    result=three_mf_preview(p)
    assert result['object_count']==2
    assert result['dimensions']==[76.2,25.4,0]
    assert not result['preparation_supported']
    assert result['color_count'] is None

def test_component_transform_and_material_colors(tmp_path):
    group='<basematerials id="5"><base name="Red" displaycolor="#FF0000"/></basematerials>'
    mesh=MESH.replace('type="model"','type="model" pid="5" pindex="0"')
    assembly='<object id="2" type="model"><components><component objectid="1" transform="2 0 0 0 3 0 0 0 1 0 0 0"/></components></object>'
    p=write_model(tmp_path/'model.3mf',group+mesh+assembly,'<item objectid="2"/>')
    result=three_mf_preview(p)
    assert result['dimensions']==[2,3,0]
    assert result['face_colors']==['#FF0000']
    assert result['color_count']==1

def test_reject_recursive_components(tmp_path):
    obj='<object id="1"><components><component objectid="1"/></components></object>'
    p=write_model(tmp_path/'cycle.3mf',obj,'<item objectid="1"/>')
    with pytest.raises(ValueError,match='Cyclic'):three_mf_preview(p)

def test_native_colors_and_source_bytes_unchanged():
    path=Path(__file__).parent/'fixtures/two-color.3mf';before=hashlib.sha256(path.read_bytes()).digest()
    result=three_mf_preview(path)
    assert result['color_count']==2 and result['preparation_supported']
    assert len(result['vertices'])==72
    data,mime=thumbnail(path,result)
    assert mime=='image/png' and data.startswith(b'\x89PNG\r\n\x1a\n')
    assert hashlib.sha256(path.read_bytes()).digest()==before


def test_medium_density_surface_has_no_randomly_missing_facets():
    from printflow.previews import Sample
    sample=Sample()
    for x in range(100):
        for y in range(100):
            sample.add([[x,y,0],[x+1,y,0],[x,y+1,0]])
            sample.add([[x+1,y,0],[x+1,y+1,0],[x,y+1,0]])
    result=sample.finish()
    assert result['triangle_count']==20000
    assert len(result['vertices'])==60000
    assert result['sampled'] is False


def test_concurrent_cache_writers_use_independent_atomic_files(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import json
    from printflow.common import save_json
    destination=tmp_path/'same-preview.json'
    def write(index): save_json(destination,{'writer':index,'vertices':list(range(1000))})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write,range(40)))
    saved=json.loads(destination.read_text())
    assert saved['writer'] in range(40) and len(saved['vertices'])==1000
    assert not list(tmp_path.glob('*.tmp'))

def test_preview_limit_never_silently_removes_facets(monkeypatch):
    from printflow import previews
    monkeypatch.setattr(previews,'LIMIT',5)
    sample=previews.Sample()
    for _ in range(5):sample.add([[0,0,0],[1,0,0],[0,1,0]])
    assert len(sample.finish()['vertices'])==15
    with pytest.raises(ValueError,match='interactive preview limit'):sample.add([[0,0,0],[1,0,0],[0,1,0]])


def test_depth_buffer_resolves_intersecting_triangles_regardless_of_order():
    from printflow.mesh_raster import rasterize
    red=([(1,1,0),(18,1,1),(1,18,0)],(255,0,0))
    blue=([(1,1,.51),(18,1,.51),(1,18,.51)],(0,0,255))
    image=rasterize([red,blue],20,20)
    assert image.tobytes()==rasterize([blue,red],20,20).tobytes()
    assert image.getpixel((2,2))==(0,0,255,255)
    assert image.getpixel((14,2))==(255,0,0,255)
    assert image.getpixel((19,19))[3]==0
