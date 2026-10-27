"""Static plate/axonometric images from emitted extrusion paths, never mesh art."""
from __future__ import annotations
import hashlib
import math
import re
import threading
import uuid
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from .common import DATA

NUMBER=r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
VALUES=re.compile(r'([XYZEFIJKR])\s*('+NUMBER+r')')
COLORS={'support':'#259BD4','brim':'#DF902E','tower':'#AF6CE3'}
RENDER_LOCK=threading.Lock()

def metadata(path):
    # Orca writes its palette and effective settings AFTER the extrusion paths.
    # Read them first so the whole image uses the actual logical-tool colors.
    info={}
    with Path(path).open(encoding='utf-8',errors='replace') as f:
        for raw in f:
            if raw.startswith('; filament_colour = '):info['colors']=[x.strip() for x in raw.split('=',1)[1].strip().split(';')]
            elif raw.startswith('; estimated printing time (normal mode) = '):info['time']=raw.split('=',1)[1].strip()
            elif raw.startswith('; layer_height = '):info['layer_height']=raw.split('=',1)[1].strip()
            elif raw.startswith('; max_z_height: '):
                try:info['max_z']=float(raw.split(':',1)[1])
                except ValueError:pass
    return info

def feature(role):
    r=role.lower()
    if 'support' in r:return 'support'
    if 'brim' in r or 'skirt' in r:return 'brim'
    if 'tower' in r or 'prime' in r:return 'tower'
    return 'model'

def segments(path,info):
    xyz=[0.,0.,0.];e=0.;absolute=True;absolute_e=True;role='Custom';tool=0;plane='G17'
    with Path(path).open(encoding='utf-8',errors='replace') as f:
        for raw in f:
            if raw.startswith('; FEATURE: '):role=raw[11:].strip()
            elif raw.startswith(';TYPE:'):role=raw[6:].strip()
            elif raw.startswith('; filament_colour = '):info['colors']=[x.strip() for x in raw.split('=',1)[1].strip().split(';')]
            elif raw.startswith('; estimated printing time (normal mode) = '):info['time']=raw.split('=',1)[1].strip()
            elif raw.startswith('; layer_height = '):info['layer_height']=raw.split('=',1)[1].strip()
            line=raw.split(';',1)[0].strip()
            if not line:continue
            command=line.split()[0]
            if command=='EXCLUDE_OBJECT_DEFINE' and 'NAME=' in line:
                info.setdefault('objects',set()).add(line.split('NAME=',1)[1].split()[0])
            if command=='G90':absolute=True
            elif command=='G91':absolute=False
            elif command=='M82':absolute_e=True
            elif command=='M83':absolute_e=False
            elif command in {'G17','G18','G19'}:plane=command
            elif re.fullmatch(r'T\d+',command):tool=int(command[1:])
            elif command=='G92':
                v={k:float(n) for k,n in VALUES.findall(line)}
                xyz=[v.get(k,xyz[i]) for i,k in enumerate('XYZ')];e=v.get('E',e)
            elif command in {'G0','G00','G1','G01','G2','G02','G3','G03'}:
                v={k:float(n) for k,n in VALUES.findall(line)}
                end=[v.get(k,xyz[i]) if absolute else xyz[i]+v.get(k,0) for i,k in enumerate('XYZ')]
                ne=v.get('E',e if absolute_e else 0);de=ne-e if absolute_e else ne
                if 'E' in v:e=ne if absolute_e else e+ne
                if de>0 and role.lower()!='custom':
                    points=[xyz,end]
                    if command in {'G2','G02','G3','G03'}:
                        if plane!='G17' or 'R' in v or not any(k in v for k in ['I','J']):raise ValueError('This arc format needs native Orca preview; no approximate image was generated.')
                        cx,cy=xyz[0]+v.get('I',0),xyz[1]+v.get('J',0)
                        r=math.hypot(xyz[0]-cx,xyz[1]-cy);a=math.atan2(xyz[1]-cy,xyz[0]-cx);b=math.atan2(end[1]-cy,end[0]-cx)
                        sweep=(b-a)%(2*math.pi)
                        if command in {'G2','G02'}:sweep=-((a-b)%(2*math.pi))
                        if abs(sweep)<1e-8:sweep=(-1 if command in {'G2','G02'} else 1)*2*math.pi
                        steps=max(2,math.ceil(abs(sweep)*r/.3))
                        if steps>20000:raise ValueError('Arc exceeds the print image budget')
                        points=[[cx+r*math.cos(a+sweep*i/steps),cy+r*math.sin(a+sweep*i/steps),xyz[2]+(end[2]-xyz[2])*i/steps] for i in range(steps+1)]
                    for start,stop in zip(points,points[1:]):
                        if start[:2]!=stop[:2]:yield start,stop,feature(role),tool
                xyz=end

def font(size):
    try:return ImageFont.truetype('DejaVuSans.ttf',size)
    except OSError:return ImageFont.load_default(size=size)

def render(path):
    # Bound concurrent CPU work; a second request reuses the completed image.
    with RENDER_LOCK:return _render(path)

def _render(path):
    path=Path(path);stat=path.stat()
    if stat.st_size>400_000_000:raise ValueError('This G-code needs native Orca preview; image budget is 400 MB.')
    key=hashlib.sha256(f'{path}|{stat.st_size}|{stat.st_mtime_ns}|print-image-v3'.encode()).hexdigest()
    dest=DATA/'print-images'/f'{key}.png'
    if dest.exists():return dest
    dest.parent.mkdir(parents=True,exist_ok=True)
    info=metadata(path);im=Image.new('RGB',(1600,1040),'#111715');d=ImageDraw.Draw(im)
    d.text((40,27),'HOW THIS PLATE WILL PRINT',font=font(30),fill='#EEF6F0')
    d.text((40,75),'Actual sliced extrusion paths · model, supports and adhesion structures',font=font(18),fill='#B7C7BD')
    d.rounded_rectangle((30,126,785,886),radius=18,fill='#929C96')
    d.rounded_rectangle((805,126,1570,886),radius=18,fill='#929C96')
    d.text((55,146),'TOP VIEW · FRONT AT BOTTOM',font=font(18),fill='#263D30')
    d.text((830,146),'ANGLED VIEW',font=font(18),fill='#263D30')
    def top(v):return (70+v[0]*2.5,845-v[1]*2.35)
    height=info.get('max_z',270)
    if not math.isfinite(height) or not 0<=height<=1000:raise ValueError('Invalid G-code height')
    iso_height=540*.55+height*1.1;scale=min(690/540,620/iso_height)
    def iso(v):return (1190+(v[0]-v[1])*scale,535+iso_height*scale/2-((v[0]+v[1])*.55+v[2]*1.1)*scale)
    for n in range(0,271,30):
        for mapper in (top,iso):
            d.line([mapper((n,0,0)),mapper((n,270,0))],fill='#7E8D83',width=1)
            d.line([mapper((0,n,0)),mapper((270,n,0))],fill='#7E8D83',width=1)
    counts={};seen=0
    for start,end,kind,tool in segments(path,info):
        if any(not math.isfinite(n) for n in start+end):raise ValueError('Non-finite G-code coordinate')
        if any(abs(n)>1000 for n in start+end):raise ValueError('G-code coordinates exceed image bounds')
        counts[kind]=counts.get(kind,0)+1;seen+=1
        if seen>5_000_000:raise ValueError('This G-code needs native Orca preview; image segment budget exceeded.')
        palette=info.get('colors',[]);color=palette[tool] if tool<len(palette) and re.fullmatch('#[0-9A-Fa-f]{6}',palette[tool]) else '#477464'
        color=COLORS.get(kind,color)
        # Every emitted segment is drawn. The raster is a schematic, not a surface simulation.
        for mapper in (top,iso):d.line([mapper(start),mapper(end)],fill=color,width=1)
    if not seen:raise ValueError('No labeled extrusion paths found; open this G-code in Orca.')
    y=912;x=45
    palette=info.get('colors',[])
    color_note='saved filament colors' if palette and all(re.fullmatch('#[0-9A-Fa-f]{6}',c) for c in palette) else 'unassigned tools shown green'
    for kind,label,color in [('model','Model · '+color_note,'#477464'),('support','Supports',COLORS['support']),('brim','Brim / skirt',COLORS['brim']),('tower','Prime tower',COLORS['tower'])]:
        d.ellipse((x,y,x+16,y+16),fill=color);d.text((x+25,y-3),label+(' · none' if not counts.get(kind) else ''),font=font(18),fill='#E1EBE4');x+=[420,240,260,220][['model','support','brim','tower'].index(kind)]
    objects=len(info.get('objects',[]));facts=[f"{info.get('layer_height','?')} mm layers",info.get('time','Time unavailable'),f'{objects} skippable object'+('s' if objects!=1 else '')]
    d.text((45,955),' · '.join(facts),font=font(20),fill='#81D6AE')
    d.text((45,996),'Schematic preview. Travel and firmware macros omitted; finish and support release require a physical check.',font=font(16),fill='#A5B5AA')
    temp=dest.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    try:im.save(temp,format='PNG');temp.replace(dest)
    finally:temp.unlink(missing_ok=True)
    return dest
