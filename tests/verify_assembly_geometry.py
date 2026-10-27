"""Run with the isolated CAD interpreter; does not require live printers."""
import base64
import json
import io
import zipfile
import xml.etree.ElementTree as ET
import tempfile
from pathlib import Path
import numpy as np
import trimesh
from printflow.assembly_geometry import split_model,load_regions

def color_fixture():
    ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
    tag=lambda name:'{'+ns+'}'+name
    root=ET.Element(tag('model'),unit='millimeter')
    resources=ET.SubElement(root,tag('resources'));build=ET.SubElement(root,tag('build'))
    settings=ET.Element('config')
    for i in range(4):
        mesh=trimesh.creation.box([30,30,80]);mesh.apply_translation([i*30+15,15,40])
        obj=ET.SubElement(resources,tag('object'),id=str(i+1),type='model')
        geometry=ET.SubElement(obj,tag('mesh'));vertices=ET.SubElement(geometry,tag('vertices'));faces=ET.SubElement(geometry,tag('triangles'))
        for v in mesh.vertices:ET.SubElement(vertices,tag('vertex'),**{axis:str(v[k]) for k,axis in enumerate('xyz')})
        for f in mesh.faces:ET.SubElement(faces,tag('triangle'),**{f'v{k+1}':str(f[k]) for k in range(3)})
        ET.SubElement(build,tag('item'),objectid=str(i+1))
        meta=ET.SubElement(settings,'object',id=str(i+1));ET.SubElement(meta,'metadata',key='extruder',value=str(i+1))
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('3D/3dmodel.model',ET.tostring(root))
        z.writestr('Metadata/model_settings.config',ET.tostring(settings))
        z.writestr('Metadata/project_settings.config',json.dumps({'printer_model':'Snapmaker U1','filament_colour':['#FF0000','#00FF00','#0000FF','#FFFFFF'],'filament_settings_id':['Test PLA']*4}))
    return raw.getvalue()

def verify():
    source=trimesh.creation.box([310,220,80]);source.apply_translation([42,-20,50])
    raw=source.export(file_type='stl')
    with tempfile.TemporaryDirectory() as temp:
        result=split_model({'data':base64.b64encode(raw).decode(),'extension':'.stl','cell_mm':[150,130,100]},temp)
        assert result['grid']==[3,2,1] and len(result['parts'])==6
        assert abs(result['split_volume_mm3']-source.volume)<1
        for part in result['parts']:
            mesh=trimesh.load(Path(temp)/part['file']);assert mesh.is_volume and np.all(mesh.extents<=[150.02,130.02,100.02]);assert np.allclose(mesh.bounds[0],0)
        print('Six capped sections: volume, fit and local origins verified')
    source=color_fixture()
    regions,profiles=load_regions(source,'.3mf');assert len(regions)==4 and len(profiles)==4
    with tempfile.TemporaryDirectory() as temp:
        result=split_model({'data':base64.b64encode(source).decode(),'extension':'.3mf','cell_mm':[50,50,65]},temp)
        assert len(result['parts'])>=4
        assert abs(result['source_volume_mm3']-result['split_volume_mm3'])<1
        assert set(c for part in result['parts'] for c in part['colors'])==set(result['colors'])
        print('Four-color solid partition: palette and volume verified')
    open_mesh=trimesh.creation.box();open_mesh.update_faces(np.arange(len(open_mesh.faces)-1))
    with tempfile.TemporaryDirectory() as temp:
        try:split_model({'data':base64.b64encode(open_mesh.export(file_type='stl')).decode(),'extension':'.stl','cell_mm':[50,50,50]},temp)
        except ValueError:pass
        else:raise AssertionError('Non-watertight source was accepted')
    print('Invalid open mesh rejected')

if __name__=='__main__':verify()
