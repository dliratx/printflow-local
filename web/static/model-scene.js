/* Load complete shared meshes for the selected plate. No geometry decimation. */
(function(root){
  class SceneLoader {
    constructor(fetcher,timeoutMs=45000){this.fetch=fetcher||((...args)=>fetch(...args));this.buffers=new Map();this.sequence=0;this.timeoutMs=timeoutMs;}
    cancel(){this.sequence++;this.controller?.abort();}
    async load(fileId,scene,plate,onProgress=()=>{}){
      this.cancel();const sequence=this.sequence,revision=fileId+':'+scene.revision;
      if(this.revision!==revision){this.buffers.clear();this.revision=revision;}
      const controller=this.controller=new AbortController(),instances=scene.instances.filter(i=>plate==='all'||i.plate===plate);
      const needed=[...new Set(instances.map(i=>i.mesh))],descriptors=new Map(scene.meshes.map(m=>[m.id,m]));
      const queue=needed.filter(id=>!this.buffers.has(id));let complete=needed.length-queue.length;
      const received=new Map(needed.map(id=>[id,this.buffers.has(id)?descriptors.get(id).byte_length:0]));
      const totalBytes=needed.reduce((n,id)=>n+descriptors.get(id).byte_length,0);let lastProgress=0;
      const progress=(force=false)=>{if(sequence!==this.sequence)return;const now=Date.now();if(force||now-lastProgress>100){lastProgress=now;onProgress(complete,needed.length,{loadedBytes:[...received.values()].reduce((a,b)=>a+b,0),totalBytes});}};
      progress(true);
      const worker=async()=>{
        while(queue.length){
          const id=queue.shift(),mesh=descriptors.get(id);
          let timer;
          const read=async()=>{
            const response=await this.fetch('/api/files/'+encodeURIComponent(fileId)+'/scene-buffer?revision='+encodeURIComponent(scene.revision)+'&mesh='+id,{signal:controller.signal});
            if(!response.ok)throw new Error('A model part could not load. Select Retry preview to try again.');
            if(!response.body?.getReader)return response.arrayBuffer();
            const bytes=new Uint8Array(mesh.byte_length),reader=response.body.getReader();let offset=0;
            try{while(true){const {done,value}=await reader.read();if(done)break;if(sequence!==this.sequence){await reader.cancel();return new ArrayBuffer(0);}if(offset+value.length>bytes.length)throw new Error('A model part had an unexpected size. Retry its preview.');bytes.set(value,offset);offset+=value.length;received.set(id,offset);progress();}}
            finally{reader.releaseLock();}
            if(offset!==bytes.length)throw new Error('A model part was incomplete. Select Retry preview to try again.');
            return bytes.buffer;
          };
          let bytes;
          try{bytes=await Promise.race([read(),new Promise((_,reject)=>{timer=setTimeout(()=>{reject(new Error('Model loading timed out. Select Retry preview to try again.'));controller.abort();},this.timeoutMs);})]);}
          finally{clearTimeout(timer);}
          if(bytes.byteLength!==mesh.byte_length||bytes.byteLength!==mesh.vertex_count*36)throw new Error('A model part was incomplete. Reopen the model to retry.');
          if(sequence!==this.sequence)return;
          this.buffers.set(id,new Float32Array(bytes));received.set(id,bytes.byteLength);complete++;progress(true);
        }
      };
      try{await Promise.all(Array.from({length:Math.min(3,queue.length)},worker));}
      catch(error){if(sequence!==this.sequence||error.name==='AbortError')return null;controller.abort();throw error;}
      return sequence===this.sequence?{scene,plate,buffers:this.buffers}:null;
    }
  }
  root.PrintFlowScene={SceneLoader};if(typeof module!=='undefined')module.exports=root.PrintFlowScene;
})(typeof window!=='undefined'?window:globalThis);
