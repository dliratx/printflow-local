'use strict';
const marketPage=workPage('marketplace','Discover models','Find your next print. Keep its source when you bring it into your Library.');
const marketNav=el('button','nav-item');marketNav.type='button';marketNav.dataset.workpage='marketplace';marketNav.append(icon('search'),el('span','','Discover models'));marketNav.onclick=()=>showPage('marketplace');document.querySelector('nav[aria-label="Main navigation"]').insertBefore(marketNav,document.querySelector('[data-scroll="design-page"]'));
const marketToolbar=el('form','market-toolbar card'),marketQuery=textInput(),marketProvider=el('select'),marketSearch=el('button','button primary','Search models');
marketQuery.placeholder='Search for a model or paste its page link…';marketQuery.setAttribute('aria-label','Search models or paste a model URL');marketQuery.required=true;marketQuery.maxLength=300;marketProvider.setAttribute('aria-label','Model source');marketSearch.type='submit';marketToolbar.append(icon('search'),marketQuery,marketProvider,marketSearch);
const marketTabs=el('div','market-tabs'),marketCount=el('span','field-help'),marketResults=el('div','market-results'),marketDetail=el('aside','market-detail card'),marketBody=el('div','market-body'),marketNotice=el('p','market-notice');
const marketResultsWrap=el('section','market-results-wrap');marketResultsWrap.append(marketTabs,marketResults);marketBody.append(marketResultsWrap,marketDetail);marketPage.append(marketToolbar,marketNotice,marketBody);
let marketState=null,marketItems=[],marketSelected=null,marketView='search',marketSearching=false,marketInspectVersion=0,marketLastSearch=null;
marketNotice.setAttribute('role','status');marketResults.setAttribute('aria-busy','false');
function marketSourceLink(url,label='Open source') {const a=el('a','button outline',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
function marketProviderName(key){return marketState?.providers.find(p=>p.id===key)?.name||key;}
async function loadMarketplace(){
  try{marketState=await api('/api/marketplace',undefined,'GET');const selected=marketProvider.value;options(marketProvider,[['all','All sources'],...marketState.providers.map(p=>[p.id,p.name])]);if(selected)marketProvider.value=selected;if(!marketLastSearch)marketNotice.textContent=marketState.notice;renderMarketTabs();renderMarketResults();if(!marketSelected)renderMarketIntro();}
  catch(e){marketNotice.textContent=e.message;}
}
function renderMarketTabs(){marketTabs.replaceChildren();for(const [key,label] of [['search','Search results'],['saved','Saved sources']]){const b=button(label,'outline'+(marketView===key?' active':''),()=>{marketView=key;renderMarketTabs();renderMarketResults();});b.setAttribute('aria-pressed',marketView===key);marketTabs.append(b);}marketTabs.append(marketCount);}
function renderMarketResults(){
  const items=marketView==='saved'?(marketState?.saved||[]).slice().reverse():marketItems;marketResults.replaceChildren();marketCount.textContent=items.length?items.length+' listings':'';
  if(!items.length){
    const state=marketView==='saved'?'saved':marketSearching?'loading':marketLastSearch?.status||'initial',query=marketLastSearch?.query||'';
    const titles={saved:'Keep a collection of ideas',initial:'What would you like to print?',loading:'Finding models for “'+query+'”',empty:'No matching listings returned',error:'Search is unavailable'};
    const copy={saved:'Opening a listing saves its source here. Imported files appear in Library.',initial:'Search across model sites, then review the creator’s files and license.',loading:'Checking public listings and verifying model links. This can take about a minute.',empty:'The public index did not return a model for “'+query+'”. The source websites may have more results.',error:'Your search could not be completed. Retry it or continue on a source website below.'};
    const empty=el('div','market-empty '+(state==='loading'?'market-loading':''));empty.append(icon(state==='loading'?'search':'box'),el('h2','',titles[state]||titles.empty),el('p','',copy[state]||copy.empty));
    if(state==='loading'){const track=el('div','market-search-track');track.append(el('span'));empty.append(track);}
    else if(['empty','error'].includes(state)){empty.append(button('Retry search','primary',()=>{marketQuery.value=query;marketProvider.value=marketLastSearch.provider;searchMarketplace();},'search'));appendMarketSourceLinks(empty);}
    else if(state==='initial'){const suggestions=el('div','market-suggestions');for(const q of ['3DBenchy','desk organizer','articulated dragon','phone stand'])suggestions.append(button(q,'outline',()=>{marketQuery.value=q;searchMarketplace();}));empty.append(suggestions);}
    marketResults.append(empty);return;
  }
  for(const item of items){const card=el('article','market-card card');card.classList.toggle('selected',marketSelected?.id===item.id);const media=el('button','market-card-media');media.type='button';media.setAttribute('aria-label','Review '+item.title);media.onclick=()=>inspectMarketItem(item);
    if(item.image){const img=el('img');img.src=item.image;img.alt=item.title;img.loading='lazy';img.referrerPolicy='no-referrer';img.onerror=()=>{img.remove();media.classList.add('no-image');media.prepend(el('span','','Preview unavailable at source'));};media.append(img);}else{media.classList.add('no-image');media.append(el('span','','Preview unavailable at source'));}
    media.append(el('span','market-source-badge',marketProviderName(item.provider)));const info=el('div','market-card-copy');info.append(el('h3','',item.title),el('p','',item.description||'Review the original listing for details and model files.'));
    const status=item.library_ids?.length?'In your Library':item.files?.length?'Direct download available':item.author?'By '+item.author:'Author & license at source';info.append(el('small','',status),button('Review model','outline',()=>inspectMarketItem(item),'arrow'));card.append(media,info);marketResults.append(card);}
  if(marketView==='search'){
    const footer=el('div','market-more');
    if(marketLastSearch?.has_more){const more=button(marketSearching?'Finding more models…':'Load more models','outline',()=>searchMarketplace(true),'search');more.disabled=marketSearching;footer.append(more);}
    else if(marketLastSearch?.status==='error')footer.append(button('Retry loading more','outline',()=>searchMarketplace(true)));
    footer.append(el('p','field-help',marketLastSearch?.has_more?'Search additional listings. Availability varies by source.':'No additional listings returned. The source websites may have more.'));appendMarketSourceLinks(footer);marketResults.append(footer);
  }
}
function renderMarketIntro(){marketDetail.replaceChildren(el('span','market-kicker','FROM DISCOVERY TO PRINT'),el('h2','','Your model, with its history'));
  for(const [n,title,copy] of [['1','Find a design','Search the public index or paste a model page from a supported site.'],['2','Review its source','Check the creator, license and original files. Some sites require their own sign-in.'],['3','Add to Library','Import the original STL or 3MF, then inspect colors, size and printer settings.']]){const row=el('div','market-step'),text=el('div');text.append(el('h3','',title),el('p','',copy));row.append(el('span','',n),text);marketDetail.append(row);}
  marketDetail.append(el('p','field-help','Catalog availability is controlled by each source. Imported models are prepared locally; they are not sent to a printer automatically.'));
}
function appendMarketSourceLinks(container){
  const links=marketLastSearch?.source_links||[];if(!links.length)return;
  const box=el('div','market-source-links');box.append(el('p','field-help','Search the source websites'));
  const list=el('div','market-suggestions');for(const source of links)list.append(marketSourceLink(source.url,source.name+' ↗'));box.append(list);container.append(box);
}
async function searchMarketplace(more=false){
  if(marketSearching)return;const previous=marketLastSearch,query=more?previous?.query:marketQuery.value.trim();if(!query)return;
  const provider=more?previous.provider:marketProvider.value||'all',page=more?(previous.next_page||previous.page+1||2):1,started=Date.now(),scroll=marketResults.scrollTop;
  marketSearching=true;marketSearch.disabled=true;marketSearch.textContent='Searching…';marketResults.setAttribute('aria-busy','true');
  marketLastSearch={query,provider,status:'loading',source_links:(marketState?.providers||[]).filter(p=>provider==='all'||p.id===provider).map(p=>({name:p.name,url:p.search+(p.id==='benchy'?'':encodeURIComponent(query))}))};
  if(more)marketLastSearch={...previous,status:'loading'};
  else{marketItems=[];marketSelected=null;++marketInspectVersion;marketBody.classList.remove('has-selection');renderMarketIntro();}
  marketView='search';renderMarketTabs();renderMarketResults();marketNotice.textContent='Searching with '+(marketState?.search_engine||'your connected search service')+'…';
  const timer=setInterval(()=>{marketNotice.textContent='Searching for “'+query+'” · '+Math.floor((Date.now()-started)/1000)+'s elapsed · checking public model listings';},1000);
  try{
    if(/^https:\/\//i.test(query)){await inspectMarketItem({url:query});marketLastSearch=null;marketNotice.textContent='Source details are ready to review.';return;}
    const r=await api('/api/marketplace/search',{q:query,provider,page,exclude:more?marketItems.map(x=>x.url):[]});marketLastSearch=r;
    if(r.status==='error'&&more)marketLastSearch={...previous,status:'error'};
    const seen=new Set(more?marketItems.map(x=>x.id):[]);marketItems=(more?marketItems:[]).concat((r.items||[]).filter(x=>!seen.has(x.id)));
    marketNotice.textContent=r.status==='error'?(r.warnings?.[0]||'Search is unavailable.'):r.items.length?`${marketItems.length} listings for “${r.query}” · ${r.engine}${r.cached?' · recent results':''}. Photos from the indexed source listings.`:more?'No more unique listings returned. Your previous results are kept.':`No listings returned for “${r.query}”. Try a different phrase or search the source websites below.`;
  }catch(e){marketLastSearch={...(more?previous:marketLastSearch),status:'error'};marketNotice.textContent=e.message;}
  finally{clearInterval(timer);marketSearching=false;marketResults.setAttribute('aria-busy','false');marketSearch.disabled=false;marketSearch.textContent='Search models';renderMarketResults();marketResults.scrollTop=more?scroll:0;}
}
marketToolbar.onsubmit=e=>{e.preventDefault();searchMarketplace();};
async function inspectMarketItem(item){const version=++marketInspectVersion;marketDetail.replaceChildren(el('h2','','Checking the source…'),el('p','field-help','Reading public model details and download availability.'));marketBody.classList.add('has-selection');
  try{const value=await api('/api/marketplace/inspect',{url:item.url,title:item.title||'',description:item.description||''});if(version!==marketInspectVersion)return;marketSelected=value;marketState.saved=marketState.saved.filter(s=>s.id!==value.id).concat(value);marketItems=marketItems.map(s=>s.id===value.id?value:s);renderMarketResults();renderMarketDetail(value);}
  catch(e){if(version===marketInspectVersion)marketDetail.replaceChildren(el('h2','','Could not read this link'),el('p','work-notice',e.message));}
}
function renderMarketDetail(item){marketDetail.replaceChildren();const head=el('div','market-detail-head');head.append(el('span','market-kicker',marketProviderName(item.provider)),button('','outline small',()=>{marketSelected=null;marketBody.classList.remove('has-selection');renderMarketIntro();renderMarketResults();},'close'));head.lastChild.setAttribute('aria-label','Close model details');marketDetail.append(head,el('h2','',item.title));
  if(item.image){const img=el('img','market-detail-image');img.src=item.image;img.alt=item.title;img.referrerPolicy='no-referrer';marketDetail.append(img);}
  if(item.description)marketDetail.append(el('p','market-description',item.description));
  const meta=el('dl','market-metadata');for(const [key,value] of [['Creator',item.author||'Check the source listing'],['License',item.license||'Not supplied by the public page — check the source']])meta.append(el('dt','',key),el('dd','',value));marketDetail.append(meta,marketSourceLink(item.url));
  if(item.notice)marketDetail.append(el('p','work-notice',item.notice));
  if(item.library_ids?.length){const existing=el('section','market-imported');existing.append(el('h3','','In your Library'));for(const id of item.library_ids){const f=ui.state?.files.find(f=>f.id===id);if(f)existing.append(button(f.name,'outline',()=>selectFile(id),'box'));}marketDetail.append(existing);}
  const importBox=el('section','market-import');importBox.append(el('h3','','Add to Library'));const folder=el('select');options(folder,(ui.state?.folders||['Unsorted']).map(s=>[s,s]));folder.value='Unsorted';importBox.append(field('Library folder',folder));
  const importResult=async(result)=>{if(result.selection_required){renderMarketArchive(result,importResult);return;}marketSelected=result.source;await refresh();await loadMarketplace();renderMarketDetail(result.source);toast(result.files.length+' model(s) added to Library.');if(result.files[0])selectFile(result.files[0].id);};
  if(item.files?.length){const files=el('select');options(files,item.files.map(f=>[f.id,f.name]));const download=button('Import original file','primary',async()=>{const r=await action(()=>api('/api/marketplace/'+item.id+'/download',{file_id:files.value,folder:folder.value}),null,download);if(r)await importResult(r);},'download');importBox.append(field('Source files',files),download);}
  const upload=el('input');upload.type='file';upload.accept='.stl,.3mf,.zip';upload.setAttribute('aria-label','Attach a file downloaded from this source');const attach=button('Import downloaded file','outline',async()=>{if(!upload.files[0]){upload.click();return;}const data=new FormData();data.append('file',upload.files[0]);data.append('folder',folder.value);const r=await action(()=>api('/api/marketplace/'+item.id+'/attach',data),null,attach);if(r)await importResult(r);},'upload');
  importBox.append(el('p','field-help','Already downloaded it? Attach the STL, 3MF or ZIP. Its source stays linked to the model.'),upload,attach,el('small','field-help','Up to 250 MB · 20 models per ZIP · G-code is excluded'));marketDetail.append(importBox);
}

function renderMarketArchive(result,onImported){
  marketDetail.replaceChildren(el('span','market-kicker','CHOOSE MODEL FILES'),el('h2','',result.source.title),el('p','field-help',`${result.models.length} model files in this archive. Choose up to 20. Original folders are shown to distinguish variants.`));
  const list=el('div','market-archive-list'),choices=[];let preferred=result.models.find(m=>m.name.toLowerCase()==='3dbenchy.stl');
  for(const model of result.models){const input=el('input');input.type='checkbox';input.checked=preferred?model.index===preferred.index:result.models.length<=20;const row=el('label','market-archive-row'),copy=el('span');copy.append(el('strong','',model.name),el('small','',model.path),el('small','',(model.size/1024/1024).toFixed(2)+' MB'));row.append(input,copy);list.append(row);choices.push({input,index:model.index});}
  const count=el('p','field-help');const update=()=>{const n=choices.filter(x=>x.input.checked).length;count.textContent=n+' selected · up to 20 models';confirm.disabled=n===0||n>20;};
  const confirm=button('Import selected models','primary',async()=>{const r=await action(()=>api('/api/marketplace/'+result.source.id+'/archive',{archive_id:result.archive_id,indices:choices.filter(x=>x.input.checked).map(x=>x.index),folder:result.folder}),null,confirm);if(r)await onImported(r);},'download');choices.forEach(x=>x.input.onchange=update);update();marketDetail.append(list,count,confirm,button('Back to source','outline',()=>renderMarketDetail(result.source)));
}
