"""Read-only linear G-code bounds audit and selected-layer review image.

Firmware macros, travel clearance, adhesion and physical quality are not verified.
Run with the image worker environment (Pillow) and an emitted G-code path.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from PIL import Image, ImageDraw


def review(path):
    bounds={};layers={};segments={};arcs=0
    position={k:0. for k in 'XYZ'};last_e=0.;relative_xyz=False;relative_e=False;tool=0;role='Custom'
    wanted=(.2,3.08,14.96,28.04,36.08,46.16)
    pattern=re.compile(r'\b([XYZEF])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))')
    for raw in path.open(encoding='utf-8',errors='replace'):
        if raw.startswith(';TYPE:'):role=raw[6:].strip()
        line=raw.split(';',1)[0].strip()
        if line=='G90':relative_xyz=False
        elif line=='G91':relative_xyz=True
        elif line=='M82':relative_e=False
        elif line=='M83':relative_e=True
        elif re.fullmatch(r'T\d+',line):tool=int(line[1:])
        elif re.match(r'G(?:92|0?[0123])\s',line):
            values={k:float(v) for k,v in pattern.findall(line)}
            if line.startswith('G92'):
                last_e=values.get('E',last_e)
                position.update({k:v for k,v in values.items() if k in position})
                continue
            target={k:(position[k]+values.get(k,0) if relative_xyz else values.get(k,position[k])) for k in position}
            extrusion=values.get('E',0) if relative_e else values.get('E',last_e)-last_e
            if 'E' in values:last_e=values['E']
            if extrusion>0 and role!='Custom' and any(target[k]!=position[k] for k in 'XY'):
                if line.startswith(('G2 ','G3 ')):arcs+=1
                box=bounds.setdefault(role,{'min':[math.inf]*3,'max':[-math.inf]*3})
                for i,k in enumerate('XYZ'):
                    box['min'][i]=min(box['min'][i],position[k],target[k]);box['max'][i]=max(box['max'][i],position[k],target[k])
                z=round(target['Z'],4);layers[z]=layers.get(z,0)+1
                if any(abs(z-w)<.002 for w in wanted):
                    segments.setdefault(z,[]).append((position['X'],position['Y'],target['X'],target['Y'],role,tool))
            position=target
    errors=[]
    if not layers:errors.append('No print extrusion was found')
    if arcs:errors.append('Arc bounds need a separate review')
    for role,box in bounds.items():
        if min(box['min'])<-.01 or max(box['max'])>270.01:errors.append('Extrusion outside the 270 mm build volume: '+role)
    result={'passed':not errors,'errors':errors,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'layer_count':len(layers),'first_z':min(layers,default=None),'last_z':max(layers,default=None),'extrusion_bounds_by_feature_mm':bounds,
            'limits':'Linear extrusion endpoints only. Firmware macros, travel clearance and physical print quality are not verified.'}
    path.with_name('path-review.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    image=Image.new('RGB',(1800,1240),'#171d27');draw=ImageDraw.Draw(image)
    for index,(z,lines) in enumerate(sorted(segments.items())):
        left=20+(index%3)*600;top=45+(index//3)*600
        draw.rectangle((left,top,left+560,top+560),fill='#8693a5',outline='#c0c9d5',width=2)
        draw.text((left,top-25),f'Z {z:.2f} mm - actual emitted extrusion',fill='white')
        for x,y,nx,ny,role,tool in lines:
            color='#8453bb' if 'Support' in role else '#345dce' if 'tower' in role.lower() else ['#101318','#df3728','#f2eeea'][min(tool,2)]
            draw.line((left+x*2,top+540-y*2,left+nx*2,top+540-ny*2),fill=color,width=1)
    draw.text((20,1215),'Purple: supports | Blue: prime tower | Other colors: model tool assignments. Travel and firmware macros omitted.',fill='white')
    image.save(path.with_name('path-review.png'))
    return result


if __name__=='__main__':
    result=review(Path(sys.argv[1]).resolve());print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
