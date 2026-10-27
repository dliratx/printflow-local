const test=require('node:test'),assert=require('node:assert/strict');
const {geometry,frame,rotate}=require('../web/static/model-renderer.js');
test('GPU geometry preserves every triangle and its configured color',()=>{
  const mesh={vertices:[[0,0,0],[1,0,0],[0,1,0],[0,0,1],[1,0,1],[0,1,1]],faceColors:['#FF0000','#0000FF']};
  const result=geometry(mesh);assert.equal(result.count,6);assert.equal(result.data.length,54);
  assert.deepEqual(Array.from(result.data.slice(6,9)),[1,0,0]);assert.deepEqual(Array.from(result.data.slice(33,36)),[0,0,1]);
  assert.deepEqual(result.low,[0,0,0]);assert.deepEqual(result.high,[1,1,1]);
});
test('fit view contains tall and wide models at rotated viewing angles',()=>{
  for(const high of [[1,.2,.2],[.2,.2,1]])for(const yaw of [-.55,1.15,3]){
    const bounds={low:[0,0,0],high},fit=frame(bounds,yaw,.6,600,400);
    for(const x of [0,high[0]])for(const y of [0,high[1]])for(const z of [0,high[2]]){
      const p=rotate([x,y,z],yaw,.6);assert.ok(Math.abs((p[0]-fit.center[0])*fit.scale[0])<=.781);assert.ok(Math.abs((p[1]-fit.center[1])*fit.scale[1])<=.781);
    }
  }
});
