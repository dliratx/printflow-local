/* View-only navigation and discovery helpers. Never prepare or start a print. */
(()=>{
  'use strict';
  const nav=document.querySelector('.sidebar'),shell=document.querySelector('.shell');
  const menu=$('navigation-toggle'),close=$('navigation-close'),shade=$('navigation-shade');
  const mobile=matchMedia('(max-width:950px)');
  let menuReturn=null;
  function setNavigation(open,restore=true){
    open=Boolean(open&&mobile.matches);
    if(open)menuReturn=document.activeElement;
    document.body.classList.toggle('navigation-open',open);
    menu.setAttribute('aria-expanded',String(open));
    nav.inert=mobile.matches&&!open;
    shell.inert=open;
    if(open){nav.setAttribute('role','dialog');nav.setAttribute('aria-modal','true');nav.setAttribute('aria-label','Workspace navigation');close.focus();}
    else {nav.removeAttribute('role');nav.removeAttribute('aria-modal');nav.removeAttribute('aria-label');if(restore&&menuReturn?.isConnected&&mobile.matches)menuReturn.focus();menuReturn=null;}
  }
  menu.onclick=()=>setNavigation(!document.body.classList.contains('navigation-open'));
  close.onclick=()=>setNavigation(false);shade.onclick=()=>setNavigation(false);
  nav.addEventListener('keydown',event=>{
    if(!document.body.classList.contains('navigation-open'))return;
    if(event.key==='Escape'){event.preventDefault();setNavigation(false);}
    if(event.key==='Tab'){
      const focusable=[...nav.querySelectorAll('button:not(:disabled),a[href]')].filter(node=>node.getClientRects().length);
      const first=focusable[0],last=focusable.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    }
  });
  nav.addEventListener('click',event=>{
    if(event.target.closest('.nav-item,.sidebar-printer')&&mobile.matches){
      const focusInNav=nav.contains(document.activeElement);setNavigation(false,false);
      if(focusInNav&&!document.querySelector('dialog[open]')){
        const heading=document.querySelector('main>.page:not([hidden]) h1')||$('dashboard');
        heading.tabIndex=-1;heading.focus({preventScroll:true});
      }
    }
  });
  mobile.addEventListener('change',()=>setNavigation(false,false));
  setNavigation(false,false);

  const filters=$('gallery-options');
  filters.querySelectorAll('[data-format]').forEach(b=>b.onclick=()=>{
    ui.format=b.dataset.format;
    filters.querySelectorAll('[data-format]').forEach(other=>other.setAttribute('aria-pressed',String(other===b)));
    if(ui.state)renderFiles();
  });
  $('library-sort').onchange=()=>{ui.sort=$('library-sort').value;if(ui.state)renderFiles();};

  const dialog=$('quick-find-dialog'),input=$('quick-find-input'),results=$('quick-find-results');
  const destinations=[['overview','Overview','Camera, printer status and loaded materials','grid'],['library','Library','Your local models and saved revisions','folder'],['marketplace','Discover models','Search model sources','search'],['design','Design studio','Create with CAD or an image','box'],['jobs','Jobs','Prepared files and print history','print'],['calibration','Calibration','Test library, results and reusable profiles','settings'],['assemblies','Assemblies','Plan parts across your printers','box']];
  function result(label,detail,glyph,handler){
    const b=el('button','quick-find-result');b.type='button';
    const copy=el('span','quick-find-copy');copy.append(el('strong','',label),el('small','',detail));
    b.append(icon(glyph),copy,icon('arrow'));
    b.onclick=()=>{dialog.close();handler();};return b;
  }
  function renderQuickFind(){
    results.replaceChildren();const q=input.value.trim(),term=PrintFlowCatalog.normalize(q);
    const files=q?PrintFlowCatalog.filterFiles(ui.state?.files||[],{search:q,sort:'newest'}).slice(0,8):[];
    if(files.length){results.append(el('div','quick-find-group','Your models'));for(const file of files)results.append(result(file.name,[file.folder||'Unsorted',PrintFlowCatalog.format(file)].join(' · '),'box',()=>selectFile(file.id)));}
    const pages=destinations.filter(d=>!q||PrintFlowCatalog.normalize(d[1]+' '+d[2]).includes(term));
    if(pages.length){results.append(el('div','quick-find-group','Workspace'));for(const [page,title,detail,glyph] of pages)results.append(result(title,detail,glyph,()=>{if(page==='library')backToLibrary();showPage(page);}));}
    if(q){results.append(el('div','quick-find-group','Discover'));results.append(result('Search model sources for “'+q+'”','MakerWorld, Printables and other supported sources','search',()=>{showPage('marketplace');marketQuery.value=q;searchMarketplace();}));}
  }
  function openQuickFind(){if(document.querySelector('dialog[open]'))return;input.value='';renderQuickFind();dialog.showModal();input.focus();}
  $('quick-find-open').onclick=openQuickFind;$('quick-find-close').onclick=()=>dialog.close();input.oninput=renderQuickFind;
  dialog.addEventListener('keydown',event=>{
    if(!['ArrowDown','ArrowUp','Enter'].includes(event.key))return;
    const choices=[...results.querySelectorAll('button')];if(!choices.length)return;
    const i=choices.indexOf(document.activeElement);
    if(event.key==='Enter'&&document.activeElement===input){event.preventDefault();choices[0].click();}
    else if(event.key==='ArrowDown'){event.preventDefault();choices[Math.min(choices.length-1,i+1)].focus();}
    else if(event.key==='ArrowUp'){event.preventDefault();if(i<=0)input.focus();else choices[i-1].focus();}
  });
  document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();if(!shell.inert)openQuickFind();}});

  const topics=el('div','discovery-topics');topics.setAttribute('aria-label','Explore model topics');
  for(const [title,query] of [['Home & living','home decor'],['Desk essentials','desk organizer'],['Miniatures','miniature'],['Articulated toys','articulated'],['Workshop','workshop tools'],['Vehicles','car model'],['Calibration','calibration test']])topics.append(button(title,'outline small',()=>{marketQuery.value=query;searchMarketplace();}));
  marketToolbar.after(topics);

  const reference=$('design-image-file'),preview=el('div','reference-preview');preview.hidden=true;preview.setAttribute('aria-live','polite');reference.closest('label').after(preview);
  let referenceUrl=null;
  reference.addEventListener('change',()=>{
    if(referenceUrl)URL.revokeObjectURL(referenceUrl);referenceUrl=null;preview.replaceChildren();preview.hidden=true;
    const file=reference.files?.[0];if(!file||!['image/png','image/jpeg','image/webp'].includes(file.type))return;
    referenceUrl=URL.createObjectURL(file);const image=el('img');image.src=referenceUrl;image.alt='Selected reference image';image.onerror=()=>{preview.hidden=true;};
    preview.append(image,el('p','',file.name+' · '+displaySize(file.size)));preview.hidden=false;
  });
  window.addEventListener('pagehide',()=>{if(referenceUrl)URL.revokeObjectURL(referenceUrl);});
})();
