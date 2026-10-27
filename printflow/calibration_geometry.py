"""Fixed, inspectable diagnostic solids. Runs only in the isolated CAD worker."""
import math
from pathlib import Path
from .calibration_catalog import get_test

def generate_coupon(identifier,destination):
    import cadquery as cq
    t=get_test(identifier)
    if t['mode']!='coupon':raise ValueError('This test does not use a generated coupon')
    def box(w,d,h,x=0,y=0,z=0):
        return cq.Workplane('XY').box(w,d,h,centered=(False,False,False)).translate((x,y,z))
    def cylinder(r,h,x,y,z=0):return cq.Workplane('XY').circle(r).extrude(h).translate((x,y,z))
    shapes=[]
    if identifier=='overhang':
        base=box(96,60,2)
        for i,angle in enumerate([35,45,55,65,75]):
            run=12*math.tan(math.radians(angle))
            # YZ section; lower sloping face is exactly angle degrees from Z.
            arm=cq.Workplane('YZ').polyline([(6,2),(10,2),(10,8),(10+run,20),(7+run,20),(7,8),(6,8)]).close().extrude(8).translate((5+i*18,0,0))
            base=base.union(arm)
        shapes=[base]
    elif identifier=='bridges':
        for i,span in enumerate([10,20,30,40,50]):
            y=i*17
            shape=box(span+14,12,2,0,y)
            shape=shape.union(box(5,8,12,2,y+2,2)).union(box(5,8,12,7+span,y+2,2))
            shape=shape.union(box(span+10,8,2,2,y+2,14));shapes.append(shape)
    elif identifier=='first_layer':
        shapes=[box(20,20,.2,x,y) for x,y in [(0,0),(80,0),(40,40),(0,80),(80,80)]]
    elif identifier=='stringing':
        base=box(54,38,1.6)
        for x,y in [(7,7),(47,7),(7,31),(47,31)]:base=base.union(cylinder(2,28.4,x,y,1.6))
        shapes=[base]
    elif identifier=='surface':shapes=[box(30,30,12)]
    elif identifier=='fine_features':
        base=box(58,30,2)
        for i,width in enumerate([.4,.6,.8,1,1.2]):base=base.union(box(width,16,12,6+i*11,10,2))
        for i,d in enumerate([1.2,2,3]):base=base.union(cylinder(d/2,12,12+i*15,5,2))
        shapes=[base]
    elif identifier=='dimensions':
        shape=box(20,20,20)
        for x,y,d in [(5,5,5),(12,12,10)]:shape=shape.cut(cylinder(d/2,22,x,y,-1))
        shapes=[shape]
    elif identifier=='clearance':
        shape=box(70,14,7)
        for i,gap in enumerate([.15,.20,.25,.30,.40]):shape=shape.cut(cylinder((5+gap)/2,9,7+i*14,7,-1))
        # Handle stays clear of the holes; the circular gauge length is 10 mm.
        pin=cylinder(4,2,7,25).union(cylinder(2.5,10,7,25,2));shapes=[shape,pin]
    elif identifier=='support_removal':
        base=box(38,28,2)
        post=box(6,18,16,4,5,2)
        roof=box(28,18,3,4,5,18)
        shapes=[base.union(post).union(roof)]
    else:raise ValueError('Unknown coupon geometry')
    solids=[solid for shape in shapes for solid in shape.solids().vals()]
    if not solids or any(not s.isValid() or s.Volume()<=0 for s in solids):raise ValueError('Invalid calibration solid')
    compound=cq.Compound.makeCompound(solids)
    target=Path(destination);target.parent.mkdir(parents=True,exist_ok=True)
    cq.exporters.export(compound,str(target),tolerance=.015,angularTolerance=.1)
    return {'test_id':identifier,'version':t['version'],'solid_count':len(solids),
            'dimensions':[round(getattr(compound.BoundingBox(),k),4) for k in ('xlen','ylen','zlen')]}
