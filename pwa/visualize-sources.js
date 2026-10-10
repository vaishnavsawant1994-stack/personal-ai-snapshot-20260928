(()=>{
'use strict';

const API='/iphone/api/visualizations';
let lastPanel=null;
let observer=null;

function esc(value){return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch]));}
function getState(){return window.__VISHNU_VISUALIZE__?.getState?.()||null;}
async function request(path,options={}){
  const response=await fetch(API+path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
  let data={};try{data=await response.json();}catch{}
  if(!response.ok){const detail=data?.detail;throw new Error((typeof detail==='object'?(detail.message||detail.code):detail)||data.error||`Request failed (${response.status})`);}
  return data;
}
function toast(message){
  let node=document.getElementById('vzToast');
  if(!node){node=document.createElement('div');node.id='vzToast';node.className='vz-toast';document.body.append(node);}
  node.textContent=message;node.classList.remove('vz-hidden');clearTimeout(node._timer);node._timer=setTimeout(()=>node.classList.add('vz-hidden'),2800);
}
function nodeLabel(graph,id){return graph?.nodes?.find(node=>node.id===id)?.label||id;}
function renderPathResult(root,result,graph){
  let resultNode=root.querySelector('[data-vz-path-result]');
  if(!resultNode){resultNode=document.createElement('div');resultNode.dataset.vzPathResult='';resultNode.className='vz-path-result';root.append(resultNode);}
  if(!result?.found){resultNode.innerHTML='<strong>No authored path found</strong><span>Vishnu did not find a relationship path between those two nodes.</span>';return;}
  const labels=(result.node_ids||[]).map(id=>nodeLabel(graph,id));
  resultNode.innerHTML=`<strong>${Number(result.hops||Math.max(0,labels.length-1))} hop${Number(result.hops||0)===1?'':'s'}</strong><span>${labels.map(esc).join(' → ')}</span>`;
}
async function submitPath(event){
  event.preventDefault();
  const state=getState();
  const root=event.currentTarget.closest('.vz-context-section');
  if(!state?.active?.id||!state.selectedNode||!root){toast('Select a visual node first.');return;}
  const select=event.currentTarget.querySelector('[data-vz-path-target]');
  const target=select?.value;
  if(!target){toast('Choose a target node.');return;}
  const button=event.currentTarget.querySelector('button[type="submit"]');
  if(button){button.disabled=true;button.textContent='Finding…';}
  try{
    const result=await request('/'+encodeURIComponent(state.active.id)+'/path',{method:'POST',body:JSON.stringify({source:state.selectedNode,target})});
    state.path=result;
    renderPathResult(root,result,state.active.graph);
  }catch(error){toast(error.message);}
  finally{if(button){button.disabled=false;button.textContent='Find path';}}
}
function enhancePaths(){
  const panel=document.getElementById('vzContextPanel');
  if(!panel||panel===lastPanel&&panel.querySelector('[data-vz-path-form]'))return;
  const activeTab=[...panel.querySelectorAll('[data-vz-context-tab]')].find(button=>button.classList.contains('active'));
  if(!activeTab||activeTab.dataset.vzContextTab!=='paths')return;
  const state=getState();
  const section=panel.querySelector('.vz-context-section');
  if(!state?.active?.graph||!state.selectedNode||!section||section.querySelector('[data-vz-path-form]'))return;
  const targets=(state.active.graph.nodes||[]).filter(node=>node.id!==state.selectedNode);
  const form=document.createElement('form');
  form.className='vz-find-path';form.dataset.vzPathForm='';
  form.innerHTML=`<label><span>Find path to</span><select data-vz-path-target aria-label="Path target">${targets.map(node=>`<option value="${esc(node.id)}">${esc(node.label)}</option>`).join('')}</select></label><button type="submit" ${targets.length?'':'disabled'}>Find path</button>`;
  form.addEventListener('submit',submitPath);
  section.append(form);
  if(state.path)renderPathResult(section,state.path,state.active.graph);
  lastPanel=panel;
}
function start(){
  enhancePaths();
  observer?.disconnect();
  observer=new MutationObserver(enhancePaths);
  observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['class']});
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
window.VishnuVisualizePathEnhancer={refresh:enhancePaths};
})();
