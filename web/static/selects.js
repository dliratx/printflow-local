/* Theme-aware select menus. Native selects remain the form data source. */
'use strict';
(() => {
  const widgets=new Set();let active=null,sequence=0;
  const valueDescriptor=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value');
  function enhance(select){
    if(select.dataset.enhanced==='true'||select.multiple)return;
    select.dataset.enhanced='true';
    const wrapper=document.createElement('span');wrapper.className='select-control';
    select.before(wrapper);wrapper.append(select);select.classList.add('select-source');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
    const trigger=document.createElement('button');trigger.type='button';trigger.className='select-trigger';trigger.setAttribute('role','combobox');trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
    const caption=document.createElement('span');caption.className='select-caption';
    const arrow=document.createElementNS('http://www.w3.org/2000/svg','svg');arrow.setAttribute('viewBox','0 0 24 24');arrow.innerHTML='<path d="m7 10 5 5 5-5"/>';trigger.append(caption,arrow);
    const menu=document.createElement('div');menu.className='select-menu';menu.id='select-menu-'+(++sequence);menu.setAttribute('popover','manual');menu.hidden=true;trigger.setAttribute('aria-controls',menu.id);
    const search=document.createElement('input');search.type='search';search.className='select-search';search.placeholder='Search options…';search.setAttribute('aria-label','Search options');
    const list=document.createElement('div');list.className='select-options';list.setAttribute('role','listbox');list.id=menu.id+'-options';trigger.setAttribute('aria-controls',list.id);menu.append(search,list);wrapper.append(trigger,menu);
    const label=select.closest('label');const labelText=select.getAttribute('aria-label')||(label?[...label.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent.trim()).join(' ')||label.querySelector('span')?.textContent:'Choose an option');
    let open=false,items=[],highlight=-1,typeAhead='',typeTimer;
    function sync(){const option=select.selectedOptions[0];caption.textContent=option?.textContent||'Choose an option';trigger.disabled=select.disabled;trigger.title=option?.textContent||'';trigger.setAttribute('aria-label',(labelText||'Choose an option')+': '+caption.textContent);if(open)paint();}
    function position(){const rect=trigger.getBoundingClientRect();const wanted=Math.min(330,menu.scrollHeight||330);const below=innerHeight-rect.bottom-10,above=rect.top-10;const up=below<Math.min(wanted,200)&&above>below;const height=Math.min(wanted,up?above:below);menu.style.width=Math.min(Math.max(rect.width,180),innerWidth-24)+'px';menu.style.left=Math.max(12,Math.min(rect.left,innerWidth-parseFloat(menu.style.width)-12))+'px';menu.style.maxHeight=Math.max(100,height)+'px';menu.style.top=(up?Math.max(10,rect.top-height-6):rect.bottom+6)+'px';}
    function focusOption(index){highlight=Math.max(0,Math.min(items.length-1,index));items.forEach((item,i)=>item.node.classList.toggle('highlighted',i===highlight));const item=items[highlight];if(item){trigger.setAttribute('aria-activedescendant',item.node.id);search.setAttribute('aria-activedescendant',item.node.id);item.node.scrollIntoView({block:'nearest'});}}
    function choose(option){if(option.disabled)return;select.value=option.value;select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));close(true);}
    function paint(){list.replaceChildren();items=[];const query=search.value.trim().toLowerCase();for(const option of select.options){if(query&&!option.textContent.toLowerCase().includes(query))continue;const node=document.createElement('div');node.className='select-option';node.id=menu.id+'-option-'+option.index;node.setAttribute('role','option');node.setAttribute('aria-selected',String(option.selected));node.setAttribute('aria-disabled',String(option.disabled));const text=document.createElement('span');text.textContent=option.textContent;const check=document.createElement('span');check.className='select-check';check.textContent=option.selected?'✓':'';check.setAttribute('aria-hidden','true');node.append(text,check);node.addEventListener('pointerdown',e=>e.preventDefault());node.addEventListener('click',e=>{e.preventDefault();choose(option);});list.append(node);if(!option.disabled)items.push({node,option});}if(!items.length){const empty=document.createElement('div');empty.className='select-no-results';empty.textContent='No matching options';list.append(empty);}focusOption(Math.max(0,items.findIndex(item=>item.option.selected)));}
    function close(focus=false){if(!open)return;open=false;if(menu.matches(':popover-open'))menu.hidePopover();menu.hidden=true;trigger.setAttribute('aria-expanded','false');trigger.removeAttribute('aria-activedescendant');if(active===widget)active=null;if(focus&&trigger.isConnected)trigger.focus();}
    function show(){if(trigger.disabled)return;if(active&&active!==widget)active.close();active=widget;open=true;search.value='';search.hidden=select.options.length<12;menu.hidden=false;paint();if(menu.showPopover)menu.showPopover();position();focusOption(highlight);trigger.setAttribute('aria-expanded','true');if(!search.hidden)search.focus();}
    function keydown(event){
      const key=event.key;
      if(['ArrowDown','ArrowUp','Home','End','Enter','Escape',' '].includes(key)&&!(event.target===search&&key===' ')){
        if(key==='Escape'){if(open){event.preventDefault();event.stopPropagation();close(true);}return;}
        if(key==='Enter'||key===' '){event.preventDefault();if(!open)show();else if(items[highlight])choose(items[highlight].option);return;}
        event.preventDefault();if(!open){show();return;}focusOption(key==='Home'?0:key==='End'?items.length-1:highlight+(key==='ArrowDown'?1:-1));
      }else if(key==='Tab'){close();}
      else if(event.target===trigger&&key.length===1&&!event.ctrlKey&&!event.metaKey){event.preventDefault();if(!open)show();typeAhead+=key.toLowerCase();clearTimeout(typeTimer);typeTimer=setTimeout(()=>typeAhead='',650);const found=items.findIndex(item=>item.option.textContent.toLowerCase().startsWith(typeAhead));if(found>=0)focusOption(found);}
    }
    const widget={select,wrapper,menu,trigger,close,position,sync};widgets.add(widget);
    trigger.addEventListener('click',event=>{event.preventDefault();open?close():show();});trigger.addEventListener('keydown',keydown);search.addEventListener('keydown',keydown);search.addEventListener('input',()=>{paint();position();});select.addEventListener('change',sync);select.addEventListener('focus',()=>trigger.focus());
    Object.defineProperty(select,'value',{configurable:true,get(){return valueDescriptor.get.call(this);},set(value){valueDescriptor.set.call(this,value);sync();}});
    new MutationObserver(sync).observe(select,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['disabled','selected','label']});
    select.closest('dialog')?.addEventListener('close',()=>close());sync();
  }
  document.querySelectorAll('select').forEach(enhance);
  new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)if(node.nodeType===Node.ELEMENT_NODE){if(node.matches('select'))enhance(node);node.querySelectorAll('select').forEach(enhance);}for(const widget of widgets)if(!widget.select.isConnected){widget.close();widgets.delete(widget);}}).observe(document.body,{childList:true,subtree:true});
  document.addEventListener('pointerdown',event=>{if(active&&!active.wrapper.contains(event.target))active.close();});
  window.addEventListener('resize',()=>active?.position());document.addEventListener('scroll',event=>{if(active&&!active.menu.contains(event.target))active.close();},true);
})();
