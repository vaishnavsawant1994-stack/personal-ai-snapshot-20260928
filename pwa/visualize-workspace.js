(()=>{
'use strict';

const API='/iphone/api/visualizations';
const TYPES=[
  ['architecture','Architecture','Components, services and relationships'],
  ['workflow','Workflow','Steps, agents, decisions and execution'],
  ['sequence','Sequence','Interactions ordered through time'],
  ['dataflow','Data Flow','Where information moves and changes'],
  ['lifecycle','Lifecycle','States, transitions and recovery'],
  ['project_map','Project Map','Goals, work, agents, tools and evidence'],
];
const icons={
  graph:'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="6" r="2.2"/><circle cx="19" cy="5" r="2.2"/><circle cx="7" cy="19" r="2.2"/><circle cx="18" cy="17" r="2.2"/><path d="M7 6.4 17 5.4M6 8l1 8.7m2-1 7-8.5m-7.2 11 7-1.2"/></svg>',
  back:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5m7-7-7 7 7 7"/></svg>',
  close:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>',
  plus:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
  project:'<svg viewBox="0 0 24 24"><path d="M3 7h7l2 2h9v10H3z"/><path d="M3 7V5h7l2 2"/></svg>',
  github:'<svg viewBox="0 0 24 24"><path d="M8 20c-4 1.3-4-2-5-2.5M15.5 22v-3.2a2.8 2.8 0 0 0-.8-2.2c2.6-.3 5.3-1.3 5.3-5.8A4.5 4.5 0 0 0 18.8 7a4.2 4.2 0 0 0-.1-3.7S17.7 3 15.5 4.5a12.7 12.7 0 0 0-7 0C6.3 3 5.3 3.3 5.3 3.3A4.2 4.2 0 0 0 5.2 7 4.5 4.5 0 0 0 4 10.8c0 4.5 2.7 5.5 5.3 5.8a2.8 2.8 0 0 0-.8 2.2V22"/></svg>',
  chat:'<svg viewBox="0 0 24 24"><path d="M4 5h16v12H9l-5 3z"/></svg>',
  file:'<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6zM14 3v5h5"/></svg>',
  search:'<svg viewBox="0 0 24 24"><circle cx="10.7" cy="10.7" r="6"/><path d="m15.3 15.3 4.5 4.5"/></svg>',
  export:'<svg viewBox="0 0 24 24"><path d="M12 16V3m-5 5 5-5 5 5M4 13v7h16v-7"/></svg>',
  history:'<svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 1 0 2-5.3L4 9M4 4v5h5M12 8v5l3 2"/></svg>',
};

const state={visuals:[],filter:'all',type:'architecture',sourceKind:'description',active:null,selectedNode:null,compare:null};
let workspace,viewer,mobileSheet,toastTimer;

function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]))}
function byId(id){return document.getElementById(id)}
async function request(path='',options={}){
  const response=await fetch(API+path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
  let data={};try{data=await response.json()}catch{}
  if(!response.ok)throw new Error((data.detail&&typeof data.detail==='object'?(data.detail.message||data.detail.code):data.detail)||data.error||`Request failed (${response.status})`);
  return data;
}
function showToast(message){
  let node=byId('vzToast');if(!node){node=document.createElement('div');node.id='vzToast';node.className='vz-toast';document.body.append(node)}
  node.textContent=message;node.classList.remove('vz-hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>node.classList.add('vz-hidden'),2800);
}
function inferTitle(text,type){
  const first=String(text||'').split(/\n|\.|:/)[0].trim().replace(/^(show|visualize|map|diagram)\s+(me\s+)?/i,'');
  return (first||TYPES.find(t=>t[0]===type)?.[1]||'Untitled visual').slice(0,92);
}
function typeLabel(type){return TYPES.find(item=>item[0]===type)?.[1]||type}
function sourceLabel(kind){return ({project:'Project',github:'GitHub',conversation:'Conversation',files:'Files & sources',description:'Description'})[kind]||kind}

function ensureNavEntry(){
  if(document.querySelector('[data-app-module="visualize"]'))return;
  const nav=document.querySelector('.sidebar-main-nav');if(!nav)return;
  const button=document.createElement('button');button.type='button';button.className='sidebar-nav-row';button.dataset.appModule='visualize';button.innerHTML=`${icons.graph}<span>Visualize</span>`;
  const tools=nav.querySelector('[data-app-module="tools"]');nav.insertBefore(button,tools||null);
  button.addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();closeDrawerIfOpen();openWorkspace()},{capture:true});
}
function closeDrawerIfOpen(){
  const drawer=byId('appDrawer'),overlay=byId('drawerOverlay');if(drawer){drawer.classList.add('hidden');drawer.setAttribute('aria-hidden','true')}if(overlay)overlay.classList.add('hidden');
}

function workspaceMarkup(){return `<section id="visualizeWorkspace" class="vz-workspace vz-hidden" aria-label="Vishnu Visualize">
<div class="vz-shell">
<header class="vz-topbar">
  <div class="vz-topbar-left"><button id="vzClose" class="vz-icon-btn" type="button" aria-label="Close Visualize">${icons.back}</button><span class="vz-title">Visualize</span></div>
  <div class="vz-status"><i></i><span>Visual intelligence</span></div>
  <div class="vz-topbar-right"><button id="vzRefresh" class="vz-action" type="button">Refresh</button><button id="vzNew" class="vz-action primary" type="button">+ Create visual</button></div>
</header>
<div class="vz-body">
  <aside class="vz-rail">
    <button id="vzCreateRail" class="vz-create-btn" type="button">+ Create visual</button>
    <div class="vz-rail-label" style="margin-top:20px">Visuals</div>
    <div id="vzFilters" class="vz-filter-list"></div>
    <div class="vz-rail-label">Recent</div><div id="vzRecentMini" class="vz-recent-mini"></div>
  </aside>
  <main class="vz-main" id="vzMain"></main>
  <aside id="vzInspector" class="vz-inspector vz-hidden-panel" aria-label="Visual details"></aside>
</div></div></section>`}

function homeMarkup(){return `<div class="vz-hero"><div class="vz-eyebrow">Visual intelligence workspace</div><h1>Turn anything into a visual system.</h1><p>Understand projects, code, workflows, conversations and knowledge as interactive maps with evidence, paths, versions and Vishnu context.</p></div>
<div id="vzPromptCard" class="vz-prompt-card"><textarea id="vzPrompt" placeholder="Describe what you want to visualize…\nExample: Browser → API → Redis → PostgreSQL"></textarea><div class="vz-prompt-footer"><div id="vzTypeSelector" class="vz-selector"></div><button id="vzGenerate" class="vz-generate" type="button">Generate</button></div></div>
<section class="vz-section"><div class="vz-section-head"><div><h2>Create from</h2><span>Use the context Vishnu already has</span></div></div><div class="vz-source-grid">
${sourceCard('project','Project', 'Goals, tasks, agents, files and live work',icons.project)}
${sourceCard('github','GitHub','Repository architecture and source evidence',icons.github)}
${sourceCard('conversation','Conversation','Turn a discussion into a system map',icons.chat)}
${sourceCard('files','Files & sources','Map documents, notes and structured data',icons.file)}
</div></section>
<section class="vz-section"><div class="vz-section-head"><div><h2>Recent visuals</h2><span id="vzRecentCount">0 visuals</span></div></div><div id="vzVisualGrid" class="vz-card-grid"></div></section>`}
function sourceCard(kind,title,subtitle,icon){return `<button class="vz-source-card" type="button" data-vz-source="${kind}"><span class="vz-source-icon">${icon}</span><strong>${title}</strong><span>${subtitle}</span></button>`}
function typeButtons(){return TYPES.map(([value,label])=>`<button class="vz-pill ${state.type===value?'active':''}" type="button" data-vz-type="${value}">${label}</button>`).join('')}

function renderFilters(){
  const filters=[['all','All visuals'],...TYPES.map(([v,l])=>[v,l])];
  const node=byId('vzFilters');if(!node)return;
  node.innerHTML=filters.map(([value,label])=>{const count=value==='all'?state.visuals.length:state.visuals.filter(v=>v.type===value).length;return `<button type="button" class="vz-filter ${state.filter===value?'active':''}" data-vz-filter="${value}"><span>${label}</span><b>${count}</b></button>`}).join('');
  node.querySelectorAll('[data-vz-filter]').forEach(btn=>btn.onclick=()=>{state.filter=btn.dataset.vzFilter;renderFilters();renderVisualCards()});
}
function renderMini(){
  const node=byId('vzRecentMini');if(!node)return;
  node.innerHTML=state.visuals.slice(0,5).map(v=>`<button type="button" class="vz-mini-card" data-vz-open="${v.id}"><strong>${esc(v.title)}</strong><span>${typeLabel(v.type)} · ${v.node_count} nodes</span></button>`).join('')||'<div class="vz-empty">No visuals yet</div>';
  node.querySelectorAll('[data-vz-open]').forEach(btn=>btn.onclick=()=>openVisual(btn.dataset.vzOpen));
}
function tinyGraph(v){
  const nodes=(v.graph?.nodes||[]).slice(0,9),edges=(v.graph?.edges||[]).slice(0,12),positions=new Map();
  nodes.forEach((n,i)=>positions.set(n.id,{x:18+(i%3)*41,y:22+Math.floor(i/3)*31}));
  return `<svg viewBox="0 0 120 100" aria-hidden="true">${edges.map(e=>{const a=positions.get(e.source),b=positions.get(e.target);return a&&b?`<path d="M${a.x} ${a.y} L${b.x} ${b.y}" stroke="#3f5879" stroke-width="1"/>`:''}).join('')}${nodes.map((n,i)=>{const p=positions.get(n.id);return `<circle cx="${p.x}" cy="${p.y}" r="${i===0?4.3:3.2}" fill="${i===0?'#6ab8ff':'#8294ad'}"/>`}).join('')}</svg>`;
}
function renderVisualCards(){
  const grid=byId('vzVisualGrid');if(!grid)return;
  const visuals=state.filter==='all'?state.visuals:state.visuals.filter(v=>v.type===state.filter);
  const count=byId('vzRecentCount');if(count)count.textContent=`${visuals.length} visual${visuals.length===1?'':'s'}`;
  if(!visuals.length){grid.innerHTML='<div class="vz-empty" style="grid-column:1/-1">No visuals in this view yet. Create one above.</div>';return}
  grid.innerHTML=visuals.map(v=>`<button type="button" class="vz-visual-card" data-vz-open="${v.id}"><div class="vz-thumb">${tinyGraph(v)}</div><div class="vz-card-copy"><strong>${esc(v.title)}</strong><span>${typeLabel(v.type)} · ${v.mode}</span><div class="vz-card-meta"><i>${v.node_count} nodes</i><i>${v.edge_count} links</i><i>${sourceLabel(v.source_kind)}</i></div></div></button>`).join('');
  grid.querySelectorAll('[data-vz-open]').forEach(btn=>btn.onclick=()=>openVisual(btn.dataset.vzOpen));
}
function wireHome(){
  byId('vzTypeSelector').innerHTML=typeButtons();
  byId('vzTypeSelector').querySelectorAll('[data-vz-type]').forEach(btn=>btn.onclick=()=>{state.type=btn.dataset.vzType;byId('vzTypeSelector').innerHTML=typeButtons();wireTypeButtonsOnly()});
  document.querySelectorAll('[data-vz-source]').forEach(btn=>btn.onclick=()=>selectSource(btn.dataset.vzSource));
  byId('vzGenerate').onclick=generateVisual;
}
function wireTypeButtonsOnly(){byId('vzTypeSelector')?.querySelectorAll('[data-vz-type]').forEach(btn=>btn.onclick=()=>{state.type=btn.dataset.vzType;byId('vzTypeSelector').innerHTML=typeButtons();wireTypeButtonsOnly()})}
function renderHome(){const main=byId('vzMain');main.innerHTML=homeMarkup();wireHome();renderFilters();renderMini();renderVisualCards()}

async function loadVisuals(){
  try{const data=await request();state.visuals=Array.isArray(data.visualizations)?data.visualizations:[];renderFilters();renderMini();renderVisualCards()}
  catch(error){showToast(error.message)}
}
function selectSource(kind){
  state.sourceKind=kind;const prompt=byId('vzPrompt');if(!prompt)return;
  const copy={project:'Visualize this Vishnu project: goals, work plan, tasks, agents, tools, files, milestones and current execution.',github:'Visualize this repository architecture with modules, services, APIs, data stores, dependencies and source evidence.',conversation:'Turn this conversation into a clear visual map of decisions, systems, steps and relationships.',files:'Analyze these files and sources, then visualize their structure, flows, dependencies and evidence.'};
  prompt.value=copy[kind]||'';prompt.focus();showToast(`${sourceLabel(kind)} selected. Add or paste the source context, then generate.`)
}
async function generateVisual(){
  const prompt=byId('vzPrompt'),description=prompt?.value.trim()||'';if(!description){showToast('Describe what you want Vishnu to visualize.');prompt?.focus();return}
  const button=byId('vzGenerate');button.disabled=true;button.textContent='Generating…';
  try{
    const body={title:inferTitle(description,state.type),type:state.type,mode:'manual',description,source_kind:state.sourceKind};
    const data=await request('',{method:'POST',body:JSON.stringify(body)});state.visuals.unshift(data.visualization);renderFilters();renderMini();renderVisualCards();prompt.value='';showToast('Visual created and verified.');openViewer(data.visualization)
  }catch(error){showToast(error.message)}finally{button.disabled=false;button.textContent='Generate'}
}

function viewerMarkup(v){return `<section id="vzViewer" class="vz-viewer" aria-label="${esc(v.title)}">
<header class="vz-topbar"><div class="vz-topbar-left"><button id="vzViewerBack" class="vz-icon-btn" type="button" aria-label="Back to Visualize">${icons.back}</button><div><div class="vz-title">${esc(v.title)}</div><div class="vz-status"><i></i><span>${typeLabel(v.type)} · ${esc(v.mode)}</span></div></div></div><div class="vz-status"><span>${v.node_count} nodes · ${v.edge_count} relationships</span></div><div class="vz-topbar-right"><button id="vzHistory" class="vz-action" type="button">History</button><button id="vzCompare" class="vz-action" type="button">Compare</button><button id="vzExport" class="vz-action primary" type="button">Export</button></div></header>
<div class="vz-viewer-main"><aside class="vz-viewer-panel"><div class="vz-section-label">Explore</div><input id="vzNodeSearch" class="vz-search" type="search" placeholder="Search this visual…"><div class="vz-section-label" style="margin-top:18px">Views</div><div class="vz-filter-list"><button class="vz-filter active" type="button"><span>Overview</span></button><button class="vz-filter" type="button" data-vz-action="clear"><span>Clear focus</span></button></div><div class="vz-section-label">Evidence</div><p style="color:#7f8ea3;font-size:.72rem;line-height:1.5">Node evidence levels distinguish verified, strong, inferred, user-supplied and unverified claims.</p></aside><div id="vzCanvas" class="vz-canvas">${v.svg||''}</div><aside id="vzViewerInspector" class="vz-viewer-panel right"></aside></div>
<div class="vz-viewer-composer"><form id="vzAskForm"><input id="vzAskInput" autocomplete="off" placeholder="Ask Vishnu about this visual…"><button type="submit" aria-label="Ask Vishnu">↑</button></form></div></section>`}
async function openVisual(id){
  try{const data=await request('/'+encodeURIComponent(id));openViewer(data.visualization)}catch(error){showToast(error.message)}
}
function openViewer(v){
  state.active=v;state.selectedNode=null;viewer?.remove();viewer=document.createElement('div');viewer.innerHTML=viewerMarkup(v);document.body.append(viewer.firstElementChild);viewer=byId('vzViewer');
  byId('vzViewerBack').onclick=closeViewer;byId('vzExport').onclick=()=>window.open(`${API}/${encodeURIComponent(v.id)}/artifact`,'_blank','noopener');
  byId('vzHistory').onclick=showHistory;byId('vzCompare').onclick=compareCurrent;byId('vzAskForm').onsubmit=askVishnu;
  byId('vzNodeSearch').oninput=event=>filterNodes(event.target.value);document.querySelector('[data-vz-action="clear"]')?.addEventListener('click',clearNodeFocus);
  byId('vzCanvas')?.querySelectorAll('.vv-node').forEach(node=>{node.addEventListener('click',()=>selectNode(node.dataset.nodeId));node.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectNode(node.dataset.nodeId)}})});
  renderInspector(null)
}
function closeViewer(){viewer?.remove();viewer=null;state.active=null;state.selectedNode=null;mobileSheet?.remove();mobileSheet=null}
function activeGraph(){return state.active?.graph||{nodes:[],edges:[]}}
function selectNode(id){
  state.selectedNode=id;byId('vzCanvas')?.querySelectorAll('.vv-node').forEach(node=>node.classList.toggle('vz-node-selected',node.dataset.nodeId===id));
  const node=activeGraph().nodes.find(item=>item.id===id);renderInspector(node);if(window.matchMedia('(max-width:720px)').matches)renderMobileSheet(node)
}
function clearNodeFocus(){state.selectedNode=null;byId('vzCanvas')?.querySelectorAll('.vv-node').forEach(node=>{node.classList.remove('vz-node-selected');node.style.opacity=''});byId('vzCanvas')?.querySelectorAll('[data-edge-id]').forEach(edge=>edge.style.opacity='');renderInspector(null);mobileSheet?.remove();mobileSheet=null}
function renderInspector(node){
  const panel=byId('vzViewerInspector');if(!panel)return;
  if(!node){panel.innerHTML='<div class="vz-section-label">Node intelligence</div><p style="color:#7f8ea3;font-size:.76rem;line-height:1.55">Select any node to inspect relationships, evidence and source metadata.</p>';return}
  const incoming=activeGraph().edges.filter(e=>e.target===node.id).length,outgoing=activeGraph().edges.filter(e=>e.source===node.id).length,evidence=(node.evidence||[]).length;
  panel.innerHTML=`<h3>${esc(node.label)}</h3><div class="vz-inspector-sub">${esc(node.category)} · ${esc(node.status||'active')}</div><div class="vz-inspector-section"><div class="vz-evidence"><i></i><span>${esc(String(node.evidence_level||'unverified').replaceAll('_',' '))}</span></div>${node.description?`<p style="font-size:.76rem;color:#9cabbd;line-height:1.55">${esc(node.description)}</p>`:''}</div><div class="vz-inspector-section"><h4>Relationships</h4><div class="vz-info-row"><span>Incoming</span><span>${incoming}</span></div><div class="vz-info-row"><span>Outgoing</span><span>${outgoing}</span></div><div class="vz-info-row"><span>Evidence</span><span>${evidence}</span></div><div class="vz-inspector-actions"><button type="button" data-reach="upstream">Upstream</button><button type="button" data-reach="downstream">Downstream</button><button type="button" id="vzFindPath">Find path</button><button type="button" id="vzAskNode">Ask Vishnu</button></div></div>`;
  panel.querySelectorAll('[data-reach]').forEach(button=>button.onclick=()=>runReach(node.id,button.dataset.reach));
  byId('vzFindPath').onclick=()=>findPath(node.id);byId('vzAskNode').onclick=()=>moveQuestionToChat(`Explain the “${node.label}” node in my visual “${state.active.title}”, including its role, connections and evidence.`)
}
function renderMobileSheet(node){
  mobileSheet?.remove();if(!node)return;mobileSheet=document.createElement('section');mobileSheet.className='vz-mobile-sheet';mobileSheet.innerHTML=`<div class="vz-mobile-sheet-handle"></div><button type="button" class="vz-icon-btn" style="float:right" aria-label="Close">${icons.close}</button><h3 style="margin:5px 0 2px">${esc(node.label)}</h3><div style="color:#7f8da2;font-size:.72rem">${esc(node.category)} · ${esc(String(node.evidence_level||'unverified').replaceAll('_',' '))}</div><div class="vz-inspector-actions" style="margin-top:16px"><button data-reach="upstream">Upstream</button><button data-reach="downstream">Downstream</button><button id="vzMobilePath">Find path</button><button id="vzMobileAsk">Ask Vishnu</button></div>`;document.body.append(mobileSheet);mobileSheet.querySelector('.vz-icon-btn').onclick=()=>{mobileSheet.remove();mobileSheet=null};mobileSheet.querySelectorAll('[data-reach]').forEach(b=>b.onclick=()=>runReach(node.id,b.dataset.reach));byId('vzMobilePath').onclick=()=>findPath(node.id);byId('vzMobileAsk').onclick=()=>moveQuestionToChat(`Explain “${node.label}” in the visual “${state.active.title}”.`)
}
function filterNodes(query){
  const q=String(query||'').trim().toLowerCase();const graph=activeGraph();const matched=new Set(graph.nodes.filter(n=>!q||`${n.label} ${n.category} ${n.description||''}`.toLowerCase().includes(q)).map(n=>n.id));
  byId('vzCanvas')?.querySelectorAll('.vv-node').forEach(node=>node.style.opacity=(!q||matched.has(node.dataset.nodeId))?'1':'.16');
  byId('vzCanvas')?.querySelectorAll('[data-edge-id]').forEach(edge=>{const item=graph.edges.find(e=>e.id===edge.dataset.edgeId);edge.style.opacity=(!q||matched.has(item?.source)||matched.has(item?.target))?'1':'.1'})
}
function highlightSet(nodeIds,edgeIds){const ns=new Set(nodeIds),es=new Set(edgeIds);byId('vzCanvas')?.querySelectorAll('.vv-node').forEach(n=>n.style.opacity=ns.has(n.dataset.nodeId)?'1':'.14');byId('vzCanvas')?.querySelectorAll('[data-edge-id]').forEach(e=>{e.style.opacity=es.has(e.dataset.edgeId)?'1':'.08';if(es.has(e.dataset.edgeId))e.style.stroke='#78d7ff'})}
async function runReach(origin,direction){try{const result=await request(`/${encodeURIComponent(state.active.id)}/reach`,{method:'POST',body:JSON.stringify({origin,direction})});highlightSet(result.node_ids,result.edge_ids);showToast(`${direction==='upstream'?'Upstream':'Downstream'}: ${result.node_ids.length} nodes · ${result.edge_ids.length} links · ${result.max_hops} hops`)}catch(error){showToast(error.message)}}
async function findPath(source){
  const options=activeGraph().nodes.filter(n=>n.id!==source);const answer=window.prompt('Find path to which node?\n'+options.slice(0,20).map(n=>`${n.id} — ${n.label}`).join('\n'));if(!answer)return;
  const target=(options.find(n=>n.id===answer.trim())||options.find(n=>n.label.toLowerCase()===answer.trim().toLowerCase()))?.id;if(!target){showToast('That node was not found.');return}
  try{const result=await request(`/${encodeURIComponent(state.active.id)}/path`,{method:'POST',body:JSON.stringify({source,target})});if(!result.found){showToast('No authored path was found.');return}highlightSet(result.node_ids,result.edge_ids);showToast(`Path found · ${result.hops} hops`)}catch(error){showToast(error.message)}
}
async function showHistory(){
  try{const data=await request(`/${encodeURIComponent(state.active.id)}/revisions`);const panel=byId('vzViewerInspector');panel.innerHTML=`<h3>Version history</h3><div class="vz-inspector-sub">${data.revisions.length} revision${data.revisions.length===1?'':'s'}</div><div class="vz-inspector-section">${data.revisions.map(r=>`<div style="padding:9px 0;border-bottom:1px solid rgba(145,171,207,.1)"><strong style="font-size:.76rem">Revision ${r.revision}</strong><div style="color:#7c8ca2;font-size:.68rem;margin-top:4px">${esc(r.reason)} · ${new Date(r.created_at).toLocaleString()}</div></div>`).join('')}</div>`}catch(error){showToast(error.message)}
}
async function compareCurrent(){
  if(state.visuals.length<2){showToast('Create another visual before comparing.');return}
  const candidates=state.visuals.filter(v=>v.id!==state.active.id);const answer=window.prompt('Compare this visual with which one?\n'+candidates.slice(0,20).map(v=>`${v.id.slice(0,8)} — ${v.title}`).join('\n'));if(!answer)return;
  const other=candidates.find(v=>v.id.startsWith(answer.trim()))||candidates.find(v=>v.title.toLowerCase()===answer.trim().toLowerCase());if(!other){showToast('Visual not found.');return}
  try{const result=await request('/compare',{method:'POST',body:JSON.stringify({before_id:other.id,after_id:state.active.id})});state.compare=result;const p=byId('vzViewerInspector');p.innerHTML=`<h3>Compare</h3><div class="vz-inspector-sub">${esc(other.title)} → ${esc(state.active.title)}</div><div class="vz-inspector-section"><div class="vz-info-row"><span>Added</span><span>${result.summary.added}</span></div><div class="vz-info-row"><span>Removed</span><span>${result.summary.removed}</span></div><div class="vz-info-row"><span>Changed</span><span>${result.summary.changed}</span></div></div>`}catch(error){showToast(error.message)}
}
function askVishnu(event){event.preventDefault();const input=byId('vzAskInput'),question=input?.value.trim();if(!question)return;const selected=state.selectedNode?activeGraph().nodes.find(n=>n.id===state.selectedNode):null;moveQuestionToChat(`About my visual “${state.active.title}”${selected?` and node “${selected.label}”`:''}: ${question}`)}
function moveQuestionToChat(text){
  closeViewer();closeWorkspace();const message=byId('message');if(message){message.value=text;message.dispatchEvent(new Event('input',{bubbles:true}));message.focus();showToast('Question moved to Vishnu chat.')}else{navigator.clipboard?.writeText(text);showToast('Question copied for Vishnu chat.')}
}

function openWorkspace(){workspace.classList.remove('vz-hidden');document.body.style.overflow='hidden';renderHome();loadVisuals()}
function closeWorkspace(){workspace.classList.add('vz-hidden');document.body.style.overflow='';closeViewer()}
function scrollCreate(){byId('vzPrompt')?.focus();byId('vzPromptCard')?.scrollIntoView({behavior:'smooth',block:'center'})}
function init(){
  ensureNavEntry();const holder=document.createElement('div');holder.innerHTML=workspaceMarkup();document.body.append(holder.firstElementChild);workspace=byId('visualizeWorkspace');
  byId('vzClose').onclick=closeWorkspace;byId('vzNew').onclick=scrollCreate;byId('vzCreateRail').onclick=scrollCreate;byId('vzRefresh').onclick=loadVisuals;renderHome();
  window.VishnuVisualize={open:openWorkspace,close:closeWorkspace,openVisual};
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
