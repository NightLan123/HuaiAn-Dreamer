'use strict';
// Small structural DOM, deliberately not described as a rendering browser.
const vm=require('node:vm'),assert=require('node:assert/strict');
function harness(nodes,source,fetch,build){
 const all=[],listeners={};
 function matches(n,s){
  if(s.includes(','))return s.split(',').some(v=>matches(n,v.trim()));
  if(s==='nav [data-view]')return !!n.dataset.view&&!!n.closest('nav');
  if(s==='dialog[open]')return n.tag==='dialog'&&n.open;
  if(s==='meta[name="app-build"]')return n.tag==='meta'&&n.attrs.name==='app-build';
  if(s.startsWith('.'))return n.classList.contains(s.slice(1));
  if(s.startsWith('[')){const m=s.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);return m&&Object.hasOwn(n.attrs,m[1])&&(m[2]===undefined||n.attrs[m[1]]===m[2]);}
  return n.tag===s;
 }
 function make(v){
  const classes=new Set((v.attrs.class||'').split(' '));let html='',value=v.attrs.value||'',dynamicOptions=null,explicitSelected=null;
  const node={...v,id:v.attrs.id||'',index:all.length,textContent:'',content:v.attrs.content||'',disabled:Object.hasOwn(v.attrs,'disabled'),hidden:Object.hasOwn(v.attrs,'hidden'),checked:Object.hasOwn(v.attrs,'checked'),
   dataset:Object.fromEntries(Object.entries(v.attrs).filter(([k])=>k.startsWith('data-')).map(([k,x])=>[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase()),x])),
   classList:{contains:c=>classes.has(c),toggle(c,on){on?classes.add(c):classes.delete(c)}},
   type:v.attrs.type||'',multiple:Object.hasOwn(v.attrs,'multiple'),listeners:{},
   getAttribute(k){return this.attrs[k]??null},setAttribute(k,v){this.attrs[k]=v},hasAttribute(k){return Object.hasOwn(this.attrs,k)},focus(){document.activeElement=this},after(n){n.parent=this.parent},addEventListener(t,fn){(this.listeners[t]??=[]).push(fn)},
   querySelectorAll(s){return all.filter(n=>{let p=n.parent;while(p!=null){if(p===this.index)return matches(n,s);p=all[p].parent;}return false})},
   querySelector(s){return this.querySelectorAll(s)[0]||null},closest(s){let n=this;while(n){if(matches(n,s))return n;n=n.parent==null?null:all[n.parent]}return null},
   showModal(){this.open=true},close(){this.open=false;for(const fn of this.listeners.close||[])fn({target:this})}};
  Object.defineProperty(node,'options',{get:()=>dynamicOptions||node.querySelectorAll('option'),set:v=>{dynamicOptions=v}});
  Object.defineProperty(node,'selectedOptions',{get:()=>explicitSelected||node.options.filter(o=>o.selected||(!node.multiple&&o.value===value)),set:v=>{explicitSelected=v}});
  Object.defineProperty(node,'innerHTML',{get:()=>html,set(v){html=v;if(node.tag==='select'){const options=[...v.matchAll(/<option\b([^>]*)value="([^"]*)"([^>]*)>/g)];dynamicOptions=options.map(o=>({value:o[2],selected:(o[1]+o[3]).includes('selected')}));explicitSelected=null;value=(options.find(o=>(o[1]+o[3]).includes('selected'))||options[0])?.[2]||'';}}});
  Object.defineProperty(node,'value',{get:()=>value,set:v=>{value=String(v)}});
  all.push(node);return node;
 }
 nodes.forEach(v=>make({...v,attrs:{...v.attrs}}));
 const ids=new Map(all.filter(n=>n.id).map(n=>[n.id,n]));
 const document={getElementById(id){assert(ids.has(id),'Missing DOM id '+id);return ids.get(id)},querySelectorAll:s=>all.filter(n=>matches(n,s)),querySelector:s=>all.find(n=>matches(n,s))||null,createElement:tag=>make({tag,attrs:{},parent:null}),
  addEventListener(type,fn,capture=false){(listeners[type]??=[]).push({fn,capture})}};
 document.querySelector('meta[name="app-build"]').content=build;
 const context=vm.createContext({document,console,Date,setTimeout,clearTimeout,fetch,navigator:{clipboard:{async writeText(){}}},confirm:()=>false,prompt:()=>null});
 const run=script=>vm.runInContext(script,context);
 run(source.replace(/\nrefresh\(\)\.then/, '\nglobalThis.bootReady=refresh().then'));
 async function event(node,type='click',extra={}){
  const e={type,target:node,stopped:false,preventDefault(){},stopImmediatePropagation(){this.stopped=true},...extra};
  if(node.disabled)return;
  for(const l of listeners[type]||[])if(l.capture){await l.fn(e);if(e.stopped)return;}
  if(node['on'+type])await node['on'+type](e);
  for(const fn of node.listeners[type]||[])await fn(e);
  for(const l of listeners[type]||[])if(!l.capture){await l.fn(e);if(e.stopped)return;}
 }
 return {run,ids,all,document,boot:run('bootReady'),click:id=>event(ids.get(id)),submit:id=>event(ids.get(id),'submit'),event,make};
}
module.exports={harness};
