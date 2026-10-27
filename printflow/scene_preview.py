"""Lossless GPU scenes: shared meshes, native build instances and plate membership.

Geometry is cached as float32 buffers rather than millions of JSON coordinates.
No triangles are sampled or removed. Sources and slicer projects remain untouched.
"""
from array import array
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import threading
import numpy as np

from .common import DATA, read_json, save_json
from . import previews as p
from .mesh_stream import read_model

MAX_BUFFER_BYTES=256*1024*1024
IDENTITY=p.matrix(None)
_build_lock=threading.Lock()


def cache_key(path):
    stat=path.stat()
    return hashlib.sha256(f'{path}|{stat.st_size}|{stat.st_mtime_ns}|scene-v2'.encode()).hexdigest()


def combined(chain,unit=1):
    points=[[0.,0.,0.],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]]
    for m in chain:points=[p.transform(v,m) for v in points]
    points=[[n*unit for n in v] for v in points];origin=points[0]
    return [points[j+1][i]-origin[i] for j in range(3) for i in range(3)]+origin


def bounds_transform(low,high,m):
    corners=[p.transform([x,y,z],m) for x in (low[0],high[0]) for y in (low[1],high[1]) for z in (low[2],high[2])]
    return [[min(v[k] for v in corners) for k in range(3)],[max(v[k] for v in corners) for k in range(3)]]


class Builder:
    def __init__(self,folder):
        self.folder=folder;self.meshes=[];self.instances=[];self.bytes=0;self.colors=set()

    def geometry(self,triangles):
        data=array('f');low=[math.inf]*3;high=[-math.inf]*3;count=0;used=set();rgb_cache={}
        for triangle,tint in triangles:
            if any(len(v)!=3 or any(not math.isfinite(n) for n in v) for v in triangle):raise ValueError('Model contains invalid coordinates')
            a,b,c=triangle;u=[b[k]-a[k] for k in range(3)];v=[c[k]-a[k] for k in range(3)]
            normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
            length=math.sqrt(sum(n*n for n in normal)) or 1.;normal=[n/length for n in normal]
            if tint not in rgb_cache:rgb_cache[tint]=[int(tint[i:i+2],16)/255 for i in (1,3,5)]
            for point in triangle:
                for k,n in enumerate(point):low[k]=min(low[k],n);high[k]=max(high[k],n)
                data.extend(point);data.extend(normal);data.extend(rgb_cache[tint])
            count+=1;used.add(tint)
            if self.bytes+len(data)*4>MAX_BUFFER_BYTES:raise ValueError('This model exceeds the 256 MB GPU scene budget. Select a smaller source project in Orca.')
        if not count:raise ValueError('A printable mesh has no triangles')
        if sys.byteorder!='little':data.byteswap()
        index=len(self.meshes);target=self.folder/f'{index}.bin'
        with tempfile.NamedTemporaryFile(dir=self.folder,delete=False) as f:
            temporary=Path(f.name);data.tofile(f)
        try:temporary.replace(target)
        finally:temporary.unlink(missing_ok=True)
        self.bytes+=len(data)*4;self.colors.update(used)
        mesh={'id':index,'triangle_count':count,'vertex_count':count*3,'byte_length':len(data)*4,'bounds':[low,high]}
        self.meshes.append(mesh);return mesh

    def geometry_arrays(self,source,tint,overrides):
        vertices=np.frombuffer(source['vertices'],dtype=np.float64).reshape(-1,3)
        indices=np.frombuffer(source['indices'],dtype=np.uint32).reshape(-1,3)
        count=len(indices);size=count*108
        if not count:raise ValueError('A printable mesh has no triangles')
        if self.bytes+size>MAX_BUFFER_BYTES:raise ValueError('This model exceeds the 256 MB GPU scene budget. Select a smaller source project in Orca.')
        if int(indices.max())>=len(vertices):raise ValueError('Invalid 3MF vertex index')
        if not np.isfinite(vertices).all():raise ValueError('Model contains invalid coordinates')
        palette=list(dict.fromkeys([tint,*overrides.values()]))
        rgb=np.array([[int(c[i:i+2],16)/255 for i in (1,3,5)] for c in palette],dtype=np.float32)
        face_colors=None
        if overrides:
            face_colors=np.zeros(count,dtype=np.uint32);lookup={c:i for i,c in enumerate(palette)}
            for index,color in overrides.items():face_colors[index]=lookup[color]
        low=np.full(3,np.inf);high=np.full(3,-np.inf)
        index=len(self.meshes);target=self.folder/f'{index}.bin'
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.folder,delete=False) as f:
                temporary=Path(f.name)
                for offset in range(0,count,65536):
                    points=vertices[indices[offset:offset+65536]]
                    normals=np.cross(points[:,1]-points[:,0],points[:,2]-points[:,0])
                    lengths=np.linalg.norm(normals,axis=1);lengths[lengths==0]=1
                    normals/=lengths[:,None]
                    data=np.empty((len(points),3,9),dtype='<f4')
                    data[:,:,:3]=points;data[:,:,3:6]=normals[:,None,:]
                    data[:,:,6:]=rgb[0] if face_colors is None else rgb[face_colors[offset:offset+len(points)],None,:]
                    if not np.isfinite(data).all():raise ValueError('Model coordinates exceed the GPU numeric range')
                    low=np.minimum(low,points.min(axis=(0,1)));high=np.maximum(high,points.max(axis=(0,1)))
                    data.tofile(f)
            temporary.replace(target)
        finally:
            if temporary:temporary.unlink(missing_ok=True)
        self.bytes+=size;self.colors.update(palette)
        mesh={'id':index,'triangle_count':count,'vertex_count':count*3,'byte_length':size,'bounds':[low.tolist(),high.tolist()]}
        self.meshes.append(mesh);return mesh

    def instance(self,mesh,chain,unit,plate):
        if len(self.instances)>=10000:raise ValueError('Too many model instances')
        m=combined(chain,unit)
        self.instances.append({'mesh':mesh['id'],'transform':m,'bounds':bounds_transform(*mesh['bounds'],m),'plate':plate})

    def finish(self,metadata,plates):
        if not self.instances:raise ValueError('No printable triangle mesh found in this file')
        for plate in plates:
            instances=[i for i in self.instances if i['plate']==plate['id']]
            plate['object_count']=len(instances)
            plate['triangle_count']=sum(self.meshes[i['mesh']]['triangle_count'] for i in instances)
        low=[min(i['bounds'][0][k] for i in self.instances) for k in range(3)]
        high=[max(i['bounds'][1][k] for i in self.instances) for k in range(3)]
        return metadata|{'meshes':self.meshes,'instances':self.instances,'plates':plates,'bounds':[low,high],
            'dimensions':[round(b-a,3) for a,b in zip(low,high)],'object_count':len(self.instances),
            'triangle_count':sum(self.meshes[i['mesh']]['triangle_count'] for i in self.instances),
            'unique_triangle_count':sum(m['triangle_count'] for m in self.meshes),
            'buffer_bytes':self.bytes,'sampled':False,'geometry_format':'float32-position-normal-color-v1'}


def three_mf(path,builder):
    with p.archive(path) as z:
        names=set(z.namelist());main='3D/3dmodel.model'
        if '_rels/.rels' in names:
            for rel in p.xml(p.part(z,'_rels/.rels',1_000_000)):
                if rel.get('Type','').endswith('/3dmodel') and rel.get('TargetMode')!='External':main=p.resolve('',rel.get('Target',''))
        cfg=json.loads(p.part(z,'Metadata/project_settings.config',5_000_000)) if 'Metadata/project_settings.config' in names else {}
        slots=[p.color(c) for c in cfg.get('filament_colour',[])];assignments={};plates=[];membership={};documents={};geometries={};painted=False
        if 'Metadata/model_settings.config' in names:
            settings=p.xml(p.part(z,'Metadata/model_settings.config',5_000_000))
            for obj in settings.findall('object'):
                for node in [obj,*obj.findall('part')]:
                    meta=node.find("metadata[@key='extruder']")
                    if meta is not None:
                        try:
                            slot=int(meta.get('value'))-1
                            if slot>=0:assignments[node.get('id')]=slots[slot]
                        except (TypeError,ValueError,IndexError):pass
            for ordinal,plate in enumerate(settings.findall('plate'),1):
                meta={n.get('key'):n.get('value') for n in plate.findall('metadata')}
                pid=str(meta.get('plater_id',ordinal))
                if any(x['id']==pid for x in plates):raise ValueError('Duplicate plate identifiers')
                plates.append({'id':pid,'name':meta.get('plater_name') or f'Plate {pid}'})
                for instance in plate.findall('model_instance'):
                    values={n.get('key'):n.get('value') for n in instance.findall('metadata')}
                    key=(values.get('object_id'),int(values.get('instance_id','0')))
                    if key in membership and membership[key]!=pid:raise ValueError('A model instance belongs to more than one plate')
                    membership[key]=pid
        if not plates:plates=[{'id':'1','name':'Plate 1'}]
        def document(name):
            nonlocal painted
            if name not in documents:
                if name not in names:raise ValueError('A referenced 3MF model part is missing')
                with z.open(name) as stream:root,numeric,has_paint=read_model(stream)
                painted=painted or has_paint
                unit=p.UNITS.get(root.get('unit','millimeter'))
                if unit is None:raise ValueError('Unknown 3MF unit')
                objects={o.get('id'):o for o in root.findall('./{*}resources/{*}object')}
                groups={g.get('id'):[p.color(n.get('displaycolor') or n.get('color')) for n in g] for g in root.findall('./{*}resources/*') if p.local(g.tag) in ('basematerials','colorgroup')}
                documents[name]=(root,objects,groups,unit,numeric)
            return documents[name]
        def walk(name,oid,chain,tint,seen,plate):
            key=(name,oid)
            if key in seen or len(seen)>40:raise ValueError('Cyclic or excessively nested 3MF components')
            root,objects,groups,unit,numeric=document(name);obj=objects.get(oid)
            if obj is None:raise ValueError('A 3MF component references a missing object')
            tint=assignments.get(oid,tint);mesh=obj.find('{*}mesh')
            if mesh is not None:
                geometry_key=(name,oid,tint)
                if geometry_key not in geometries:
                    def face_color(pid,pindex):
                        try:return groups[pid][int(pindex)]
                        except (KeyError,ValueError,TypeError,IndexError):return tint
                    base_color=face_color(obj.get('pid'),obj.get('pindex','0'))
                    overrides={index:face_color(pid or obj.get('pid'),pindex or obj.get('pindex','0')) for index,(pid,pindex) in numeric[oid]['properties'].items()}
                    geometries[geometry_key]=builder.geometry_arrays(numeric[oid],base_color,overrides)
                builder.instance(geometries[geometry_key],chain,unit,plate)
            for comp in obj.findall('./{*}components/{*}component'):
                target=p.attr(comp,'path');child=p.resolve(name,target) if target else name
                walk(child,comp.get('objectid'),[p.matrix(comp.get('transform'))]+chain,tint,seen|{key},plate)
        root,_,_,_,_=document(main);counts=defaultdict(int)
        for item in root.findall('./{*}build/{*}item'):
            oid=item.get('objectid');index=counts[oid];counts[oid]+=1
            if p.attr(item,'printable','1')=='0':continue
            plate=membership.get((oid,index),'unassigned' if membership or len(plates)>1 else plates[0]['id'])
            if plate=='unassigned' and not any(x['id']==plate for x in plates):plates.append({'id':plate,'name':'Unassigned objects'})
            target=p.attr(item,'path');name=p.resolve(main,target) if target else main
            walk(name,oid,[p.matrix(item.get('transform'))],p.DEFAULT,set(),plate)
        colors=list(dict.fromkeys(slots or sorted(builder.colors-{p.DEFAULT})))
        note='Full mesh and object colors. Painted facets and textures require review in Orca.' if painted else 'Full mesh, saved object colors and original build placement.'
        return builder.finish(p.project_compatibility(cfg)|{'format':'3MF','colors':colors,'color_count':len(colors) or None,'painted_facets':painted,'note':note},plates)


def stl(path,builder):
    def triangles():
        with path.open('rb') as f:
            header=f.read(84);count=struct.unpack_from('<I',header,80)[0] if len(header)==84 else 0
            if count and path.stat().st_size==84+count*50:
                for _ in range(count):
                    values=struct.unpack('<12fH',f.read(50));yield [values[i:i+3] for i in (3,6,9)],p.DEFAULT
            else:
                f.seek(0);tri=[]
                for raw in f:
                    line=raw.strip().split()
                    if line[:1]==[b'vertex'] and len(line)==4:
                        tri.append([float(x) for x in line[1:]])
                        if len(tri)==3:yield tri,p.DEFAULT;tri=[]
                if tri:raise ValueError('Incomplete STL triangle')
    mesh=builder.geometry(triangles());builder.instance(mesh,[],1,'1')
    return builder.finish({'format':'STL','colors':[],'color_count':None,'preparation_supported':True,
        'preparation_note':'Choose the filament actually loaded before preparing this model.',
        'note':'Full mesh. STL does not contain printable color assignments.'},[{'id':'1','name':'Plate 1'}])


def scene(path):
    path=Path(path);revision=cache_key(path);folder=DATA/'model-scenes'/revision;manifest=folder/'scene.json'
    cached=read_json(manifest,None)
    if cached and all((folder/f"{m['id']}.bin").exists() for m in cached['meshes']):return cached
    with _build_lock:
        cached=read_json(manifest,None)
        if cached and all((folder/f"{m['id']}.bin").exists() for m in cached['meshes']):return cached
        folder.mkdir(parents=True,exist_ok=True);builder=Builder(folder)
        result=stl(path,builder) if path.suffix.lower()=='.stl' else three_mf(path,builder)
        if path.parent.parent.name=='designs' and read_json(path.parent/'manifest.json',{}).get('engine')=='TripoSR':result.update(view_yaw=1.15,view_tilt=.3)
        if path.stem=='overhang' and 'calibration-assets' in path.parts:result.update(view_yaw=-.55,view_tilt=.25)
        if cache_key(path)!=revision:raise ValueError('The model changed while loading. Open it again.')
        result['revision']=revision;save_json(manifest,result);return result


def buffer_path(path,revision,mesh):
    path=Path(path)
    if revision!=cache_key(path):raise ValueError('The model changed. Reload its preview.')
    folder=DATA/'model-scenes'/revision;manifest=read_json(folder/'scene.json',{})
    if not any(m['id']==mesh for m in manifest.get('meshes',[])):raise ValueError('Preview mesh not found')
    return folder/f'{mesh}.bin'
