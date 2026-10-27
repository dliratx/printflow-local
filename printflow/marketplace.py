"""Personal model discovery and explicit imports. Never proxies a login or executes downloads."""
from __future__ import annotations
import asyncio, hashlib, io, ipaddress, os, re, socket, stat, uuid, zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET
import httpx
from fastapi import APIRouter, File, Form, Request, UploadFile
from .common import ROOT, DATA, now, read_json, save_json
from . import previews

router=APIRouter()
store=DATA/'marketplace.json'
records=read_json(store,{'saved':[]})
PROVIDERS={
 'makerworld':{'name':'MakerWorld','host':'makerworld.com','path':r'^/[a-z-]+/models/\d+','search':'https://makerworld.com/en/search/models?keyword='},
 'printables':{'name':'Printables','host':'printables.com','path':r'^/model/\d+','search':'https://www.printables.com/search/models?q='},
 'thingiverse':{'name':'Thingiverse','host':'thingiverse.com','path':r'^/thing:\d+','search':'https://www.thingiverse.com/search?q='},
 'cults':{'name':'Cults','host':'cults3d.com','path':r'^/[a-z]+/3d-model/','search':'https://cults3d.com/en/search?q='},
 'myminifactory':{'name':'MyMiniFactory','host':'myminifactory.com','path':r'^/object/','search':'https://www.myminifactory.com/search/?query='},
 'thangs':{'name':'Thangs','host':'thangs.com','path':r'^/(designer/|mythangs/)','search':'https://thangs.com/search/'},
 'benchy':{'name':'3DBenchy','host':'3dbenchy.com','path':r'^/(download/?)?$','search':'https://www.3dbenchy.com/download/'}
}
ASSET_HOSTS={'makerworld.bblmw.com','makerworld.bblcdn.com','files.printables.com','media.printables.com','cdn.thingiverse.com','thingiverse-production-new.s3.amazonaws.com','cdn2.myminifactory.com','images.cults3d.com','github.com','codeload.github.com'}
MAX_BYTES=250*1024**2
search_cache={}
image_cache={}
IMAGE_HOSTS={
 'makerworld':{'makerworld.bblmw.com','makerworld.bblcdn.com'},
 'printables':{'media.printables.com','files.printables.com','media.prusaprinters.org'},
 'thingiverse':{'cdn.thingiverse.com','thingiverse-production-new.s3.amazonaws.com'},
 'cults':{'images.cults3d.com'},'myminifactory':{'cdn2.myminifactory.com','cdn.myminifactory.com'},
 'thangs':{'thangs.com','www.thangs.com'},'benchy':{'3dbenchy.com','www.3dbenchy.com'}}

def portal():
    from . import api
    return api

def provider_for(url):
    p=urlsplit(str(url));host=(p.hostname or '').lower().removeprefix('www.')
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443):raise ValueError('Use a public HTTPS model page')
    for key,v in PROVIDERS.items():
        if host==v['host'] and re.search(v['path'],p.path):return key
    raise ValueError('Use a model page from one of the listed sources')

def canonical(url):
    key=provider_for(url);p=urlsplit(url);path=p.path.rstrip('/')
    if key in {'printables','makerworld'}:
        match=re.match(PROVIDERS[key]['path']+r'[^/]*',path);path=match.group(0)
    return urlunsplit(('https',p.netloc.lower(),path or '/', '', ''))

def model_identity(url):
    key=provider_for(url);path=urlsplit(url).path
    if key in {'makerworld','printables','thingiverse'}:
        return key+':'+re.search(r'(?:models?/|thing:)(\d+)',path).group(1)
    return key+':'+path.rstrip('/')

def source_image(image,url):
    if not isinstance(image,str) or len(image)>3000:return None
    try:
        p=urlsplit(image)
        if p.scheme!='https' or p.username or p.password or p.port not in (None,443):return None
        if (p.hostname or '').lower() not in IMAGE_HOSTS[provider_for(url)]:return None
    except ValueError:return None
    return image

def search_page(page,exclude):
    if type(page)!=int or not 1<=page<=8:raise ValueError('Search pages must be between 1 and 8')
    if not isinstance(exclude,list) or len(exclude)>200:raise ValueError('Too many previous search results')
    return page,list(dict.fromkeys(canonical(url) for url in exclude))

def entry(url,title='',description=''):
    url=canonical(url);key=provider_for(url)
    return {'id':hashlib.sha256(url.encode()).hexdigest()[:20],'url':url,'provider':key,
            'title':str(title or urlsplit(url).path.split('/')[-1].replace('-',' '))[:240],
            'description':str(description)[:800],'author':None,'license':None,'image':None,'files':[],
            'access':'uninspected','checked_at':None}

def allowed_url(url,extra_hosts=()):
    p=urlsplit(url);host=(p.hostname or '').lower()
    domains=ASSET_HOSTS|{v['host'] for v in PROVIDERS.values()}|{'www.'+v['host'] for v in PROVIDERS.values()}|set(extra_hosts)
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or host not in domains:
        raise ValueError('This download host is not supported. Download from the source and attach the file here')
    return host

async def fetch(url,limit=3_000_000,extra_hosts=()):
    # Validate every redirect; provider responses cannot target LAN or local services.
    async with httpx.AsyncClient(timeout=25,trust_env=False,headers={'User-Agent':'PrintFlow/0.3 (personal model library)'}) as client:
        for _ in range(5):
            host=allowed_url(url,extra_hosts)
            addresses=await asyncio.to_thread(socket.getaddrinfo,host,443,type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('Private network downloads are not allowed')
            async with client.stream('GET',url) as r:
                if r.is_redirect:
                    url=urljoin(url,r.headers.get('location',''));continue
                if r.status_code in (401,403,429):raise ValueError('This source requires its website or is limiting access. Open the source, then attach your downloaded STL, 3MF or ZIP')
                r.raise_for_status()
                if int(r.headers.get('content-length','0'))>limit:raise ValueError('The download exceeds the size limit')
                data=bytearray()
                async for chunk in r.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>limit:raise ValueError('The download exceeds the size limit')
                return bytes(data),url,r.headers.get('content-type','')
        raise ValueError('Too many download redirects')

class PageInfo(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.meta={};self.links=[];self.json=[];self.script=False;self.buffer='';self.in_title=False;self.title=''
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta':self.meta[a.get('property') or a.get('name','')]=a.get('content','')
        if tag=='a' and a.get('href'):self.links.append((a['href'],a.get('download','')))
        if tag=='title':self.in_title=True
        if tag=='script' and a.get('type')=='application/ld+json':self.script=True;self.buffer=''
    def handle_data(self,data):
        if self.script:self.buffer+=data
        if self.in_title:self.title+=data
    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False
        if tag=='script' and self.script:
            import json
            try:self.json.append(json.loads(self.buffer))
            except ValueError:pass
            self.script=False

def page_metadata(item,data):
    parser=PageInfo();parser.feed(data.decode('utf-8',errors='replace'))
    item['title']=(parser.meta.get('og:title') or parser.title or item['title'])[:240]
    item['description']=(parser.meta.get('og:description') or parser.meta.get('description') or item['description'])[:800]
    item['image']=parser.meta.get('og:image') or None
    item['author']=parser.meta.get('author') or None
    links=list(parser.links)
    def visit(v,depth=0):
        if depth>8:return
        if isinstance(v,list):
            for child in v[:100]:visit(child,depth+1)
        elif isinstance(v,dict):
            author=v.get('author') or v.get('creator')
            if author and not item['author']:item['author']=(author.get('name') if isinstance(author,dict) else author) if not isinstance(author,list) else None
            if isinstance(v.get('license'),str):item['license']=v['license'][:500]
            if isinstance(v.get('contentUrl'),str):links.append((v['contentUrl'],str(v.get('name',''))))
            for key in ('@graph','encoding','associatedMedia'):visit(v.get(key),depth+1)
    for node in parser.json:visit(node)
    files=[]
    for href,name in links:
        url=urljoin(item['url'],href);suffix=Path(urlsplit(url).path).suffix.lower()
        if suffix not in {'.stl','.3mf','.zip'}:continue
        try:allowed_url(url)
        except ValueError:continue
        filename=Path(urlsplit(url).path).name
        if name and Path(name).suffix.lower()==suffix:filename=name
        if not any(f['url']==url for f in files):files.append({'id':hashlib.sha256(url.encode()).hexdigest()[:16],'name':filename[:180],'url':url})
    item['files']=files[:20];item['access']='direct' if files else 'source_download'
    if item['image']:
        try:allowed_url(item['image'])
        except ValueError:item['image']=None
    if item['author']:item['author']=str(item['author'])[:160]
    if item['provider']=='benchy':
        # Attribution verified against the creator's public license page, not inferred from a search snippet.
        item.update(title='Original 3DBenchy',author='Daniel Norée / Creative Tools',license='CC0 1.0 — https://www.3dbenchy.com/license/')
        item['image']=next((url for url,_ in parser.links if url.startswith('https://www.3dbenchy.com/') and url.endswith('3DBenchy_page_download_main_image.png')),item['image'])
    return item

async def inspect(url,title='',description=''):
    item=entry(url,title,description)
    prior=image_cache.get(model_identity(url)) or next((x for x in records['saved'] if model_identity(x['url'])==model_identity(url)),{})
    try:
        data,_,_=await fetch(item['url']);page_metadata(item,data)
    except (ValueError,httpx.HTTPError,OSError) as exc:
        item['access']='source_download';item['notice']=str(exc) if isinstance(exc,ValueError) else 'Source temporarily unavailable. Open its website and attach your download.'
    if not item.get('image') and source_image(prior.get('image'),url):
        item['image']=prior['image'];item['image_source']=prior.get('image_source','source_page')
    item['checked_at']=now();return item

@router.get('/api/marketplace')
async def overview():
    return {'providers':[{'id':k,**v} for k,v in PROVIDERS.items()], 'saved':records['saved'],
            'search_engine':'SearXNG' if os.environ.get('PRINTFLOW_SEARCH_URL') else 'Codex web search',
            'notice':'Search public model listings with your connected Codex account. Search is not a complete catalog. Check files, price and license at the source.' if not os.environ.get('PRINTFLOW_SEARCH_URL') else 'Search public model listings with your configured search service. Check files, price and license at the source.'}


def search_links(q,provider):
    from urllib.parse import quote
    return [{'id':k,'name':v['name'],'url':v['search']+(quote(q,safe='') if k!='benchy' else '')}
            for k,v in PROVIDERS.items() if provider=='all' or k==provider]


async def search(q:str='',provider:str='all',page:int=1,exclude=None):
    q=' '.join(q.split())[:160]
    if not q:raise ValueError('Enter a model name or topic')
    if provider!='all' and provider not in PROVIDERS:raise ValueError('Unknown model source')
    page,exclude=search_page(page,exclude or []);excluded={model_identity(url) for url in exclude}
    import time
    engine=os.environ.get('PRINTFLOW_SEARCH_URL','').rstrip('/')
    key=(q.casefold(),provider,engine,page,tuple(sorted(excluded)));cached=search_cache.get(key)
    if cached and time.monotonic()-cached[0]<300:return cached[1]|{'cached':True}
    selected=PROVIDERS if provider=='all' else {provider:PROVIDERS[provider]}
    results=[];engine_name='SearXNG' if engine else 'Codex web search'
    warnings=[]
    try:
        if engine:
            terms=' OR '.join('site:'+p['host'] for p in selected.values())
            async with httpx.AsyncClient(timeout=25,trust_env=False) as client:
                r=await client.get(engine+'/search',params={'q':q+' 3D printable model ('+terms+')','format':'json','pageno':page});r.raise_for_status()
                rows=r.json().get('results',[])[:60]
        else:
            result=(await portal().host('POST','/discover',json={'query':q,'provider':provider,'page':page,'exclude':exclude},timeout=120)).json()
            rows=result.get('items',[])[:60]
        for row in rows:
            if not isinstance(row,dict):continue
            try:item=entry(row.get('url',''),row.get('title',''),row.get('content',''))
            except (ValueError,TypeError):continue
            identity=model_identity(item['url'])
            if item['provider'] not in selected or identity in excluded or any(model_identity(i['url'])==identity for i in results):continue
            item['image']=source_image(row.get('image_url') or row.get('thumbnail'),item['url'])
            if item['image']:
                if len(image_cache)>500:image_cache.clear()
                item['image_source']='search_index';image_cache[identity]={'image':item['image'],'image_source':'search_index'}
            results.append(item)
    except (httpx.HTTPError,OSError,ValueError,TypeError) as exc:
        warnings.append(str(exc) if isinstance(exc,ValueError) else 'The search service is unavailable. Try again or search a source directly.')
    status='error' if warnings else 'results' if results else 'empty'
    value={'items':results,'query':q,'provider':provider,'partial':True,'status':status,
           'engine':engine_name,'warnings':warnings,'source_links':search_links(q,provider),'at':now(),'cached':False,
           'page':page,'has_more':bool(results) and page<8,'next_page':page+1 if results and page<8 else None}
    # Never cache service failures as successful zero-result searches.
    if not warnings:
        if len(search_cache)>100:search_cache.clear()
        search_cache[key]=(time.monotonic(),value)
    return value


@router.post('/api/marketplace/search')
async def search_request(request:Request):
    body=await request.json()
    return await search(str(body.get('q','')),str(body.get('provider','all')),body.get('page',1),body.get('exclude',[]))


@router.post('/api/marketplace/inspect')
async def inspect_request(request:Request):
    body=await request.json();item=await inspect(str(body.get('url','')),str(body.get('title','')),str(body.get('description','')))
    previous=next((x for x in records['saved'] if x['id']==item['id']),None)
    if previous:item['library_ids']=previous.get('library_ids',[]);records['saved'].remove(previous)
    records['saved'].append(item);save_json(store,records);return item

def saved(identifier):
    found=next((x for x in records['saved'] if x['id']==identifier),None)
    if not found:raise ValueError('Inspect and save the model page first')
    return found

def archive_models(z):
    infos=z.infolist()
    if len(infos)>2000 or sum(i.file_size for i in infos)>MAX_BYTES:raise ValueError('Archive exceeds the import limit')
    models=[]
    for index,i in enumerate(infos):
        if i.is_dir():continue
        name=i.filename.replace('\\','/')
        if name.startswith('/') or '..' in name.split('/') or ':' in name or stat.S_ISLNK(i.external_attr>>16):raise ValueError('Unsafe archive entry')
        if Path(name).suffix.lower() in {'.stl','.3mf'}:models.append({'index':index,'name':Path(name).name,'path':name,'size':i.file_size})
    if not models:raise ValueError('No STL or 3MF files found. G-code is not imported')
    return models

def unpack(data,name,selected=None):
    suffix=Path(name).suffix.lower()
    if suffix in {'.stl','.3mf'}:return [(Path(name.replace('\\','/')).name,data)]
    if suffix!='.zip':raise ValueError('Choose STL, 3MF or a ZIP containing those model files')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        models=archive_models(z)
        if selected is not None:
            if not isinstance(selected,list) or not selected or any(type(i)!=int for i in selected) or len(set(selected))!=len(selected):raise ValueError('Choose model files from the archive')
            if set(selected)-{m['index'] for m in models}:raise ValueError('Unknown archive model selection')
            models=[m for m in models if m['index'] in selected]
        if len(models)>20:raise ValueError('Import at most 20 models at a time')
        return [(m['name'],z.read(z.infolist()[m['index']])) for m in models]

async def receive_models(item,data,name,folder):
    if Path(name).suffix.lower()!='.zip':return await save_models(item,data,name,folder)
    if len(data)>MAX_BYTES:raise ValueError('The archive exceeds 250 MB')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:models=archive_models(z)
    except (zipfile.BadZipFile,RuntimeError,OSError) as exc:raise ValueError('This archive is damaged or encrypted') from exc
    if len(models)==1:return await save_models(item,data,name,folder)
    import time
    cache=DATA/'marketplace-cache';cache.mkdir(parents=True,exist_ok=True)
    for path in cache.glob('*.zip'):
        if time.time()-path.stat().st_mtime>3600:path.unlink(missing_ok=True)
    if sum(p.stat().st_size for p in cache.glob('*.zip'))+len(data)>1024**3:raise ValueError('Archive preview cache is full. Try again after the previous previews expire')
    identifier=hashlib.sha256(data).hexdigest();(cache/(item['id']+'_'+identifier+'.zip')).write_bytes(data)
    return {'selection_required':True,'archive_id':identifier,'models':models,'source':item,'folder':folder,'expires_in_seconds':3600}

@router.post('/api/marketplace/{identifier}/archive')
async def import_archive(identifier:str,request:Request):
    import time
    item=saved(identifier);body=await request.json();key=str(body.get('archive_id',''))
    if not re.fullmatch('[0-9a-f]{64}',key):raise ValueError('Invalid archive preview')
    path=DATA/'marketplace-cache'/(identifier+'_'+key+'.zip')
    if not path.is_file() or time.time()-path.stat().st_mtime>3600:raise ValueError('Archive preview expired. Download or attach it again')
    if not isinstance(body.get('indices'),list) or not body['indices']:raise ValueError('Choose model files from the archive')
    data=path.read_bytes()
    return await save_models(item,data,'selected.zip',body.get('folder','Unsorted'),body.get('indices'))

async def save_models(item,data,name,folder,selected=None):
    module=portal()
    if folder not in module.folders:raise ValueError('Choose an existing Library folder')
    if len(data)>MAX_BYTES:raise ValueError('The download exceeds 250 MB')
    try:model_data=await asyncio.to_thread(unpack,data,name,selected)
    except (zipfile.BadZipFile,RuntimeError,OSError) as exc:raise ValueError('This archive is damaged or encrypted. Download the model files again.') from exc
    created=[];staged=[]
    import tempfile
    with tempfile.TemporaryDirectory(prefix='printflow-import-') as tmp:
        for index,(name,content) in enumerate(model_data):
            digest=hashlib.sha256(content).hexdigest()
            duplicate=next((f for f in module.files if f.get('source',{}).get('url')==item['url'] and f.get('sha256')==digest),None)
            if duplicate:created.append(duplicate);continue
            clean=re.sub(r'[^\w .()\-]','_',name)
            if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',clean,re.I):clean='model_'+clean
            path=Path(tmp)/str(index)/clean;path.parent.mkdir();path.write_bytes(content)
            # Validate geometry/archive structure before adding the model to the library.
            try:preview=await asyncio.to_thread(previews.preview,path);metadata=previews.metadata(preview)
            except ValueError as exc:
                if '500,000 triangles' not in str(exc):raise
                metadata=None
            staged.append((clean,content,digest,metadata))
    for name,content,digest,metadata in staged:
        identifier=uuid.uuid4().hex[:16];relative=Path('marketplace')/item['id']/identifier/name
        target=ROOT/'models'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
        source={k:item.get(k) for k in ('provider','url','title','author','license','checked_at')}
        model={'id':identifier,'name':name,'path':relative.as_posix(),'extension':Path(name).suffix.lower(),'folder':folder,'size':len(content),'created_at':now(),'source':source,'sha256':digest}
        if metadata:model['preview']=metadata
        module.files.append(model);created.append(model)
    item['library_ids']=list(dict.fromkeys(item.get('library_ids',[])+[f['id'] for f in created]))
    save_json(module.store_path,module.files);save_json(store,records);module.events.emit('library',created)
    return {'files':created,'source':item,'note':'Imported original models. Review units, colors, printer compatibility and settings before preparation.'}

@router.post('/api/marketplace/{identifier}/download')
async def download(identifier:str,request:Request):
    item=saved(identifier);b=await request.json();file=next((f for f in item['files'] if f['id']==b.get('file_id')),None)
    if not file:raise ValueError('Choose one of the source-provided model downloads')
    try:data,_,_=await fetch(file['url'],MAX_BYTES)
    except (httpx.HTTPError,OSError) as exc:raise ValueError('Download unavailable. Reopen the source or attach your downloaded model file.') from exc
    return await receive_models(item,data,file['name'],b.get('folder','Unsorted'))

@router.post('/api/marketplace/{identifier}/attach')
async def attach(identifier:str,file:UploadFile=File(),folder:str=Form('Unsorted')):
    item=saved(identifier);data=await file.read(MAX_BYTES+1)
    return await receive_models(item,data,file.filename or '',folder)
