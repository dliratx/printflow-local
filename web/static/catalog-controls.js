(function(root) {
  'use strict';
  const normalize=value=>String(value??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('en');
  const format=file=>String(file.extension||String(file.name||'').split('.').pop()).replace(/^\./,'').toUpperCase();
  const time=file=>{const value=file.created_at??file.uploaded_at;return typeof value==='number'?value:(Date.parse(value)||0);};
  function filterFiles(files,options={}) {
    const terms=normalize(options.search).trim().split(/\s+/).filter(Boolean);
    const rows=(files||[]).map((file,index)=>({file,index})).filter(({file})=>
      (!options.folder||file.folder===options.folder)&&
      (!options.format||format(file)===options.format.toUpperCase())&&
      terms.every(term=>normalize(file.name).includes(term)));
    const order=options.sort||'newest';
    rows.sort((a,b)=>{
      if(order==='name')return String(a.file.name).localeCompare(String(b.file.name),'en',{numeric:true,sensitivity:'base'})||a.index-b.index;
      if(order==='size')return (Number(b.file.size)||0)-(Number(a.file.size)||0)||a.index-b.index;
      return time(b.file)-time(a.file)||b.index-a.index;
    });
    return rows.map(row=>row.file);
  }
  const api=Object.freeze({filterFiles,format,normalize});
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.PrintFlowCatalog=api;
})(typeof window==='undefined'?globalThis:window);
