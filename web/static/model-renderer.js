'use strict';
// Depth is resolved per pixel. Sorting whole triangles by their center produces
// false holes whenever large surfaces overlap, even for a valid watertight mesh.
(function(root){
  function rotate(v,yaw,tilt){const c=Math.cos(yaw),s=Math.sin(yaw),ct=Math.cos(tilt),st=Math.sin(tilt),y=v[0]*s+v[1]*c;return [v[0]*c-v[1]*s,y*st-v[2]*ct,y*ct+v[2]*st];}
  function geometry(mesh){
    const data=new Float32Array(mesh.vertices.length*9),low=[Infinity,Infinity,Infinity],high=[-Infinity,-Infinity,-Infinity];
    for(let i=0;i<mesh.vertices.length;i+=3){
      const a=mesh.vertices[i],b=mesh.vertices[i+1],c=mesh.vertices[i+2],u=b.map((v,k)=>v-a[k]),v=c.map((n,k)=>n-a[k]);
      const n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],length=Math.hypot(...n)||1;
      const hex=/^#[0-9a-f]{6}$/i.test(mesh.faceColors[i/3]||'')?mesh.faceColors[i/3]:'#8BA8D8',rgb=[1,3,5].map(k=>parseInt(hex.slice(k,k+2),16)/255);
      for(let j=0;j<3;j++){const p=mesh.vertices[i+j],offset=(i+j)*9;data.set([...p,...n.map(x=>x/length),...rgb],offset);for(let k=0;k<3;k++){low[k]=Math.min(low[k],p[k]);high[k]=Math.max(high[k],p[k]);}}
    }
    return {data,low,high,count:mesh.vertices.length};
  }
  function frame(bounds,yaw,tilt,width,height,zoom=1){
    const points=[];for(const x of [bounds.low[0],bounds.high[0]])for(const y of [bounds.low[1],bounds.high[1]])for(const z of [bounds.low[2],bounds.high[2]])points.push(rotate([x,y,z],yaw,tilt));
    const low=[0,1].map(k=>Math.min(...points.map(p=>p[k]))),high=[0,1].map(k=>Math.max(...points.map(p=>p[k])));
    const scale=Math.min(width*.78/Math.max(high[0]-low[0],.0001),height*.78/Math.max(high[1]-low[1],.0001))*zoom;
    return {center:low.map((n,k)=>(n+high[k])/2),scale:[2*scale/width,2*scale/height]};
  }
  const identity4=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],identity3=[1,0,0,0,1,0,0,0,1];
  function modelMatrix(m){return [m[0],m[1],m[2],0,m[3],m[4],m[5],0,m[6],m[7],m[8],0,m[9],m[10],m[11],1];}
  function normalMatrix(m){
    const a=m.slice(0,3),b=m.slice(3,6),c=m.slice(6,9),cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
    const x=cross(b,c),y=cross(c,a),z=cross(a,b),det=a.reduce((s,n,k)=>s+n*x[k],0);
    return Math.abs(det)<1e-12?identity3:[...x,...y,...z].map(n=>n/det);
  }
  function sceneView(scene,plate='all'){
    const instances=scene.instances.filter(i=>plate==='all'||i.plate===plate);
    if(!instances.length)return {instances,low:[-.5,-.5,0],high:[.5,.5,0],origin:[0,0,0],extent:1,triangleCount:0};
    const low=[0,1,2].map(k=>Math.min(...instances.map(i=>i.bounds[0][k]))),high=[0,1,2].map(k=>Math.max(...instances.map(i=>i.bounds[1][k])));
    const origin=low.map((v,k)=>(v+high[k])/2),extent=Math.max(...high.map((v,k)=>v-low[k]),.001),counts=new Map(scene.meshes.map(m=>[m.id,m.triangle_count]));
    return {instances,origin,extent,low:low.map((v,k)=>(v-origin[k])/extent),high:high.map((v,k)=>(v-origin[k])/extent),triangleCount:instances.reduce((n,i)=>n+counts.get(i.mesh),0)};
  }
  class Renderer{
    constructor(canvas){
      this.canvas=canvas;this.mesh=null;this.sceneBuffers=new Map();
      const gl=canvas.getContext('webgl',{antialias:true,alpha:false,depth:true});if(!gl)throw new Error('3D preview requires WebGL. Enable graphics acceleration or open the model in Orca.');this.gl=gl;
      const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error('The 3D preview shader could not load.');return s;};
      const vertex=shader(gl.VERTEX_SHADER,`attribute vec3 a_position;attribute vec3 a_normal;attribute vec3 a_color;uniform vec4 u_angles;uniform vec2 u_center;uniform vec2 u_scale;uniform mat4 u_model;uniform mat3 u_normal;uniform vec3 u_origin;uniform float u_extent;varying vec3 v_normal;varying vec3 v_color;
        vec3 rotate(vec3 p){float x=p.x*u_angles.x-p.y*u_angles.y;float y=p.x*u_angles.y+p.y*u_angles.x;return vec3(x,y*u_angles.w-p.z*u_angles.z,y*u_angles.z+p.z*u_angles.w);}
        void main(){vec3 world=(u_model*vec4(a_position,1.)).xyz;vec3 p=rotate((world-u_origin)/u_extent);gl_Position=vec4((p.x-u_center.x)*u_scale.x,-(p.y-u_center.y)*u_scale.y,-p.z*.5,1.);v_normal=rotate(u_normal*a_normal);v_color=a_color;}`);
      const fragment=shader(gl.FRAGMENT_SHADER,`precision mediump float;varying vec3 v_normal;varying vec3 v_color;uniform float u_grid;
        void main(){float lighting=.65+.35*abs(dot(normalize(v_normal),normalize(vec3(-.35,-.5,.79))));vec3 color=mix(v_color*lighting+vec3(.015),v_color,u_grid);gl_FragColor=vec4(color,1.);}`);
      this.program=gl.createProgram();gl.attachShader(this.program,vertex);gl.attachShader(this.program,fragment);gl.linkProgram(this.program);gl.deleteShader(vertex);gl.deleteShader(fragment);
      if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw new Error('The 3D preview could not initialize.');
      this.locations={};for(const name of ['a_position','a_normal','a_color'])this.locations[name]=gl.getAttribLocation(this.program,name);
      for(const name of ['u_angles','u_center','u_scale','u_grid','u_model','u_normal','u_origin','u_extent'])this.locations[name]=gl.getUniformLocation(this.program,name);
      this.buffer=gl.createBuffer();this.gridBuffer=gl.createBuffer();
      canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();this.lost=true;});
      canvas.addEventListener('webglcontextrestored',()=>{this.lost=false;this.mesh=null;this.restored=true;canvas.dispatchEvent(new CustomEvent('preview-reload'));});
    }
    bind(buffer){const gl=this.gl;gl.bindBuffer(gl.ARRAY_BUFFER,buffer);for(const [i,name] of ['a_position','a_normal','a_color'].entries()){const location=this.locations[name];gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,3,gl.FLOAT,false,36,i*12);}}
    draw(mesh,yaw,tilt,zoom,light){
      if(this.lost)throw new Error('Graphics connection lost. Reload the page to restore the preview.');
      const gl=this.gl,w=this.canvas.clientWidth,h=this.canvas.clientHeight,dpr=Math.min(root.devicePixelRatio||1,2);
      if(this.canvas.width!==Math.round(w*dpr)||this.canvas.height!==Math.round(h*dpr)){this.canvas.width=Math.round(w*dpr);this.canvas.height=Math.round(h*dpr);}
      gl.viewport(0,0,this.canvas.width,this.canvas.height);gl.clearColor(...(light?[.95,.96,.98,1]:[.065,.078,.098,1]));gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      const revision=mesh?.scene?.revision||null;
      // Keep uploaded meshes while a plate loads. Clearing a view must not upload
      // the same hundreds of MB again on every plate switch or retry.
      if(mesh&&this.sceneRevision!==revision){for(const buffer of this.sceneBuffers.values())gl.deleteBuffer(buffer);this.sceneBuffers.clear();this.sceneRevision=revision;}
      if(!mesh)return;
      if(this.mesh!==mesh){
        if(mesh.scene)this.bounds=sceneView(mesh.scene,mesh.plate);
        else {this.bounds=geometry(mesh);gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.bufferData(gl.ARRAY_BUFFER,this.bounds.data,gl.STATIC_DRAW);this.bounds.data=null;}
        this.mesh=mesh;
      }
      const f=frame(this.bounds,yaw,tilt,w,h,zoom),loc=this.locations;gl.useProgram(this.program);gl.uniform4f(loc.u_angles,Math.cos(yaw),Math.sin(yaw),Math.cos(tilt),Math.sin(tilt));gl.uniform2fv(loc.u_center,f.center);gl.uniform2fv(loc.u_scale,f.scale);
      gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.disable(gl.CULL_FACE);gl.disable(gl.BLEND);gl.depthMask(true);
      gl.uniformMatrix4fv(loc.u_model,false,identity4);gl.uniformMatrix3fv(loc.u_normal,false,identity3);gl.uniform3fv(loc.u_origin,[0,0,0]);gl.uniform1f(loc.u_extent,1);
      const lines=[],tint=light?[.83,.85,.88]:[.12,.15,.19],z=this.bounds.low[2]-.003;
      const add=p=>lines.push(...p,0,0,1,...tint);
      for(let i=-15;i<=15;i++){const n=i*.1;add([-1.5,n,z]);add([1.5,n,z]);add([n,-1.5,z]);add([n,1.5,z]);}
      this.bind(this.gridBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(lines),gl.DYNAMIC_DRAW);gl.uniform1f(loc.u_grid,1);gl.drawArrays(gl.LINES,0,lines.length/9);
      gl.uniform1f(loc.u_grid,0);
      if(mesh.scene){
        gl.uniform3fv(loc.u_origin,this.bounds.origin);gl.uniform1f(loc.u_extent,this.bounds.extent);
        const descriptors=new Map(mesh.scene.meshes.map(m=>[m.id,m]));
        for(const instance of this.bounds.instances){
          let buffer=this.sceneBuffers.get(instance.mesh);
          if(!buffer){const data=mesh.buffers.get(instance.mesh);if(!data)throw new Error('A model mesh has not finished loading.');buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);this.sceneBuffers.set(instance.mesh,buffer);}
          this.bind(buffer);gl.uniformMatrix4fv(loc.u_model,false,modelMatrix(instance.transform));gl.uniformMatrix3fv(loc.u_normal,false,normalMatrix(instance.transform));gl.drawArrays(gl.TRIANGLES,0,descriptors.get(instance.mesh).vertex_count);
        }
      }else {this.bind(this.buffer);gl.drawArrays(gl.TRIANGLES,0,this.bounds.count);}
    }
  }
  root.PrintFlowModelRenderer={Renderer,geometry,frame,rotate,sceneView,modelMatrix,normalMatrix};
  if(typeof module!=='undefined')module.exports=root.PrintFlowModelRenderer;
})(typeof window!=='undefined'?window:globalThis);
