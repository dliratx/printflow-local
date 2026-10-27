"""Small deterministic depth-buffer renderer for cached model thumbnails."""
import math
from array import array
from PIL import Image


def rasterize(triangles,width,height):
    """Triangles are (three screen xyz points, RGB); larger z is nearer."""
    depth=array('f',[-math.inf])*(width*height);pixels=bytearray(width*height*4)
    for tri,rgb in triangles:
        a,b,c=tri;den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-10:continue
        xmin=max(0,math.floor(min(v[0] for v in tri)));xmax=min(width-1,math.ceil(max(v[0] for v in tri)))
        ymin=max(0,math.floor(min(v[1] for v in tri)));ymax=min(height-1,math.ceil(max(v[1] for v in tri)))
        if xmin>xmax or ymin>ymax:continue
        du=(b[1]-c[1])/den;dv=(c[1]-a[1])/den
        rgba=bytes((*rgb,255));dz=du*(a[2]-c[2])+dv*(b[2]-c[2])
        for y in range(ymin,ymax+1):
            py=y+.5;px=xmin+.5
            u=((b[1]-c[1])*(px-c[0])+(c[0]-b[0])*(py-c[1]))/den
            v=((c[1]-a[1])*(px-c[0])+(a[0]-c[0])*(py-c[1]))/den
            z=c[2]+u*(a[2]-c[2])+v*(b[2]-c[2]);index=y*width+xmin
            for _ in range(xmin,xmax+1):
                if u>=-1e-7 and v>=-1e-7 and u+v<=1.0000001 and z>depth[index]+1e-7:
                    depth[index]=z;pixels[index*4:index*4+4]=rgba
                u+=du;v+=dv;z+=dz;index+=1
    return Image.frombytes('RGBA',(width,height),bytes(pixels))


def render_model(value,width=640,height=460,yaw=None,tilt=None):
    yaw=value.get('view_yaw',-.55) if yaw is None else yaw;tilt=value.get('view_tilt',.6) if tilt is None else tilt
    cy,sy,ct,st=math.cos(yaw),math.sin(yaw),math.cos(tilt),math.sin(tilt)
    def rotate(v):
        x=v[0]*cy-v[1]*sy;y=v[0]*sy+v[1]*cy
        return (x,y*st-v[2]*ct,y*ct+v[2]*st)
    points=[rotate(v) for v in value['vertices']]
    low=[min(p[k] for p in points) for k in (0,1)];high=[max(p[k] for p in points) for k in (0,1)]
    scale=min(width*.78/max(high[0]-low[0],.0001),height*.78/max(high[1]-low[1],.0001));center=[(a+b)/2 for a,b in zip(low,high)]
    projected=[(width/2+(p[0]-center[0])*scale,height/2+(p[1]-center[1])*scale,p[2]) for p in points]
    triangles=[]
    for i in range(0,len(points),3):
        a,b,c=points[i:i+3];u=[b[k]-a[k] for k in range(3)];v=[c[k]-a[k] for k in range(3)]
        n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];length=math.sqrt(sum(x*x for x in n)) or 1
        light=.65+.35*abs(sum(x*y for x,y in zip(n,[-.35,-.5,.79]))/length)
        color=value['face_colors'][i//3];rgb=tuple(min(255,int(int(color[k:k+2],16)*light+3.8)) for k in (1,3,5))
        triangles.append((projected[i:i+3],rgb))
    return rasterize(triangles,width,height)
