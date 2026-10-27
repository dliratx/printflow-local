import asyncio, io, json, zipfile
from types import SimpleNamespace
import pytest
from printflow import marketplace as m
from printflow.common import Events

def run(coro):return asyncio.run(coro)

def test_sources_canonicalization_and_host_boundary():
    assert m.canonical('https://www.printables.com/model/3161-3d-benchy/files?lang=en')=='https://www.printables.com/model/3161-3d-benchy'
    for url in ['http://127.0.0.1/x.stl','https://makerworld.com.evil.test/en/models/1','file:///C:/x.stl','https://user:pass@printables.com/model/1','https://printables.com:8840/model/1']:
        with pytest.raises(ValueError):m.provider_for(url)
    for url in ['https://127.0.0.1/x.stl','https://localhost/x.stl','https://files.printables.com.evil.test/x.stl']:
        with pytest.raises(ValueError):m.allowed_url(url)

def test_metadata_extracts_only_model_downloads_and_keeps_unknown_license():
    item=m.entry('https://www.printables.com/model/123-widget')
    html=b'''<meta property="og:title" content="Widget"><meta name="author" content="Creator">
    <a href="https://files.printables.com/a.stl">STL</a><a href="https://files.printables.com/a.gcode">Gcode</a>
    <a href="http://127.0.0.1/private.stl">private</a><a href="https://evil.test/a.3mf">unexpected</a>'''
    parsed=m.page_metadata(item,html)
    assert parsed['title']=='Widget' and parsed['author']=='Creator' and parsed['license'] is None
    assert len(parsed['files'])==1 and parsed['files'][0]['name']=='a.stl'

def test_zip_import_rejects_traversal_and_ignores_gcode():
    def package(entries):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:
            for name,body in entries:z.writestr(name,body)
        return b.getvalue()
    assert m.unpack(package([('folder/a.stl',b'model'),('printer.gcode',b'G28')]),'models.zip')==[('a.stl',b'model')]
    with pytest.raises(ValueError,match='Unsafe'):m.unpack(package([('../a.stl',b'model')]),'bad.zip')
    with pytest.raises(ValueError,match='20 models'):m.unpack(package([(str(i)+'.stl',b'x') for i in range(21)]),'many.zip')

def test_search_filters_duplicate_external_results_and_never_invents_metadata(monkeypatch):
    async def host(*args,**kw):
        assert args==('POST','/discover')
        return SimpleNamespace(json=lambda:{'items':[
            {'url':'https://www.printables.com/model/1-model','title':'Model'},
            {'url':'https://www.printables.com/model/1-model/files','title':'Duplicate'},
            {'url':'https://evil.test/model/2','title':'Other'},
            {'url':'https://makerworld.com/en/models/123','title':'Wrong source'}]})
    monkeypatch.setattr(m,'portal',lambda:SimpleNamespace(host=host));monkeypatch.setattr(m,'search_cache',{});monkeypatch.delenv('PRINTFLOW_SEARCH_URL',raising=False)
    r=run(m.search('fixture','printables'))
    assert len(r['items'])==1 and r['partial'] is True
    assert r['items'][0]['license'] is None and not r['items'][0]['files']

def test_blocked_source_becomes_explicit_download_fallback(monkeypatch):
    async def fetch(*a,**kw):raise ValueError('This source requires its website')
    monkeypatch.setattr(m,'fetch',fetch)
    item=run(m.inspect('https://makerworld.com/en/models/12-fixture','Original title'))
    assert item['title']=='Original title' and item['access']=='source_download' and not item['files']

def test_import_retains_bytes_source_and_deduplicates(monkeypatch,tmp_path):
    fake=SimpleNamespace(files=[],folders=['Unsorted'],store_path=tmp_path/'library.json',events=Events())
    monkeypatch.setattr(m,'portal',lambda:fake);monkeypatch.setattr(m,'ROOT',tmp_path);monkeypatch.setattr(m,'store',tmp_path/'sources.json');monkeypatch.setattr(m,'records',{'saved':[]})
    item=m.entry('https://www.printables.com/model/123-test');item.update(author='Creator',license='CC BY 4.0')
    content=b'solid test\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid test'
    a=run(m.save_models(item,content,'original.stl','Unsorted'));b=run(m.save_models(item,content,'original.stl','Unsorted'))
    f=a['files'][0]
    assert (tmp_path/'models'/f['path']).read_bytes()==content
    assert f['source']['author']=='Creator' and b['files'][0]['id']==f['id'] and len(fake.files)==1
    assert not hasattr(fake,'printers')

def test_fetch_rejects_private_dns_before_request(monkeypatch):
    monkeypatch.setattr(m.socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError,match='Private network'):run(m.fetch('https://files.printables.com/a.stl'))

def test_large_zip_allows_explicit_subset_without_extracting_other_models():
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for i in range(25):z.writestr(f'variant-{i}/part.stl',str(i).encode())
    data=stream.getvalue()
    assert m.unpack(data,'archive.zip',[3,20])==[('part.stl',b'3'),('part.stl',b'20')]
    for indices in [[],[1,1],[99],['3']]:
        with pytest.raises(ValueError):m.unpack(data,'archive.zip',indices)


def test_search_failure_is_not_cached_as_empty_and_includes_source_fallback(monkeypatch):
    calls=[]
    async def host(*args,**kw):calls.append(kw);raise ValueError('Search account unavailable')
    monkeypatch.setattr(m,'portal',lambda:SimpleNamespace(host=host));monkeypatch.setattr(m,'search_cache',{});monkeypatch.delenv('PRINTFLOW_SEARCH_URL',raising=False)
    for _ in range(2):
        result=run(m.search('tesla roadster','makerworld'))
        assert result['status']=='error' and result['warnings']==['Search account unavailable']
        assert result['source_links'][0]['url'].endswith('tesla%20roadster')
    assert len(calls)==2 and not m.search_cache


def test_successful_search_cache_keeps_source_filter(monkeypatch):
    calls=[]
    async def host(*a,**kw):calls.append(kw);return SimpleNamespace(json=lambda:{'items':[]})
    monkeypatch.setattr(m,'portal',lambda:SimpleNamespace(host=host));monkeypatch.setattr(m,'search_cache',{});monkeypatch.delenv('PRINTFLOW_SEARCH_URL',raising=False)
    first=run(m.search('test','makerworld'));second=run(m.search('test','makerworld'));third=run(m.search('test','printables'))
    assert first['status']=='empty' and not first['cached'] and second['cached'] and not third['cached']
    assert len(calls)==2


def test_discovery_turn_removes_printer_and_command_capabilities():
    from printflow.discovery_search import search_config
    original={'mcp_servers':{'printflow':{'url':'http://localhost'},'snapmaker-u1':{}}}
    config=search_config(original)
    assert config['mcp_servers.printflow.enabled'] is False
    assert config['mcp_servers.snapmaker-u1.enabled'] is False
    for feature in ('shell_tool','apps','plugins','browser_use','computer_use','multi_agent'):
        assert config['features.'+feature] is False
    assert config['web_search']=='live' and original['mcp_servers']['printflow']=={'url':'http://localhost'}

def test_indexed_images_are_source_scoped_and_survive_a_blocked_inspection(monkeypatch):
    url='https://makerworld.com/en/models/123-fixture';image='https://makerworld.bblmw.com/model/photo.jpg'
    assert m.source_image(image,url)==image
    for bad in ['https://files.printables.com/other.jpg','http://makerworld.bblmw.com/a.jpg','https://makerworld.bblmw.com.evil.test/a.jpg','javascript:alert(1)']:
        assert m.source_image(bad,url) is None
    monkeypatch.setattr(m,'image_cache',{'makerworld:123':{'image':image,'image_source':'search_index'}})
    async def blocked(*a,**k):raise ValueError('Source requires its website')
    monkeypatch.setattr(m,'fetch',blocked)
    result=run(m.inspect(url));assert result['image']==image and result['access']=='source_download'

def test_pagination_removes_old_models_across_languages_and_slugs(monkeypatch):
    calls=[]
    async def host(*args,**kw):
        calls.append(kw['json']);return SimpleNamespace(json=lambda:{'items':[
            {'url':'https://makerworld.com/de/models/12-new-slug','title':'Already shown'},
            {'url':'https://www.makerworld.com/en/models/13-new','title':'New','image_url':'https://makerworld.bblmw.com/model/new.jpg'}]})
    monkeypatch.setattr(m,'portal',lambda:SimpleNamespace(host=host));monkeypatch.setattr(m,'search_cache',{});monkeypatch.delenv('PRINTFLOW_SEARCH_URL',raising=False)
    result=run(m.search('tesla','makerworld',2,['https://makerworld.com/en/models/12-old']))
    assert len(result['items'])==1 and result['items'][0]['title']=='New' and result['items'][0]['image']
    assert result['next_page']==3 and calls[0]['page']==2
    with pytest.raises(ValueError):run(m.search('tesla','all',999))
    with pytest.raises(ValueError):run(m.search('tesla','all',2,['https://evil.test/model/1']))
