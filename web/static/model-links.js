/* Resolve chat artifacts only against the known library; never expose arbitrary local paths. */
(function(root){
  function clean(value){let s=String(value||'').trim().replace(/^<|>$/g,'');try{s=decodeURIComponent(s);}catch{}return s.replace(/\\/g,'/').replace(/^file:\/\/\/?/i,'').replace(/[?#].*$/,'');}
  function resolveModelLink(value,files,origin='http://127.0.0.1:8840'){
    const path=clean(value);let pathname=path;
    if(/^https?:/i.test(path)){try{const url=new URL(path);if(url.origin!==origin)return null;pathname=url.pathname;}catch{return null;}}
    else if(/^[a-z][a-z\d+.-]*:/i.test(path)&&!/^([a-z]:\/)/i.test(path))return null;
    const route=pathname.match(/^\/api\/files\/([^/]+)(?:\/|$)/);if(route)return files.find(f=>f.id===route[1])||null;
    const normalized=pathname.toLowerCase();const exact=files.filter(f=>normalized===clean(f.path).toLowerCase()||normalized.endsWith('/models/'+clean(f.path).toLowerCase()));if(exact.length===1)return exact[0];
    const basename=normalized.split('/').pop();if(!/\.(stl|3mf)$/i.test(basename))return null;
    const named=files.filter(f=>clean(f.path).split('/').pop().toLowerCase()===basename||String(f.name).toLowerCase()===basename);return named.length===1?named[0]:null;
  }
  function textModels(text,files,origin){const found=[];for(const match of String(text||'').matchAll(/\[[^\]]+\]\(([^)]+)\)/g)){const file=resolveModelLink(match[1],files,origin);if(file&&!found.some(f=>f.id===file.id))found.push(file);}return found;}
  function resolveJobLink(value,jobs,origin='http://127.0.0.1:8840'){
    const path=clean(value);let pathname=path;
    if(/^https?:/i.test(path)){try{const url=new URL(path);if(url.origin!==origin)return null;pathname=url.pathname;}catch{return null;}}
    else if(/^[a-z][a-z\d+.-]*:/i.test(path)&&!/^([a-z]:\/)/i.test(path))return null;
    const route=pathname.match(/^\/api\/jobs\/([^/]+)\/download$/);if(route)return jobs.find(j=>j.id===route[1]&&!j.comparison_parent)||null;
    const normalized=pathname.toLowerCase();
    const matches=jobs.filter(j=>{const project=clean(j.result?.project).toLowerCase();return project&&!j.comparison_parent&&(normalized===project||(/^runs\//.test(project)&&normalized.endsWith('/'+project)));});
    return matches.length===1?matches[0]:null;
  }
  function textJobs(text,jobs,origin){const found=[];for(const match of String(text||'').matchAll(/\[[^\]]+\]\(([^)]+)\)/g)){const job=resolveJobLink(match[1],jobs,origin);if(job&&!found.some(j=>j.id===job.id))found.push(job);}return found;}
  function completedJob(state,origin){
    if(state?.codex?.busy||!['completed','partial'].includes(state?.codex?.progress?.phase))return null;
    for(const message of [...(state.chat||[])].reverse()){if(message.role==='user')break;if(message.role==='assistant'){const found=textJobs(message.text,state.jobs||[],origin);if(found.length)return found[0];}}
    return null;
  }
  function completedModel(state,origin){
    if(state?.codex?.busy||!['completed','partial'].includes(state?.codex?.progress?.phase))return null;
    const files=state.files||[];for(const message of [...(state.chat||[])].reverse()){if(message.role==='user')break;if(message.role==='assistant'){const found=textModels(message.text,files,origin);if(found.length)return found.at(-1);}}
    const job=completedJob(state,origin),model=job&&files.find(f=>f.id===job.file_id);if(model)return model;
    const ready=state.model_ready,p=state.codex.progress,at=Date.parse(ready?.at),start=Date.parse(p.started_at),end=Date.parse(p.finished_at);
    return at>=start&&at<=end+5000?files.find(f=>f.id===ready.file_id)||null:null;
  }
  const api={resolveModelLink,textModels,completedModel,resolveJobLink,textJobs,completedJob};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.PrintFlowModelLinks=api;
})(globalThis);
