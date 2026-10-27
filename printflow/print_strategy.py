"""Geometry-led preparation proposals; measurements are not physical validation.

Numeric thresholds below are conservative local heuristics, not manufacturer
presets. Native material, cooling, motion and tool-change profiles stay intact.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from . import previews as p
from .mesh_stream import read_model

VERSION='2026-10-25.1'
SOURCES=[
    {'title':'OrcaSlicer auto orientation','url':'https://github.com/OrcaSlicer/OrcaSlicer/wiki/prepare_auto_orient'},
    {'title':'OrcaSlicer brim','url':'https://github.com/OrcaSlicer/OrcaSlicer/wiki/others_settings_brim'},
    {'title':'OrcaSlicer support types','url':'https://github.com/OrcaSlicer/OrcaSlicer/wiki/support_settings_support'},
    {'title':'OrcaSlicer support contact gaps','url':'https://github.com/OrcaSlicer/OrcaSlicer/wiki/support_settings_advanced'},
    {'title':'Snapmaker U1 multicolor guide','url':'https://wiki.snapmaker.com/en/snapmaker_u1/printing_guides/multi-color_printing_guide'},
    {'title':'Snapmaker PLA/PETG interfaces','url':'https://wiki.snapmaker.com/en/snapmaker_u1/printing_guides/pla_and_petg'},
]
POLICY=(
    'Inspect the source and per-object overrides before changing settings. '
    'Choose orientation before supports; protect visible faces, mating surfaces and load direction. '
    'Use brim only for adhesion risk: small/disconnected feet, tall parts or warp-prone materials. '
    'Model brim, support bases and prime-tower brim are different settings. '
    'Keep material temperature, flow, cooling, retraction, acceleration and tool priming from matching native or physically verified profiles. '
    'Do not tune every setting arbitrarily. Compare two to four purposeful alternatives and inspect emitted toolpaths. '
    'Read u1_setting_options for the installed bridge allowlist; newer upstream options may not exist in this fork. '
    'Never infer the best angle, surface quality, strength or support removability from a geometric score or slicing time alone.'
)

def guide():
    return {'version':VERSION,'sources':SOURCES,'policy':POLICY,
        'decision_order':['Actual printer, nozzle, plate and loaded material','Purpose, visible and mating surfaces, load direction',
        'Saved placement and object overrides','Contact, fit, overhangs and candidate orientations','Adhesion and support strategy',
        'Compatible measured profile or native baseline','Compare purposeful changes','Review emitted settings and print image','Record physical feedback'],
        'setting_groups':{
            'geometry':['orientation','plate placement','part separation','supports','brim'],
            'finish':['layer height','outer walls','top surfaces','seams','thin features'],
            'function':['wall thickness','infill','layer direction','fit tolerances'],
            'material_calibration':['temperature','cooling','flow ratio','volumetric flow','retraction','pressure advance'],
            'multicolor':['tool assignments','interfaces','prime tower','purge/priming','color contamination']},
        'source_policy':'Guides explain mechanisms; local thresholds are hypotheses. Recheck sources when requested, stale, or when slicer/firmware/material changes.'}

def metrics(parts):
    """parts are (vertices Nx3, triangle indices Mx3) in world mm."""
    low=np.min([v.min(0) for v,_ in parts],axis=0);high=np.max([v.max(0) for v,_ in parts],axis=0)
    area=contact=overhang=horizontal=curved=0.;count=0
    for vertices,indices in parts:
        if not np.isfinite(vertices).all():raise ValueError('Geometry contains non-finite coordinates')
        if len(indices) and (indices.min()<0 or indices.max()>=len(vertices)):raise ValueError('Invalid mesh indices')
        for start in range(0,len(indices),65536):
            t=vertices[indices[start:start+65536]]
            cross=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);norm=np.linalg.norm(cross,axis=1)
            a=norm*.5;nz=np.divide(cross[:,2],norm,out=np.zeros_like(norm),where=norm>1e-12)
            bed=np.max(t[:,:,2],axis=1)<=low[2]+.05
            down=(nz < -np.cos(np.pi/4)) & ~bed
            area+=a.sum();contact+=(a[bed]*np.abs(nz[bed])).sum();overhang+=a[down].sum()
            horizontal+=a[down & (nz < -.95)].sum();curved+=a[(abs(nz)>.1)&(abs(nz)<.95)].sum();count+=len(t)
    dims=high-low;foot=max(dims[0]*dims[1],.0001)
    return {'triangles':count,'dimensions_mm':dims.round(3).tolist(),'bounds_mm':[low.round(3).tolist(),high.round(3).tolist()],
        'surface_mm2':round(area,3),'bed_contact_mm2':round(contact,3),'contact_footprint_ratio':round(contact/foot,4),
        'unsupported_downward_mm2':round(overhang,3),'overhang_surface_ratio':round(overhang/max(area,.0001),4),
        'horizontal_overhang_ratio':round(horizontal/max(overhang,.0001),4),'sloped_surface_ratio':round(curved/max(area,.0001),4),
        'fits_u1':bool(np.all(dims<=266)),
        'limitations':['Downward-facing area excludes the bed, but is not a bridge or occlusion simulation.','Disconnected islands and visible surfaces need separate review.']}

def rotation_to_down(normal):
    a=np.asarray(normal,dtype=float);a/=np.linalg.norm(a);b=np.array([0.,0.,-1.]);c=float(a@b)
    if c>1-1e-7:return np.eye(3)
    if c<-1+1e-7:return np.diag([1.,-1.,-1.])
    v=np.cross(a,b);k=np.array([[0.,-v[2],v[1]],[v[2],0.,-v[0]],[-v[1],v[0],0.]])
    return (np.eye(3)+k+k@k/(1+c)).T # row-vector convention

def validate_rotation(value):
    r=np.asarray(value,dtype=float)
    if r.size!=9:raise ValueError('Orientation must be a 3 by 3 rotation')
    r=r.reshape(3,3)
    if not np.isfinite(r).all() or not np.allclose(r.T@r,np.eye(3),atol=1e-5) or not np.isclose(np.linalg.det(r),1,atol=1e-5):
        raise ValueError('Orientation must preserve scale and handedness')
    return r

def connected_count(triangles):
    if len(triangles)>100000:return None
    _,inverse=np.unique(triangles.reshape(-1,3),axis=0,return_inverse=True)
    parent=list(range(int(inverse.max())+1))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for a,b,c in inverse.reshape(-1,3):
        a=root(int(a));parent[root(int(b))]=a;parent[root(int(c))]=a
    return len({root(i) for i in range(len(parent))})

def stl_plan(triangles,material,purpose='display',orientation='auto'):
    t=np.asarray(triangles,dtype=float)
    if not len(t):raise ValueError('The STL has no triangles')
    vertices=t.reshape(-1,3);indices=np.arange(len(vertices)).reshape(-1,3)
    candidates=[np.eye(3)]
    cross=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);area=np.linalg.norm(cross,axis=1)
    normals=np.divide(cross,area[:,None],out=np.zeros_like(cross),where=area[:,None]>1e-12)
    # Axis directions plus dominant planar faces provide bounded, reproducible candidates.
    groups,inverse=np.unique(normals.round(2),axis=0,return_inverse=True)
    weights=np.bincount(inverse,weights=area)
    directions=[*np.eye(3),*-np.eye(3),*groups[np.argsort(weights)[-6:]]]
    for normal in directions:
        if np.linalg.norm(normal)<.9:continue
        r=rotation_to_down(normal)
        if not any(np.allclose(r,old,atol=.01) for old in candidates):candidates.append(r)
    options=[]
    for index,r in enumerate(candidates):
        m=metrics([(vertices@r,indices)]);x,y,z=m['dimensions_mm']
        score=100*m['overhang_surface_ratio']+z/max(min(x,y),1)*.25+5*(1-min(m['contact_footprint_ratio'],1))
        if m['bed_contact_mm2']<1:score+=100
        options.append({'id':str(index),'rotation':r.round(8).reshape(-1).tolist(),'metrics':m,'score':round(score,4)})
    fit=[o for o in options if o['metrics']['fits_u1']]
    if not fit:raise ValueError('No candidate fits the U1 with placement clearance. Split the model first.')
    best=min(fit,key=lambda o:o['score']);original=options[0]
    if orientation=='preserve' or purpose in {'functional','fit'}:best=original
    elif original['metrics']['fits_u1'] and best['score']>=original['score']*.9:best=original
    if not best['metrics']['fits_u1']:raise ValueError('The preserved orientation does not fit the U1. Choose a fitting orientation or split the model.')
    m=best['metrics'];islands=connected_count(t);x,y,z=m['dimensions_mm']
    stable=material.upper()=='PLA' and islands==1 and m['bed_contact_mm2']>=100 and m['contact_footprint_ratio']>=.65 and z/max(min(x,y),1)<2
    supports=bool(m['unsupported_downward_mm2']>max(2,m['surface_mm2']*.01))
    changes={'brim_type':'no_brim' if stable else 'auto_brim','enable_support':supports,
             'layer_height':.12 if m['sloped_surface_ratio']>.15 or z<20 else .16}
    if supports:changes['support_type']='normal(auto)' if m['horizontal_overhang_ratio']>.7 else 'tree(auto)'
    return {'source_type':'STL','orientation':{'mode':'preserved' if best['id']=='0' else 'geometry_candidate','selected':best,'candidates':sorted(options,key=lambda o:o['score'])},
        'objects':[{'id':'1','metrics':m,'connected_components':islands}], 'process_changes':changes,
        'decisions':[{'setting':'orientation','reason':'Lower geometric support/contact score; review visible faces before printing.' if best['id']!='0' else 'Current placement retained; functional load and mating faces take priority over geometric ranking.'},
            {'setting':'brim_type','value':changes['brim_type'],'reason':'One low PLA solid with broad flat contact.' if stable else 'Small, tall, disconnected, unverified or warp-prone contact: use native automatic brim.'},
            {'setting':'enable_support','value':supports,'reason':'Measured downward area away from the bed; native slicing resolves bridges and support paths.'}],
        'review_required':['Orientation ranking does not know the intended visible face or load direction.','Inspect supports against mating and cosmetic surfaces.']}

def project_plan(path):
    """Inspect saved build instances, preserving all native placement and painting."""
    with p.archive(path) as z:
        cfg=json.loads(p.part(z,'Metadata/project_settings.config',5_000_000));docs={};objects=[]
        main='3D/3dmodel.model'
        if '_rels/.rels' in z.namelist():
            for rel in p.xml(p.part(z,'_rels/.rels',1_000_000)):
                if rel.get('Type','').endswith('/3dmodel'):main=p.resolve('',rel.get('Target',''))
        def doc(name):
            if name not in docs:
                with z.open(name) as f:root,numeric,_=read_model(f)
                docs[name]=(root,{o.get('id'):o for o in root.findall('./{*}resources/{*}object')},numeric)
            return docs[name]
        def walk(name,oid,chain,seen):
            if (name,oid) in seen or len(seen)>32:raise ValueError('Invalid recursive model components')
            root,objs,numeric=doc(name);obj=objs[oid]
            if oid in numeric and len(numeric[oid]['indices']):
                data=numeric[oid];v=np.frombuffer(data['vertices'],dtype=np.float64).reshape(-1,3).copy()
                for transform in chain:
                    a=np.array(transform);v=v@a[:9].reshape(3,3)+a[9:]
                unit=p.UNITS.get(root.get('unit','millimeter'))
                if unit is None:raise ValueError('Unknown model units')
                yield v*unit,np.frombuffer(data['indices'],dtype=np.uint32).reshape(-1,3)
            for c in obj.findall('./{*}components/{*}component'):
                target=p.attr(c,'path');child=p.resolve(name,target) if target else name
                yield from walk(child,c.get('objectid'),[p.matrix(c.get('transform'))]+chain,seen|{(name,oid)})
        root,_,_=doc(main)
        for index,item in enumerate(root.findall('./{*}build/{*}item')):
            if p.attr(item,'printable','1')=='0':continue
            target=p.attr(item,'path');name=p.resolve(main,target) if target else main
            parts=list(walk(name,item.get('objectid'),[p.matrix(item.get('transform'))],set()))
            if parts:objects.append({'id':item.get('objectid'),'instance':index,'metrics':metrics(parts)})
        overrides=[]
        if 'Metadata/model_settings.config' in z.namelist():
            for node in p.xml(p.part(z,'Metadata/model_settings.config',5_000_000)).iter():
                settings={m.get('key'):m.get('value',m.text) for m in node.findall('metadata') if m.get('key') in {'brim_type','brim_width','brim_object_gap','enable_support','support_type','layer_height','support_top_z_distance','support_interface_spacing','outer_wall_speed'}}
                if settings:overrides.append({'scope':node.tag,'id':node.get('id'),'settings':settings})
    keys=('brim_type','brim_width','brim_object_gap','enable_support','support_type','support_top_z_distance','support_object_xy_distance','layer_height','outer_wall_speed','top_surface_speed','prime_tower_brim_width')
    return {'source_type':'3MF','objects':objects,'saved_settings':{k:cfg.get(k) for k in keys},'object_overrides':overrides,
        'orientation':{'mode':'preserved_native_layout','reason':'Keep authored plates, multi-part alignment, painting and tool-clearance layout. Do not rotate a whole packed plate as one part.'},
        'process_changes':{},'decisions':[{'setting':'brim_type','value':cfg.get('brim_type'),'origin':'saved_project','reason':'Retained from the authored project; inspect small islands before removing adhesion aids.'}],
        'review_required':['Saved layout is a baseline, not a proven optimum. Review individual objects and author instructions.','Object and plate overrides can take precedence over global changes.','A merged mesh may contain many disconnected feet; whole-object contact area cannot justify removing their brims.']}

def finish_plan(plan):
    return plan|{'version':VERSION,'sources':SOURCES,'physical_quality_verified':False,
        'preserved_native_groups':['material temperatures','cooling','flow and volumetric limits','retraction','machine acceleration','tool changes and priming','seam and wall/infill defaults unless purpose requires a change'],
        'next':'Compare two to four meaningful candidates; review effective G-code, print image and physical feedback.'}
