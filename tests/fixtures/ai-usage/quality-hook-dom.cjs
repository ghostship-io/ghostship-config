// Minimal DOM boundary for the real hook: sanitized markup has no form controls.
// Element lookup is generic by attributes; no copy of the pager implementation.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const hook=JSON.parse(fs.readFileSync(process.argv[2])).panels.find(p=>p.id===250).options.afterRender;
const nodes=[];
class Element {
 constructor(tag='div'){this.tagName=tag;this.dataset={};this.attrs={};this.children=[];this.listeners={};this.value='';this.checked=false;nodes.push(this)}
 setAttribute(k,v){this.attrs[k]=v}
 append(...children){for(const child of children){this.children.push(child);child.parent=this}}
 addEventListener(event,fn){this.listeners[event]=fn}
 replaceWith(other){const siblings=this.parent.children;siblings[siblings.indexOf(this)]=other;other.parent=this.parent;nodes.splice(nodes.indexOf(this),1)}
 getBoundingClientRect(){return {width:1000}}
 querySelectorAll(selector){
  if(selector==='tbody tr.quality-model-row'||selector.startsWith('.'))return [];
  const m=selector.match(/^(?:([a-z]+))?\[([^=\]]+)(?:="([^"]*)")?\]$/);
  if(!m)throw Error('unsupported selector '+selector);
  return nodes.filter(node=>(!m[1]||node.tagName===m[1])&&Object.hasOwn(node.attrs,m[2])&&(m[3]===undefined||node.attrs[m[2]]===m[3]));
 }
 querySelector(selector){return this.querySelectorAll(selector)[0]||null}
}
const root=new Element('section');root.ownerDocument={createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})};
function fixture(tag,attr,value=''){const node=new Element(tag);node.setAttribute(attr,value);root.append(node);return node}
const controls=fixture('div','data-quality-controls');
fixture('th','data-col','passes');fixture('p','data-quality-evidence-note');fixture('p','data-quality-empty');
const expand=fixture('span','data-quality-expand-label');expand.textContent='Compare measured efforts';
let disconnected=false;
global.ResizeObserver=class{observe(){}disconnect(){disconnected=true}};
global.document={querySelector(){throw Error('the hook must use its own panel element')}};
const run=new Function('context',hook);
const context={element:{querySelector:selector=>selector==='section.quality'?root:null}};
const cleanup=run(context);
assert.equal(root.querySelector('[data-quality-filter]').type,'search');
assert.equal(root.querySelector('[data-quality-all]').type,'checkbox');
assert.equal(root.querySelector('[data-quality-range]').textContent,'No matching models');
assert.equal(typeof root.querySelector('[data-quality-filter]').listeners.input,'function');
assert.equal(typeof root.querySelector('[data-quality-all]').listeners.change,'function');
assert.equal(typeof root.querySelector('[data-quality-expand]').listeners.click,'function');
assert.equal(controls.children.length,3);
run(context);assert.equal(controls.children.length,3,'refresh must not duplicate controls');
cleanup();assert.ok(disconnected,'unmount releases the observer');
