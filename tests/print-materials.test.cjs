const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {readFileSync}=require('node:fs');

function setup(){
  class Element{
    constructor(tag='',classes='',text=''){Object.assign(this,{tag,className:classes,textContent:text,children:[],style:{},dataset:{},listeners:{},checked:false});}
    addEventListener(type,fn){this.listeners[type]=fn;}
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this.children=children;}
    querySelectorAll(){return this.children;}
  }
  const nodes={};const $=id=>nodes[id]??=new Element();
  const select=new Element();select.value='0';select.dataset.logicalTool='0';$('print-mapping-tools').append(select);
  const calls=[];const ui={pendingPrint:{job:{id:'j'},printerId:'u1'}};
  const context=vm.createContext({ui,$,el:(...args)=>new Element(...args),icon:()=>new Element(),button:(text,cls,fn)=>Object.assign(new Element('button',cls,text),{click:fn}),setText:(id,text)=>{$(id).textContent=text;},api:(path,body)=>new Promise((resolve,reject)=>calls.push({path,body,resolve,reject}))});
  vm.runInContext(readFileSync('web/static/colors.js','utf8'),context);
  const run=source=>vm.runInContext(source,context);
  return {$,calls,ui,run,select};
}
const good={rows:[],errors:[],warnings:[],materials_match:true,colors_match:true};

test('print requires a fresh successful check and the current cleared-bed checkbox',async()=>{
  const {$,calls,run}=setup();const pending=run('validatePrintColors()');
  $('print-bed-clear').checked=true;run('updatePrintStartState()');assert.equal($('start-mapped-print').disabled,true);
  assert.match(calls[0].path,/check-materials$/);calls[0].resolve(good);await pending;
  assert.equal($('start-mapped-print').disabled,false);
  $('print-bed-clear').checked=false;run('updatePrintStartState()');assert.equal($('start-mapped-print').disabled,true);
});

test('accepting a color difference cannot bypass a material or calibration error',async()=>{
  const {$,calls,run}=setup();$('print-bed-clear').checked=true;
  const pending=run('validatePrintColors()');calls[0].resolve({...good,materials_match:false,colors_match:false,warnings:['Different color'],errors:['Wrong hotend']});await pending;
  $('print-accept-substitution').checked=true;run('updatePrintStartState()');assert.equal($('start-mapped-print').disabled,true);
});

test('changing mapping clears stale validation and ignores late errors',async()=>{
  const {$,calls,run,select}=setup();$('print-bed-clear').checked=true;
  const old=run('validatePrintColors()');select.value='3';const current=run('validatePrintColors()');
  assert.equal(calls[1].body.mapping['0'],3);
  calls[1].resolve({...good,materials_match:false,errors:['Wrong hotend']});await current;
  calls[0].reject(new Error('Stale error'));await old;
  assert.equal($('start-mapped-print').disabled,true);
  assert.notEqual($('print-color-check').textContent,'Stale error');
  assert.equal(run('ui.pendingPrint.materialCheck.errors[0]'),'Wrong hotend');
});

test('a reply for a closed or replaced print dialog cannot enable the new one',async()=>{
  const {$,calls,ui,run}=setup();const pending=run('validatePrintColors()');
  ui.pendingPrint={job:{id:'other'},printerId:'u1'};calls[0].resolve(good);await pending;
  assert.equal(ui.pendingPrint.materialCheck,undefined);assert.equal($('start-mapped-print').disabled,true);
});
