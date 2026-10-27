"""Reference-based October 2026 Roadster display miniature, with explicit solids.

An original approximation from Tesla's published front/side/rear photographs.
It is not manufacturer CAD and has fixed wheels and a concealed printable belly.
"""
import json
import math
from pathlib import Path


def generate_roadster(request, destination):
    import cadquery as cq
    import trimesh
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    scale = request["parameters"]["length"] / 160

    def box(x, y, z, a, b, c):
        return cq.Workplane("XY").box(a, b, c).translate((x, y, z)).val()

    def union(shapes):
        result = shapes[0]
        for shape in shapes[1:]:
            result = result.fuse(shape)
        return result.clean()

    def section(x, width, shoulder, crown, bottom=4):
        # Matching six-edge stations retain the sharp shoulder and tapered sill.
        yz = [(-width*.72, bottom), (-width, 7), (-width, shoulder),
              (-width*.77, crown), (width*.77, crown), (width, shoulder),
              (width, 7), (width*.72, bottom)]
        return cq.Wire.makePolygon([cq.Vector(x,y,z) for y,z in yz], close=True)

    stations = [(-80,23,14,16),(-72,29,18,20),(-52,33,25,28),
                (-40,33,26,28),(-19,32,27,29),(15,32,28,30),
                (40,34,29,32),(57,34,30,32),(76,32,28,30),(80,30,27,29)]
    body = cq.Solid.makeLoft([section(*s) for s in stations], ruled=False)
    # The central belly reaches the bed but is hidden behind the visible sills.
    belly = box(0,0,3.5,133,39,7)
    body = body.fuse(belly)

    # Glass canopy follows the photographed side silhouette, with a long screen.
    def cabin_section(x,w,top):
        pts=[(x,-w,24),(x,-w*.77,top-1),(x,-w*.52,top),
             (x,w*.52,top),(x,w*.77,top-1),(x,w,24)]
        return cq.Wire.makePolygon([cq.Vector(*v) for v in pts],close=True)
    canopy = cq.Solid.makeLoft([cabin_section(*s) for s in
        [(-45,27,27),(-32,27,33),(-14,25,40),(3,25,41),(20,25,40.6),(35,26,38),(49,27,32),(57,27,30)]],ruled=False)
    outer = body.fuse(canopy)
    # Two white roof rails leave a panoramic dark windscreen/roof; a thin B pillar.
    rails=[]
    for side in (-1,1):
        points=[cq.Vector(x,side*y,z) for x,y,z in [(-43,26,27),(-13,19.3,39.2),(18,19.4,39.7),(41,23,34)]]
        for a,b in zip(points,points[1:]):
            axis=b-a
            rails.append(cq.Solid.makeCylinder(.8,axis.Length,a,axis.normalized()))
        rails += [cq.Solid.makeSphere(.8,p) for p in points]
    rail_mask=union(rails).intersect(canopy)
    pillar_mask = union([box(18,s*26,32,1.2,12,17) for s in (-1,1)])
    glass = canopy.cut(body).cut(rail_mask).cut(pillar_mask)

    black = [glass]
    white_wheels=[]
    all_tires=[]
    # Wheels are fixed, tangent to the ground with a 0.4 mm flattened contact.
    for x,r in [(-50,12.3),(54,12.7)]:
        z=r-.4
        for side in (-1,1):
            y=side*27.0
            axis=cq.Vector(0,side,0)
            tire=cq.Solid.makeCylinder(r,7.2,cq.Vector(x,y,z),axis)
            tire=tire.cut(box(x,y,-8,35,35,16))
            # Cut a shallow wheel well around the visible upper tire, then fill
            # with the tire solid so no unsupported decorative skin remains.
            arch=cq.Solid.makeCylinder(r+.65,10,cq.Vector(x,side*26.5,z),axis)
            outer=outer.cut(arch).fuse(tire)
            axle=cq.Solid.makeCylinder(3.5,10,cq.Vector(x,side*20,z),axis)
            outer=outer.fuse(axle)
            black.append(axle)
            black.append(tire)
            all_tires.append(tire)
            disk=cq.Solid.makeCylinder(r*.73,1.3,cq.Vector(x,side*33.0,z),axis)
            # Five broad blades survive a 0.4 mm nozzle; black spokes cut them.
            spokes=[]
            for angle in range(0,360,72):
                a=math.radians(angle)
                spoke=box(x+r*.4,side*33.2,z,r*.9,3,1.5)
                spoke=spoke.rotate((x,0,z),(x,1,z),angle)
                spokes.append(spoke)
            spokes.append(cq.Solid.makeCylinder(2,3,cq.Vector(x,side*32,z),axis))
            disk=disk.cut(union(spokes)).intersect(tire)
            white_wheels.append(disk)

    # Dark sill and front/rear fascia are embedded color regions, not cavities.
    black += [outer.intersect(box(0,s*32,5.2,116,7,5.5)) for s in (-1,1)]
    black += [outer.intersect(box(-77,0,8.3,11,65,9)),
              outer.intersect(box(77,0,13.5,10,67,19))]
    dark=union(black)
    rim=union(white_wheels)
    dark=dark.cut(rim)
    # Thin front lightbar and rear red lightbar use continuous printable inlays.
    light=outer.intersect(box(-78,0,14.7,6,49,1.0))
    dark=dark.cut(light)
    tail=outer.intersect(box(78,0,25,6,61,1.25))
    # Add four recessed rear thruster circles, backed by solid material.
    for y in (-18,-6,6,18):
        cut=cq.Solid.makeCylinder(1.6,1.1,cq.Vector(80,y,16),cq.Vector(-1,0,0))
        outer=outer.cut(cut); dark=dark.cut(cut)
    dark=dark.cut(tail)
    white=outer.cut(dark).cut(tail).fuse(rim).fuse(light).clean()
    # Shallow engraved door seams and hood creases. No detached movable parts.
    for side in (-1,1):
        seam=box(18,side*33,18,.5,6,18)
        white=white.cut(seam)
    solids=[dark.clean(),tail.clean(),white.clean()]
    names=["glass_tires_and_trim","rear_lightbar","body_and_wheel_blades"]
    colors=request["colors"]
    parts=[]
    all_scaled=[]
    mesh_checks=[]
    def checked_export(solid,path):
        cq.exporters.export(solid,str(path),tolerance=.025,angularTolerance=.08)
        mesh=trimesh.load(path,force="mesh")
        # CAD tessellation can emit degenerate float32 triangles at tangencies.
        # Weld at 0.00001 mm, remove duplicate/zero-area faces, never fill holes.
        mesh.merge_vertices(digits_vertex=5)
        mesh.update_faces(mesh.nondegenerate_faces());mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
        if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume<=0:
            raise ValueError("The exported mesh is not a closed oriented solid: "+path.name)
        mesh.export(path)
        mesh_checks.append({"file":path.name,"triangles":len(mesh.faces),"watertight":True,"positive_volume":True})
    for i,(name,solid) in enumerate(zip(names,solids)):
        solid=solid.scale(scale)
        if not solid.isValid() or solid.Volume()<=0:
            raise ValueError("Invalid Roadster color region: "+name)
        bb=solid.BoundingBox()
        if bb.zmin < -.01 or any(v>limit-12 for v,limit in zip((bb.xlen,bb.ylen,bb.zlen),request["printer"]["build_volume"])):
            raise ValueError("Roadster geometry is outside the printable volume")
        checked_export(solid,out/(name+".stl"))
        parts.append({"name":name,"file":name+".stl","quantity":1,"dimensions":[round(bb.xlen,3),round(bb.ylen,3),round(bb.zlen,3)],"color":colors[i],"planned_tool":i,"preserve_assembly_origin":True})
        all_scaled.append(solid)
    combined=union(all_scaled)
    if not combined.isValid(): raise ValueError("Roadster assembly is invalid")
    if len(combined.Solids())!=1:
        raise ValueError(f"Roadster has {len(combined.Solids())} disconnected solids; revise geometry before printing")
    checked_export(combined,out/"assembled.stl")
    cq.exporters.export(cq.Compound.makeCompound(all_scaled),str(out/"model.step"))
    notes=["Original reference-based approximation of the October 2026 Roadster, not factory CAD.",
           "Fixed wheels, closed doors, concealed flat belly and recessed rear thrusters. No moving assembly or post-print gluing.",
           "White, black and red PLA approximate the photographed colors; opaque PLA cannot reproduce metallic wheels or gold-tinted glass.",
           "Keep the common part origins. Inspect front/rear overhangs and compare supports before slicing."]
    manifest={"engine":"CadQuery 2.8.0","parts":parts,"notes":notes,"request":request,
              "assembly":{"source":"assembled.stl","parts":parts,"colors":colors,"name":request["name"]},
              "geometry_checks":{"valid":True,"connected_solids":1,"volume_mm3":combined.Volume(),"meshes":mesh_checks},
              "reference":"https://www.tesla.com/roadster","color_note":"Explicit color solids in a shared coordinate system. Native U1 assembly preparation is required."}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    (out/"parameters.json").write_text(json.dumps(request,indent=2),encoding="utf-8")
    (out/"model.py").write_text('from pathlib import Path\nimport json\nfrom printflow.design_geometry import generate\np=Path(__file__).resolve().parent\ngenerate(json.loads((p/"parameters.json").read_text()),p/"regenerated")\n',encoding="utf-8")
    return manifest
