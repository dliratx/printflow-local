"""Bounded solid partitioning for the isolated CAD container, using Manifold."""
import base64
import io
import itertools
import json
import math
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
import manifold3d as mf
from . import previews as p

def load_regions(raw, extension):
    if extension=='.stl':
        mesh=trimesh.load(io.BytesIO(raw),file_type='stl',force='mesh',process=True)
        return [(mesh,'#B8C6DA','Model',0)],[]
    if extension!='.3mf':raise ValueError('Split an STL or an unpainted native 3MF assembly')
    regions=[]
    with p.archive(io.BytesIO(raw)) as z:
        cfg=json.loads(p.part(z,'Metadata/project_settings.config',5_000_000))
        palette=cfg.get('filament_colour',[])
        if cfg.get('printer_model')!='Snapmaker U1' or not 1<=len(palette)<=4:raise ValueError('Save an unpainted native U1 color assembly before splitting')
        assignments={};labels={};doc={}
        if 'Metadata/model_settings.config' in z.namelist():
            root=p.xml(p.part(z,'Metadata/model_settings.config',5_000_000))
            for node in [*root.findall('object'),*root.findall('.//part')]:
                settings={n.get('key'):n.get('value') for n in node.findall('metadata')}
                # New section projects intentionally use new process settings; never silently discard local overrides.
                if set(settings)-{'name','extruder','matrix','source_file','source_object_id','source_volume_id','source_offset_x','source_offset_y','source_offset_z'}:raise ValueError('This project has per-object settings. Review and remove overrides in a copy before splitting.')
                if 'extruder' in settings:assignments[node.get('id')]=int(settings['extruder'])-1
                labels[node.get('id')]=settings.get('name','Color region')
        def document(name):
            if name not in doc:
                data=p.part(z,name)
                if any(x in data for x in (b'paint_color',b'mmu_segmentation',b'texture2d',b'pid=')):raise ValueError('Painted facets, texture or face-color data require native Orca cutting to preserve them')
                root=p.xml(data);unit=p.UNITS.get(root.get('unit','millimeter'))
                if unit!=1:raise ValueError('Use a project in millimeters')
                doc[name]=(root,{o.get('id'):o for o in root.findall('./{*}resources/{*}object')})
            return doc[name]
        def visit(name,oid,chain,slot,seen):
            if (name,oid) in seen or len(seen)>30:raise ValueError('Invalid 3MF component graph')
            root,objects=document(name);obj=objects.get(oid)
            if obj is None:raise ValueError('Missing 3MF object')
            slot=assignments.get(oid,slot)
            if not 0<=slot<len(palette):raise ValueError('Invalid color assignment')
            mesh=obj.find('{*}mesh')
            if mesh is not None:
                vertices=[]
                for v in mesh.findall('./{*}vertices/{*}vertex'):
                    point=[float(v.get(a,'0')) for a in 'xyz']
                    for matrix in chain:point=p.transform(point,matrix)
                    vertices.append(point)
                faces=[[int(t.get('v'+str(i))) for i in (1,2,3)] for t in mesh.findall('./{*}triangles/{*}triangle')]
                regions.append((trimesh.Trimesh(vertices,faces,process=True),palette[slot],labels.get(oid,'Color region'),slot))
            for c in obj.findall('./{*}components/{*}component'):
                target=p.attr(c,'path');visit(p.resolve(name,target) if target else name,c.get('objectid'),[p.matrix(c.get('transform'))]+chain,slot,seen|{(name,oid)})
        main='3D/3dmodel.model';root,_=document(main)
        for item in root.findall('./{*}build/{*}item'):
            if p.attr(item,'printable','1')=='0':continue
            target=p.attr(item,'path');visit(p.resolve(main,target) if target else main,item.get('objectid'),[p.matrix(item.get('transform'))],0,set())
    return regions,list(zip(cfg.get('filament_settings_id',[]),palette))

def as_solid(mesh):
    if not isinstance(mesh,trimesh.Trimesh) or not len(mesh.faces) or len(mesh.faces)>1_000_000:raise ValueError('Each region must contain 1 to 1,000,000 triangles')
    if not np.isfinite(mesh.vertices).all() or not mesh.is_volume:raise ValueError('Splitting requires closed, consistently wound solid regions. Repair a copy in Orca first.')
    solid=mf.Manifold(mf.Mesh(np.asarray(mesh.vertices,dtype=np.float32),np.asarray(mesh.faces,dtype=np.uint32)))
    if solid.status()!=mf.Error.NoError:raise ValueError('The mesh could not be converted to a manifold solid')
    return solid

def export_3mf(meshes,path,colors):
    ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02';tag=lambda x:'{'+ns+'}'+x
    root=ET.Element(tag('model'),unit='millimeter');res=ET.SubElement(root,tag('resources'));mats=ET.SubElement(res,tag('basematerials'),id='1')
    for i,c in enumerate(colors):ET.SubElement(mats,tag('base'),name=f'Color {i+1}',displaycolor=c)
    build=ET.SubElement(root,tag('build'))
    for i,(mesh,slot) in enumerate(meshes,2):
        obj=ET.SubElement(res,tag('object'),id=str(i),type='model',pid='1',pindex=str(slot));node=ET.SubElement(obj,tag('mesh'));verts=ET.SubElement(node,tag('vertices'));faces=ET.SubElement(node,tag('triangles'))
        for v in mesh.vertices:ET.SubElement(verts,tag('vertex'),**{a:str(v[k]) for k,a in enumerate('xyz')})
        for f in mesh.faces:ET.SubElement(faces,tag('triangle'),**{f'v{k+1}':str(n) for k,n in enumerate(f)})
        ET.SubElement(build,tag('item'),objectid=str(i))
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('3D/3dmodel.model',ET.tostring(root))
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')

def split_model(body,directory):
    raw=base64.b64decode(body['data'],validate=True)
    if len(raw)>50_000_000:raise ValueError('Split source is limited to 50 MB')
    cell=np.asarray(body['cell_mm'],dtype=float)
    if cell.shape!=(3,) or not np.isfinite(cell).all() or np.any(cell<10) or np.any(cell>2000):raise ValueError('Use three usable build dimensions between 10 and 2,000 mm')
    regions,profiles=load_regions(raw,body['extension'])
    if not regions or len(regions)>16:raise ValueError('Use one to sixteen solid color regions')
    solids=[as_solid(r[0]) for r in regions]
    low=np.min([r[0].bounds[0] for r in regions],axis=0);high=np.max([r[0].bounds[1] for r in regions],axis=0)
    counts=np.maximum(1,np.ceil((high-low)/cell).astype(int))
    if math.prod(counts)>32:raise ValueError('This cut would exceed 32 sections. Choose a larger printer or split a smaller region in Orca.')
    step=(high-low)/counts;dest=Path(directory);parts=[];volume=0
    palette=[c for _,c in profiles] if profiles else ['#B8C6DA']
    for grid in itertools.product(*(range(n) for n in counts)):
        lower=low+np.asarray(grid)*step;upper=lower+step;cut=[]
        for region,solid in zip(regions,solids):
            for axis in range(3):
                normal=[0.,0.,0.];normal[axis]=1
                solid=solid.split_by_plane(normal,float(lower[axis]))[0].split_by_plane(normal,float(upper[axis]))[1]
            if solid.is_empty() or solid.volume()<.001:continue
            out=solid.to_mesh();mesh=trimesh.Trimesh(out.vert_properties[:,:3],out.tri_verts,process=True)
            if not mesh.is_volume:raise ValueError('A cut produced an invalid solid; no assembly was saved')
            volume+=mesh.volume;cut.append((mesh,region[1],region[2],region[3]))
        if not cut:continue
        index=len(parts)+1;offset=np.min([r[0].bounds[0] for r in cut],axis=0);region_files=[]
        for n,(mesh,color,label,slot) in enumerate(cut):
            mesh.apply_translation(-offset);name=f'part-{index:02d}-color-{n+1}.stl';mesh.export(dest/name)
            region_files.append({'name':label,'file':name,'planned_tool':slot,'color':color,'preserve_assembly_origin':True})
        merged=trimesh.util.concatenate([r[0] for r in cut]);base=f'part-{index:02d}.stl';merged.export(dest/base)
        three=f'part-{index:02d}.3mf';export_3mf([(m,slot) for m,_,_,slot in cut],dest/three,palette)
        dims=merged.extents.tolist()
        if np.any(merged.extents>cell+.02):raise ValueError('A section exceeds the usable build volume')
        manifest={'assembly':{'name':f'Section {index:02d}','source':base,'parts':region_files,'colors':palette}}
        (dest/f'part-{index:02d}.json').write_text(json.dumps(manifest),encoding='utf-8')
        parts.append({'index':index,'grid':[int(n)+1 for n in grid],'file':base,'color_file':three,'manifest':f'part-{index:02d}.json','regions':region_files,'dimensions':dims,'assembly_translation_mm':offset.tolist(),'volume_mm3':float(merged.volume),'colors':list(dict.fromkeys(c[1] for c in cut))})
    source_volume=sum(s.volume() for s in solids)
    if abs(volume-source_volume)>max(.1,source_volume*.0001):raise ValueError('Split volume verification failed')
    manifest={'parts':parts,'source_dimensions':(high-low).tolist(),'grid':[int(n) for n in counts],'profiles':profiles,'colors':palette,'source_volume_mm3':source_volume,'split_volume_mm3':float(volume),'joint':'Flat cut faces for adhesive assembly; no alignment pins or load rating. Match the numbered grid and original coordinates. Review seams and print orientation before slicing.'}
    (dest/'assembly-plan.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest
