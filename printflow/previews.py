"""Bounded, read-only STL / 3MF previews. Sources are never rewritten.

3MF transforms follow https://github.com/3MFConsortium/spec_core (row vectors).
"""
from __future__ import annotations
import hashlib, io, json, math, posixpath, re, struct, zipfile
from pathlib import Path
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from .common import DATA, read_json, save_json

LIMIT=500000
UNITS={'micron':.001,'millimeter':1.,'centimeter':10.,'inch':25.4,'foot':304.8,'meter':1000.}
DEFAULT='#8BA8D8'
def local(tag): return tag.rsplit('}',1)[-1]
def attr(node,name,default=None): return next((v for k,v in node.attrib.items() if local(k)==name),default)
def color(value):
    value=str(value or '')
    return value[:7].upper() if re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?',value) else DEFAULT

def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper(): raise ValueError('External XML entities are not supported')
    return ET.fromstring(data)

def archive(path):
    z=zipfile.ZipFile(path)
    if len(z.infolist())>20000 or len(set(z.namelist()))!=len(z.namelist()) or sum(i.file_size for i in z.infolist())>600_000_000:
        z.close(); raise ValueError('3MF is too large or contains duplicate entries')
    return z

def part(z,name,limit=180_000_000):
    if name not in z.namelist(): raise ValueError('A referenced 3MF model part is missing')
    if z.getinfo(name).file_size>limit: raise ValueError('3MF model part exceeds the preview limit')
    return z.read(name)

def resolve(current,target):
    target=unquote(target)
    if ':' in target or '\\' in target: raise ValueError('Only internal 3MF model references are supported')
    value=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(current),target))
    if value.startswith('../'): raise ValueError('3MF reference escapes its archive')
    return value

def matrix(value):
    a=[float(x) for x in value.split()] if value else [1,0,0,0,1,0,0,0,1,0,0,0]
    if len(a)!=12 or not all(math.isfinite(x) for x in a): raise ValueError('Invalid 3MF transform')
    return a

def project_compatibility(cfg):
    kind='u1_project' if cfg.get('printer_model')=='Snapmaker U1' else 'foreign_project' if cfg else '3mf_model'
    supported=kind=='u1_project' and bool(cfg.get('nozzle_diameter')) and all(float(n)==.4 for n in cfg['nozzle_diameter']) and not any(str(x).strip() for x in cfg.get('post_process',[]))
    return {'project_kind':kind,'preparation_supported':supported,
            'preparation_note':'Saved U1 project: material assignments and painting are preserved.' if supported else 'Open in Snapmaker Orca, select the U1 with 0.4 mm nozzles, and save a native 3MF project before automated preparation.',
            'source_printer':cfg.get('printer_model')}

def preparation_metadata(path):
    """Check project compatibility without allocating an interactive mesh.

    This is not geometry validation: preparation still requires the native
    inspection and slicing checks on the complete original file.
    """
    path=Path(path)
    if path.suffix.lower()=='.stl':return {'preparation_supported':True}
    if path.suffix.lower()!='.3mf':raise ValueError('Choose an STL or 3MF model.')
    with archive(path) as z:
        cfg=json.loads(part(z,'Metadata/project_settings.config',5_000_000)) if 'Metadata/project_settings.config' in z.namelist() else {}
    return project_compatibility(cfg)


def quick_metadata(path):
    """Library metadata must never queue full mesh builds for every visible card."""
    path=Path(path)
    if path.suffix.lower()=='.stl':
        return {'format':'STL','preparation_supported':True,'colors':[],'color_count':None,
                'note':'Open the model to inspect its complete geometry.'}
    with archive(path) as z:
        cfg=json.loads(part(z,'Metadata/project_settings.config',5_000_000)) if 'Metadata/project_settings.config' in z.namelist() else {}
    palette=list(dict.fromkeys(color(c) for c in cfg.get('filament_colour',[])))
    return project_compatibility(cfg)|{'format':'3MF','colors':palette,'color_count':len(palette) or None,
                                     'note':'Open the model to inspect geometry and plate assignments.'}

def transform(point,m): return [sum(point[j]*m[j*3+i] for j in range(3))+m[9+i] for i in range(3)]

class Sample:
    def __init__(self): self.vertices=[];self.face_colors=[];self.count=0;self.stride=1;self.low=[math.inf]*3;self.high=[-math.inf]*3
    def add(self,triangle,tint=DEFAULT):
        if len(triangle)!=3 or any(not math.isfinite(n) for v in triangle for n in v): raise ValueError('Model contains invalid coordinates')
        for v in triangle:
            for i,n in enumerate(v): self.low[i]=min(self.low[i],n);self.high[i]=max(self.high[i],n)
        if self.count%self.stride==0:self.vertices.extend(triangle);self.face_colors.append(tint)
        self.count+=1
        if len(self.face_colors)>LIMIT:
            raise ValueError("This model exceeds the interactive preview limit of 500,000 triangles. Open the original in Orca to inspect its complete surface.")
        if self.count>5_000_000: raise ValueError('Model exceeds five million preview triangles')
    def finish(self):
        if not self.count: raise ValueError('No printable triangle mesh found in this file')
        dims=[self.high[i]-self.low[i] for i in range(3)];scale=max(*dims,.001);center=[(a+b)/2 for a,b in zip(self.low,self.high)]
        return {'vertices':[[round((v[i]-center[i])/scale,6) for i in range(3)] for v in self.vertices], 'face_colors':self.face_colors,'dimensions':[round(x,3) for x in dims],'triangle_count':self.count,'sampled':self.count>len(self.face_colors)}

def stl_preview(path):
    sample=Sample()
    with path.open('rb') as f:
        header=f.read(84);count=struct.unpack_from('<I',header,80)[0] if len(header)==84 else 0
        if count and path.stat().st_size==84+count*50:
            for _ in range(count):
                values=struct.unpack('<12fH',f.read(50));sample.add([list(values[i:i+3]) for i in (3,6,9)])
        else:
            f.seek(0);tri=[]
            for raw in f:
                line=raw.strip().split()
                if line[:1]==[b'vertex'] and len(line)==4:
                    tri.append([float(x) for x in line[1:]])
                    if len(tri)==3:sample.add(tri);tri=[]
            if tri: raise ValueError('Incomplete STL triangle')
    return sample.finish()|{'format':'STL','object_count':1,'color_count':None,'colors':[],'project_kind':'stl','preparation_supported':True,'preparation_note':'Choose the filament actually loaded before preparing this model.','note':'STL stores geometry; print colors are assigned during preparation.'}

def three_mf_preview(path):
    sample=Sample();documents={};instances=0;palette=[];painted=False
    with archive(path) as z:
        names=z.namelist();main='3D/3dmodel.model'
        if '_rels/.rels' in names:
            for rel in xml(part(z,'_rels/.rels',1_000_000)):
                if rel.get('Type','').endswith('/3dmodel') and rel.get('TargetMode')!='External':main=resolve('',rel.get('Target',''))
        cfg={}
        if 'Metadata/project_settings.config' in names:
            cfg=json.loads(part(z,'Metadata/project_settings.config',5_000_000))
        palette=list(dict.fromkeys(color(c) for c in cfg.get('filament_colour',[])))
        slot_colors=[color(c) for c in cfg.get('filament_colour',[])]
        assignments={}
        if 'Metadata/model_settings.config' in names:
            root=xml(part(z,'Metadata/model_settings.config',5_000_000))
            for obj in root.findall('object'):
                meta=obj.find("metadata[@key='extruder']")
                if meta is not None:
                    try: assignments[obj.get('id')]=slot_colors[int(meta.get('value','1'))-1]
                    except (ValueError,IndexError):pass
                for volume in obj.findall('part'):
                    meta=volume.find("metadata[@key='extruder']")
                    if meta is not None:
                        try: assignments[volume.get('id')]=slot_colors[int(meta.get('value','1'))-1]
                        except (ValueError,IndexError):pass
        def document(name):
            nonlocal painted
            if name not in documents:
                raw=part(z,name);root=xml(raw);painted=painted or b'paint_color' in raw or b'mmu_segmentation' in raw
                unit=UNITS.get(root.get('unit','millimeter'))
                if unit is None: raise ValueError('Unknown 3MF unit')
                objects={o.get('id'):o for o in root.findall('./{*}resources/{*}object')}
                groups={}
                for group in root.findall('./{*}resources/*'):
                    if local(group.tag) in ('basematerials','colorgroup'):
                        groups[group.get('id')]=[color(b.get('displaycolor') or b.get('color')) for b in group]
                documents[name]=(root,objects,groups,unit)
            return documents[name]
        def walk(name,oid,chain,tint,seen):
            nonlocal instances
            key=(name,oid)
            if key in seen or len(seen)>40:raise ValueError('Cyclic or excessively nested 3MF components')
            root,objects,groups,unit=document(name);obj=objects.get(oid)
            if obj is None:raise ValueError('A 3MF component references a missing object')
            tint=assignments.get(oid,tint)
            mesh=obj.find('{*}mesh')
            if mesh is not None:
                instances+=1
                if instances>10000:raise ValueError('Too many 3MF instances')
                vertices=[[float(v.get(a,'0')) for a in 'xyz'] for v in mesh.findall('./{*}vertices/{*}vertex')]
                transformed=[]
                for v in vertices:
                    for m in chain:v=transform(v,m)
                    transformed.append([n*unit for n in v])
                for tri in mesh.findall('./{*}triangles/{*}triangle'):
                    indices=[int(tri.get('v'+str(i),'0')) for i in range(1,4)]
                    if any(i<0 or i>=len(transformed) for i in indices):raise ValueError('Invalid 3MF vertex index')
                    pid=tri.get('pid',obj.get('pid'));pindex=tri.get('p1',obj.get('pindex','0'));face_tint=tint
                    try: face_tint=groups[pid][int(pindex)]
                    except (KeyError,IndexError,ValueError):pass
                    if face_tint!=DEFAULT and face_tint not in palette:palette.append(face_tint)
                    sample.add([transformed[i] for i in indices],face_tint)
            for comp in obj.findall('./{*}components/{*}component'):
                target=attr(comp,'path');next_name=resolve(name,target) if target else name
                walk(next_name,comp.get('objectid'),[matrix(comp.get('transform'))]+chain,tint,seen|{key})
        root,objects,groups,unit=document(main)
        for item in root.findall('./{*}build/{*}item'):
            if attr(item,'printable','1')=='0':continue
            target=attr(item,'path');name=resolve(main,target) if target else main
            walk(name,item.get('objectid'),[matrix(item.get('transform'))],DEFAULT,set())
        note='Object and material colors are shown; painted facets and textures should be reviewed in Orca.' if painted else 'Mesh preview includes build placement and object colors; textures are not rendered.'
        return sample.finish()|project_compatibility(cfg)|{'format':'3MF','object_count':instances,'color_count':len(palette) or None,'colors':palette,'note':note,'painted_facets':painted}

def preview(path):
    path=Path(path);stat=path.stat();key=hashlib.sha256(f'{path}|{stat.st_size}|{stat.st_mtime_ns}|preview-v5'.encode()).hexdigest()
    cache=DATA/'model-previews'/(key+'.json')
    if cache.exists():return read_json(cache,{})
    value=stl_preview(path) if path.suffix.lower()=='.stl' else three_mf_preview(path)
    # Show the known reference side of generated TripoSR meshes initially,
    # without rotating or rewriting printable geometry.
    if path.parent.parent.name=='designs' and read_json(path.parent/'manifest.json',{}).get('engine')=='TripoSR':
        value.update(view_yaw=1.15,view_tilt=.3)
    if path.stem=='overhang' and 'calibration-assets' in path.parts:
        value.update(view_yaw=-.55,view_tilt=.25)
    save_json(cache,value);return value

def metadata(value):return {k:v for k,v in value.items() if k not in ('vertices','face_colors')}

def embedded_thumbnail(path):
    # Color revisions carry the original embedded thumbnail. Render their actual
    # geometry and palette so the library cannot show a stale color image.
    if path.suffix.lower()=='.3mf' and 'revisions' not in path.parts:
        with archive(path) as z:
            choices=['Metadata/plate_1.png','Metadata/plate_1_small.png','Metadata/thumbnail.png','Metadata/thumbnail.jpg']
            if '_rels/.rels' in z.namelist():
                for rel in xml(part(z,'_rels/.rels',1_000_000)):
                    if rel.get('Type','').endswith('/thumbnail') and rel.get('TargetMode')!='External':choices.insert(0,resolve('',rel.get('Target','')))
            for name in choices:
                if name not in z.namelist() or z.getinfo(name).file_size>8_000_000:continue
                data=z.read(name)
                if data.startswith(b'\x89PNG\r\n\x1a\n'):return data,'image/png'
                if data.startswith(b'\xff\xd8\xff'):return data,'image/jpeg'
    return None

def thumbnail(path,value):
    embedded=embedded_thumbnail(path)
    if embedded:return embedded
    stat=path.stat();key=hashlib.sha256(f'{path}|{stat.st_size}|{stat.st_mtime_ns}|thumbnail-depth-v4'.encode()).hexdigest()
    cache=DATA/'model-previews'/(key+'.png')
    if cache.exists():return cache.read_bytes(),'image/png'
    from .mesh_raster import render_model
    from PIL import Image
    raster=render_model(value,960,690).resize((640,460),Image.Resampling.LANCZOS)
    buffer=io.BytesIO();raster.save(buffer,format='PNG');data=buffer.getvalue()
    cache.parent.mkdir(parents=True,exist_ok=True)
    # Atomic cache publication avoids returning a partial thumbnail to another request.
    import tempfile
    with tempfile.NamedTemporaryFile(dir=cache.parent,suffix='.png',delete=False) as output:
        temp=Path(output.name);output.write(data)
    try:temp.replace(cache)
    finally:temp.unlink(missing_ok=True)
    return data,'image/png'
