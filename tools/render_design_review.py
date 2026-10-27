"""Render saved geometry for review without controlling a browser or native GUI."""
import json
import math
from pathlib import Path
import sys
import numpy as np
import trimesh
from PIL import Image, ImageDraw

folder=Path(sys.argv[1]);manifest=json.loads((folder/'manifest.json').read_text())
meshes=[]
for part in manifest['parts']:
    m=trimesh.load(folder/part['file'],force='mesh')
    print(part['name'],len(m.faces),'watertight',m.is_watertight,'volume',round(m.volume,2))
    if not m.is_watertight or m.volume<=0:raise ValueError('Non-manifold or inverted color part')
    rgb=tuple(bytes.fromhex(part['color'].lstrip('#')))
    meshes.append((m.triangles,rgb))
image=Image.new('RGB',(1800,1200),'#131820');draw=ImageDraw.Draw(image)
for cell,(yaw,tilt,title) in enumerate([(-2.3,.48,'Front three-quarter'),(0,.12,'Side profile'),(.7,.45,'Rear three-quarter'),(0,1.55,'Top view')]):
    x0=(cell%2)*900;y0=(cell//2)*600
    draw.text((x0+24,y0+20),title,fill='#ffffff')
    cy,sy,ct,st=math.cos(yaw),math.sin(yaw),math.cos(tilt),math.sin(tilt)
    transform=np.array([[cy,-sy,0],[sy*st,cy*st,-ct],[sy*ct,cy*ct,st]])
    groups=[(tri@transform.T,color) for tri,color in meshes]
    verts=np.concatenate([g[0].reshape(-1,3) for g in groups]);lo=verts.min(0);hi=verts.max(0)
    scale=min(810/(hi[0]-lo[0]),470/(hi[1]-lo[1]));center=(lo+hi)/2
    zbuffer=np.full((600,900),-np.inf);pixels=np.zeros((600,900,3),dtype=np.uint8);pixels[:]=[19,24,32]
    for triangles,color in groups:
        normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-12)
        illumination=.5+.5*np.abs(normals@np.array([-.35,-.5,.79]))
        for tri,shade in zip(triangles,illumination):
            points=np.array([(450+(p[0]-center[0])*scale,315+(p[1]-center[1])*scale) for p in tri])
            # Lift the very dark plastic enough to inspect its shape.
            tint=tuple(min(255,int((c*.85+25)*shade)) for c in color)
            xmin=max(0,int(points[:,0].min()));xmax=min(899,int(points[:,0].max())+1)
            ymin=max(45,int(points[:,1].min()));ymax=min(599,int(points[:,1].max())+1)
            if xmin>=xmax or ymin>=ymax:continue
            a,b,c=points;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(den)<1e-8:continue
            yy,xx=np.mgrid[ymin:ymax+1,xmin:xmax+1];xx=xx+.5;yy=yy+.5
            u=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
            v=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den
            w=1-u-v;depth=u*tri[0,2]+v*tri[1,2]+w*tri[2,2]
            z=zbuffer[ymin:ymax+1,xmin:xmax+1];mask=(u>=0)&(v>=0)&(w>=0)&(depth>z)
            z[mask]=depth[mask];pixels[ymin:ymax+1,xmin:xmax+1][mask]=tint
    image.paste(Image.fromarray(pixels),(x0,y0));draw=ImageDraw.Draw(image);draw.text((x0+24,y0+20),title,fill='#ffffff')
out=folder/'review.png';image.save(out);print(out.resolve())
