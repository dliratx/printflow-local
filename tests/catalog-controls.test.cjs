const test=require('node:test'),assert=require('node:assert/strict');
const {filterFiles,format}=require('../web/static/catalog-controls.js');
const files=Object.freeze([
  Object.freeze({id:'a',name:'Café tray 10.stl',folder:'Home',size:500,created_at:'2026-10-22T10:00:00Z'}),
  Object.freeze({id:'b',name:'Cafe tray 2.3mf',folder:'Home',extension:'.3mf',size:1200,created_at:'2026-10-24T10:00:00Z'}),
  Object.freeze({id:'c',name:'Tray joint.STL',folder:'Workshop',size:200,created_at:'2026-10-23T10:00:00Z'})
]);
test('folder, format and accent-insensitive multiword search compose without changing source files',()=>{
  assert.deepEqual(filterFiles(files,{folder:'Home',format:'3mf',search:'tray CAFE'}).map(f=>f.id),['b']);
  assert.deepEqual(files.map(f=>f.id),['a','b','c']);
  assert.equal(format(files[2]),'STL');
});
test('newest, natural name and size orders preserve original model identities',()=>{
  assert.deepEqual(filterFiles(files).map(f=>f.id),['b','c','a']);
  assert.deepEqual(filterFiles(files,{sort:'name'}).map(f=>f.id),['b','a','c']);
  assert.deepEqual(filterFiles(files,{sort:'size'}).map(f=>f.id),['b','a','c']);
  assert.equal(filterFiles(files,{format:'3mf'})[0],files[1]);
});
test('empty and missing-date libraries have deterministic order and honest filtered emptiness',()=>{
  assert.deepEqual(filterFiles(null),[]);
  assert.deepEqual(filterFiles(files,{folder:'Workshop',format:'3mf'}),[]);
  assert.deepEqual(filterFiles([{id:1,name:'a'},{id:2,name:'b'}]).map(f=>f.id),[2,1]);
});
