"""Read 3MF XML into compact numeric arrays without a per-vertex XML tree."""
from array import array
import xml.etree.ElementTree as ET
from xml.parsers import expat

MAX_NUMERIC_BYTES = 192 * 1024 * 1024


def read_model(stream):
    stack=[]; root=None; objects={}; current=None; total=0; painted=False
    parser=expat.ParserCreate(namespace_separator='}')
    def tag(name): return '{'+name if '}' in name else name
    def forbidden(*args): raise ValueError('External XML entities and DTDs are not supported')
    parser.StartDoctypeDeclHandler=forbidden
    parser.EntityDeclHandler=forbidden
    parser.ExternalEntityRefHandler=forbidden
    def start(name,attrs):
        nonlocal root,current,total,painted
        local=name.rsplit('}',1)[-1]
        if current is not None and local=='vertex':
            current['vertices'].extend(float(attrs.get(k,'0')) for k in ('x','y','z'))
            total+=24
        elif current is not None and local=='triangle':
            index=len(current['indices'])//3
            try:current['indices'].extend(int(attrs.get(k,'0')) for k in ('v1','v2','v3'))
            except OverflowError:raise ValueError('Invalid 3MF vertex index') from None
            if 'pid' in attrs or 'p1' in attrs:
                current['properties'][index]=(attrs.get('pid'),attrs.get('p1'))
                total+=32
            painted=painted or any(k.rsplit('}',1)[-1] in ('paint_color','mmu_segmentation') for k in attrs)
            total+=12
        else:
            node=ET.Element(tag(name),{tag(k):v for k,v in attrs.items()})
            if stack:stack[-1].append(node)
            else:root=node
            stack.append(node)
            if local=='object':
                oid=attrs.get('id')
                if oid in objects:raise ValueError('Duplicate 3MF object identifiers')
                current={'vertices':array('d'),'indices':array('I'),'properties':{}}
                objects[oid]=current
        if total>MAX_NUMERIC_BYTES:raise ValueError('This model exceeds the numeric scene memory budget.')
        if len(stack)>64:raise ValueError('Excessively nested 3MF XML')
    def end(name):
        nonlocal current
        local=name.rsplit('}',1)[-1]
        if current is not None and local in ('vertex','triangle'):return
        stack.pop()
        if local=='object':current=None
    parser.StartElementHandler=start;parser.EndElementHandler=end
    while chunk:=stream.read(256*1024):parser.Parse(chunk,False)
    parser.Parse(b'',True)
    return root,objects,painted
