const test=require('node:test'),assert=require('node:assert/strict');
const {SceneLoader}=require('../web/static/model-scene.js');
const {sceneView,modelMatrix,normalMatrix}=require('../web/static/model-renderer.js');
const {Renderer}=require('../web/static/model-renderer.js');
const mesh=id=>({id,triangle_count:1,vertex_count:3,byte_length:108});
const transform=[1,0,0,0,1,0,0,0,1,0,0,0];
const instance=(id,plate,x)=>({mesh:id,plate,transform,bounds:[[x,0,0],[x+1,1,1]]});
const scene={revision:'r',meshes:[mesh(0),mesh(1)],instances:[instance(0,'3',0),instance(0,'3',2),instance(1,'7',400)]};
const reply=()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(108)});

test('plate view fits only its parts and all-plates preserves the original layout',()=>{
  const first=sceneView(scene,'3');assert.equal(first.instances.length,2);assert.equal(first.triangleCount,2);assert.deepEqual(first.origin,[1.5,.5,.5]);
  const all=sceneView(scene);assert.equal(all.triangleCount,3);assert.equal(all.extent,401);
  assert.equal(sceneView(scene,'empty').instances.length,0);
  assert.deepEqual(modelMatrix([...transform.slice(0,9),4,5,6]).slice(12,15),[4,5,6]);
  assert.deepEqual(normalMatrix([2,0,0,0,3,0,0,0,4,0,0,0]),[.5,0,0,0,1/3,0,0,0,.25]);
});

test('repeated objects load one full mesh and plate switches reuse loaded geometry',async()=>{
  const calls=[],loader=new SceneLoader(async url=>{calls.push(url);return reply();});
  const first=await loader.load('file',scene,'3');assert.equal(calls.length,1);assert.equal(first.buffers.get(0).length,27);
  await loader.load('file',scene,'7');assert.equal(calls.length,2);
  await loader.load('file',scene,'all');assert.equal(calls.length,2);
  assert.ok(calls[0].endsWith('mesh=0')&&calls[1].endsWith('mesh=1'));
});

test('late plate loads never replace a newer selection',async()=>{
  let resolveFirst;const loader=new SceneLoader(url=>url.endsWith('mesh=0')?new Promise(resolve=>resolveFirst=resolve):Promise.resolve(reply()));
  const first=loader.load('file',scene,'3');const next=await loader.load('file',scene,'7');
  resolveFirst(reply());assert.equal(await first,null);assert.equal(next.plate,'7');assert.equal(loader.buffers.has(0),false);
});

test('truncated binary geometry fails visibly instead of showing missing faces',async()=>{
  const loader=new SceneLoader(async()=>({ok:true,arrayBuffer:async()=>new ArrayBuffer(104)}));
  await assert.rejects(loader.load('file',scene,'3'),/incomplete/);assert.equal(loader.buffers.size,0);
});

test('streamed buffers report real byte progress and preserve the final geometry',async()=>{
  const updates=[],expected=new Float32Array(27).map((_,i)=>i);
  const bytes=new Uint8Array(expected.buffer);
  const loader=new SceneLoader(async()=>({ok:true,body:new ReadableStream({start(c){c.enqueue(bytes.slice(0,44));c.enqueue(bytes.slice(44));c.close();}})}));
  const result=await loader.load('file',scene,'3',(_,__,transfer)=>updates.push(transfer));
  assert.deepEqual(result.buffers.get(0),expected);
  assert.equal(updates[0].loadedBytes,0);assert.equal(updates.at(-1).loadedBytes,108);
  assert.equal(updates.at(-1).totalBytes,108);
});

test('a stalled transfer offers retry instead of waiting forever',async()=>{
  const loader=new SceneLoader(()=>new Promise(()=>{}),5);
  await assert.rejects(loader.load('file',scene,'3'),/timed out/);
  assert.equal(loader.buffers.size,0);
});

test('clearing the canvas during a plate switch retains existing GPU buffers',()=>{
  let uploads=0,deleted=0,drawn=0;
  const gl={ARRAY_BUFFER:1,TRIANGLES:2,LINES:3,STATIC_DRAW:4,DYNAMIC_DRAW:5,
    createShader:()=>({}),getShaderParameter:()=>true,createProgram:()=>({}),
    getProgramParameter:()=>true,getAttribLocation:()=>0,getUniformLocation:()=>0,
    createBuffer:()=>({}),deleteBuffer:()=>deleted++,
    bufferData:(_,data,usage)=>{if(usage===4)uploads++;},drawArrays:(mode,_,n)=>{if(mode===2)drawn+=n/3;}};
  const proxy=new Proxy(gl,{get:(obj,key)=>key in obj?obj[key]:()=>{}});
  const renderer=new Renderer({clientWidth:800,clientHeight:600,getContext:()=>proxy,addEventListener(){}});
  const buffers=new Map([[0,new Float32Array(27)],[1,new Float32Array(27)]]);
  renderer.draw({scene,plate:'3',buffers},0,0,1,false);assert.equal(uploads,1);assert.equal(drawn,2);
  renderer.draw(null,0,0,1,false);assert.equal(deleted,0);
  renderer.draw({scene,plate:'all',buffers},0,0,1,false);assert.equal(uploads,2);assert.equal(drawn,5);
  renderer.draw({scene:{...scene,revision:'new'},plate:'3',buffers},0,0,1,false);assert.equal(deleted,2);
});
