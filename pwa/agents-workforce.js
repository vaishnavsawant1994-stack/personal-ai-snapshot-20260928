(()=>{
  'use strict';
  const API='/iphone/api/agents';
  const state={agents:[],projects:[],selected:null,detail:null,tab:'overview',catalog:'all',conversation:null,chatProject:null,loading:false};
  const $=(q,root=document)=>root.querySelector(q);
  const $$=(q,root=document)=>[...root.querySelectorAll(q)];
  const esc=value=>String(value??'').replace(/[&<>'"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const fmtTime=value=>{try{return new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(new Date(value))}catch{return String(value||'')}};
  const short=value=>String(value||'').replace(/^agent(ver|chat|msg)?_/,'').slice(0,10);
  const toast=(message,error=false)=>{const el=$('#toast');el.textContent=message;el.className='aw-toast show'+(error?' error':'');clearTimeout(toast.t);toast.t=setTimeout(()=>el.className='aw-toast',3200)};
  const errorText=async response=>{try{const body=await response.json();const detail=body?.detail;return typeof detail==='string'?detail:(detail?.message||detail?.code||body?.message||`Request failed (${response.status})`)}catch{return `Request failed (${response.status})`}};
  async function api(path,options={}){
    const init={credentials:'same-origin',headers:{Accept:'application/json',...(options.body?{'Content-Type':'application/json'}:{}),...(options.headers||{})},...options};
    const response=await fetch(API+path,init);
    if(!response.ok)throw new Error(await errorText(response));
    if(response.status===204)return null;
    return response.json();
  }
  async function projectApi(path=''){
    const response=await fetch('/iphone/api/projects'+path,{credentials:'same-origin',headers:{Accept:'application/json'}});
    if(!response.ok)throw new Error(await errorText(response));
    return response.json();
  }
  const projectName=id=>state.projects.find(p=>p.id===id)?.name||id||'Unassigned';
  const preferred=detail=>detail?.versions?.find(v=>v.state==='preferred')||detail?.versions?.find(v=>v.state==='stable')||detail?.versions?.[0]||null;
  const iconFor=agent=>({coding:'</>',research:'Q',browser:'◎',data:'DB',reviewer:'✓',qa:'QA',security:'◇',design:'✦',project_manager:'PM',files:'F',communications:'C',knowledge:'K'}[agent.role]||'V');
  const stateBadge=value=>`<span class="aw-badge ${esc(value)}">${esc(value||'unknown')}</span>`;
  const empty=(title,copy)=>`<div class="aw-empty-state"><div class="aw-empty-orb">V</div><h2>${esc(title)}</h2><p>${esc(copy)}</p></div>`;

  function renderKpis(summary={}){
    const values={...summary,success_rate:summary.success_rate==null?'—':`${summary.success_rate}%`};
    $$('[data-kpi]').forEach(el=>{const key=el.dataset.kpi;el.textContent=values[key]??'—'});
    const health=$('#healthCopy');
    if(health)health.textContent=`${summary.active_instances??0} active instance${summary.active_instances===1?'':'s'} · ${summary.running_tasks??0} running task${summary.running_tasks===1?'':'s'}`;
  }
  function filteredAgents(){
    const q=($('#agentSearch')?.value||$('#globalSearch')?.value||'').trim().toLowerCase();
    const status=$('#statusFilter')?.value||'all';
    const sort=$('#sortFilter')?.value||'usage';
    let rows=state.agents.filter(agent=>{
      if(state.catalog==='system'&&!agent.system_owned)return false;
      if(state.catalog==='custom'&&agent.system_owned)return false;
      if(state.catalog==='active'&&!agent.active_instance_count)return false;
      if(status==='active'&&!agent.active_instance_count)return false;
      if(status==='idle'&&agent.active_instance_count)return false;
      if(q&&!`${agent.name} ${agent.role} ${agent.description} ${(agent.preferred_version?.capabilities||[]).join(' ')}`.toLowerCase().includes(q))return false;
      return true;
    });
    rows.sort((a,b)=>sort==='name'?a.name.localeCompare(b.name):sort==='versions'?(b.version_count-a.version_count):(b.instance_count-a.instance_count||a.name.localeCompare(b.name)));
    return rows;
  }
  function renderAgentList(){
    const root=$('#agentList');if(!root)return;
    const rows=filteredAgents();
    if(!rows.length){root.innerHTML='<div class="aw-loading">No agents match these filters.</div>';return}
    root.innerHTML=rows.map(agent=>`<button class="aw-agent-card ${state.selected===agent.id?'active':''}" data-agent-id="${esc(agent.id)}">
      <span class="aw-agent-icon">${esc(iconFor(agent))}</span>
      <span class="aw-agent-copy"><strong>${esc(agent.name)}</strong><small>${esc(agent.description||agent.role)}</small></span>
      <span class="aw-agent-stats"><b>${agent.active_instance_count||0}/${agent.instance_count||0}</b><small>${esc(agent.preferred_version?.version||'—')}</small></span>
    </button>`).join('');
    $$('[data-agent-id]',root).forEach(btn=>btn.addEventListener('click',()=>selectAgent(btn.dataset.agentId)));
  }
  async function selectAgent(id){
    state.selected=id;state.tab='overview';state.conversation=null;renderAgentList();
    const root=$('#agentDetail');root.innerHTML='<div class="aw-loading">Loading agent…</div>';
    try{state.detail=await api('/'+encodeURIComponent(id));renderDetail()}catch(error){root.innerHTML=`<div class="aw-error">${esc(error.message)}</div>`;toast(error.message,true)}
  }
  function agentProjects(detail){return [...new Set((detail.instances||[]).map(i=>i.project_id).filter(Boolean))]}
  function averageScore(detail){const scores=(detail.observations||[]).map(o=>Number(o.score)).filter(Number.isFinite);return scores.length?(scores.reduce((a,b)=>a+b,0)/scores.length):null}
  function renderDetail(){
    const d=state.detail,root=$('#agentDetail');if(!d){root.innerHTML=empty('Select an agent','Open a specialist to inspect its versions, workers, Projects and direct work chat.');return}
    const pref=preferred(d),active=(d.instances||[]).filter(i=>!['idle','completed','failed','stopped'].includes(i.state)).length;
    root.innerHTML=`
      <div class="aw-detail-head">
        <span class="aw-agent-icon">${esc(iconFor(d))}</span>
        <div class="aw-detail-title"><h2>${esc(d.name)} ${pref?stateBadge(pref.state):''}</h2><p>${esc(d.description||d.role)} · ${esc(pref?.version||'No version')}</p></div>
        <div class="aw-detail-actions"><button class="aw-btn primary" data-detail-action="chat">Chat</button><button class="aw-btn" data-detail-action="instance">＋ Instance</button><button class="aw-btn" data-detail-action="version">＋ Version</button></div>
      </div>
      <div class="aw-detail-tabs">${['overview','chat','instances','projects','versions','skills','tools','memory','performance','activity','settings'].map(tab=>`<button class="${state.tab===tab?'active':''}" data-detail-tab="${tab}">${tab[0].toUpperCase()+tab.slice(1)}</button>`).join('')}</div>
      <div class="aw-detail-body" id="detailBody"></div>`;
    $$('[data-detail-tab]',root).forEach(btn=>btn.addEventListener('click',()=>{state.tab=btn.dataset.detailTab;state.conversation=null;renderDetail()}));
    $$('[data-detail-action]',root).forEach(btn=>btn.addEventListener('click',()=>{
      const action=btn.dataset.detailAction;if(action==='chat'){state.tab='chat';renderDetail()}else if(action==='instance')openInstanceDialog();else if(action==='version')openVersionDialog();
    }));
    const renderers={overview:renderOverview,chat:renderChat,instances:renderInstances,projects:renderProjects,versions:renderVersions,skills:renderSkills,tools:renderTools,memory:renderMemory,performance:renderPerformance,activity:renderActivity,settings:renderSettings};
    (renderers[state.tab]||renderOverview)();
    void active;
  }
  function renderOverview(){
    const d=state.detail,pref=preferred(d),projects=agentProjects(d),score=averageScore(d),body=$('#detailBody');
    body.innerHTML=`<div class="aw-grid">
      <div class="aw-stat"><small>Total instances</small><strong>${(d.instances||[]).filter(i=>i.state!=='stopped').length}</strong></div>
      <div class="aw-stat"><small>Active now</small><strong>${(d.instances||[]).filter(i=>!['idle','completed','failed','stopped'].includes(i.state)).length}</strong></div>
      <div class="aw-stat"><small>Projects</small><strong>${projects.length}</strong></div>
      <div class="aw-stat"><small>Evidence score</small><strong>${score==null?'—':score.toFixed(1)}</strong></div>
    </div>
    <section class="aw-section"><div class="aw-section-head"><h3>Capabilities</h3><span class="aw-meta">${esc(pref?.version||'—')}</span></div><div class="aw-chip-row">${(pref?.capabilities||[]).map(x=>`<span class="aw-chip">${esc(x)}</span>`).join('')||'<span class="aw-muted">No capabilities declared.</span>'}</div></section>
    <section class="aw-section"><h3>Current Projects</h3><div class="aw-list">${projects.map(id=>`<div class="aw-row"><div class="aw-row-main"><strong>${esc(projectName(id))}</strong><small>${(d.instances||[]).filter(i=>i.project_id===id).length} instance(s)</small></div></div>`).join('')||'<div class="aw-muted">No Project instances yet.</div>'}</div></section>
    <section class="aw-section"><h3>Governance</h3><div class="aw-note">This specialist supplies intelligence only. Tool execution, approvals, receipts, Evidence, recovery and canonical completion remain controlled by Vishnu's existing Work authority.</div></section>`;
  }
  async function renderChat(){
    const body=$('#detailBody'),d=state.detail,projectIds=agentProjects(d);
    const candidates=projectIds.length?state.projects.filter(p=>projectIds.includes(p.id)):state.projects;
    if(!candidates.length){body.innerHTML=empty('Create a Project first','Specialist chat is always bound to one Project so context cannot silently mix.');return}
    if(!state.chatProject||!candidates.some(p=>p.id===state.chatProject))state.chatProject=candidates[0].id;
    body.innerHTML=`<div class="aw-chat-shell"><aside class="aw-chat-sidebar"><div class="aw-section-head"><h4>Chats</h4><button class="aw-btn small" id="newAgentChat">＋ New</button></div><div id="chatThreads"><div class="aw-loading">Loading…</div></div></aside><div class="aw-chat-main"><div class="aw-chat-controls"><select id="chatProjectSelect">${candidates.map(p=>`<option value="${esc(p.id)}" ${p.id===state.chatProject?'selected':''}>${esc(p.name)}</option>`).join('')}</select><span class="aw-meta">Project-only context · no tool authority</span></div><div class="aw-messages" id="chatMessages"><div class="aw-chat-empty">Choose or create a chat.</div></div><form class="aw-chat-composer" id="agentChatForm"><textarea id="agentChatInput" placeholder="Message ${esc(d.name)}…" required></textarea><button class="aw-btn primary" type="submit">Send</button></form></div></div>`;
    $('#chatProjectSelect').addEventListener('change',event=>{state.chatProject=event.target.value;state.conversation=null;loadChatThreads()});
    $('#newAgentChat').addEventListener('click',()=>createAgentChat());
    $('#agentChatForm').addEventListener('submit',sendAgentChat);
    await loadChatThreads();
  }
  async function loadChatThreads(){
    const root=$('#chatThreads');if(!root)return;
    try{
      const data=await api(`/${encodeURIComponent(state.detail.id)}/conversations?project_id=${encodeURIComponent(state.chatProject)}&limit=100`);
      const rows=data.conversations||[];
      root.innerHTML=rows.map(row=>`<button class="aw-chat-thread ${state.conversation?.id===row.id?'active':''}" data-chat-id="${esc(row.id)}"><strong>${esc(row.title)}</strong><small>${esc(fmtTime(row.updated_at))} · ${esc(short(row.version_id))}</small></button>`).join('')||'<div class="aw-muted">No chats yet.</div>';
      $$('[data-chat-id]',root).forEach(btn=>btn.addEventListener('click',()=>loadConversation(btn.dataset.chatId)));
      if(!state.conversation&&rows.length)await loadConversation(rows[0].id);
      else if(!rows.length)renderMessages();
    }catch(error){root.innerHTML=`<div class="aw-error">${esc(error.message)}</div>`}
  }
  async function createAgentChat(){
    try{
      const matching=(state.detail.instances||[]).find(i=>i.project_id===state.chatProject&&i.state!=='stopped');
      const data=await api(`/${encodeURIComponent(state.detail.id)}/conversations`,{method:'POST',body:JSON.stringify({project_id:state.chatProject,instance_id:matching?.id||null,title:`${state.detail.name} · ${projectName(state.chatProject)}`})});
      state.conversation={...data.conversation,messages:[]};await loadChatThreads();await loadConversation(data.conversation.id);toast('Agent chat created');
    }catch(error){toast(error.message,true)}
  }
  async function loadConversation(id){
    try{state.conversation=await api(`/conversations/${encodeURIComponent(id)}?project_id=${encodeURIComponent(state.chatProject)}`);renderMessages();await loadChatThreadsHighlight()}catch(error){toast(error.message,true)}
  }
  async function loadChatThreadsHighlight(){const root=$('#chatThreads');if(!root)return;$$('[data-chat-id]',root).forEach(btn=>btn.classList.toggle('active',btn.dataset.chatId===state.conversation?.id))}
  function renderMessages(){
    const root=$('#chatMessages');if(!root)return;
    const rows=state.conversation?.messages||[];
    root.innerHTML=rows.length?rows.map(row=>`<div class="aw-message ${row.role==='user'?'user':'assistant'}"><div class="bubble">${esc(row.content)}</div><small>${esc(row.role==='assistant'?[row.provider,row.model_id].filter(Boolean).join(' · '):fmtTime(row.created_at))}</small></div>`).join(''):'<div class="aw-chat-empty">Start a project-scoped conversation with this specialist.</div>';
    root.scrollTop=root.scrollHeight;
  }
  async function sendAgentChat(event){
    event.preventDefault();const input=$('#agentChatInput');const prompt=input.value.trim();if(!prompt)return;
    if(!state.conversation){await createAgentChat();if(!state.conversation)return}
    input.value='';input.disabled=true;
    const root=$('#chatMessages');if(root){root.insertAdjacentHTML('beforeend',`<div class="aw-message user"><div class="bubble">${esc(prompt)}</div><small>sending…</small></div>`);root.scrollTop=root.scrollHeight}
    try{
      const data=await api(`/conversations/${encodeURIComponent(state.conversation.id)}/messages`,{method:'POST',body:JSON.stringify({project_id:state.chatProject,prompt,sensitivity:'internal'})});
      state.conversation={...data.conversation,messages:[...(state.conversation.messages||[]),data.user_message,data.assistant_message]};renderMessages();
    }catch(error){toast(error.message,true);await loadConversation(state.conversation.id)}finally{input.disabled=false;input.focus()}
  }
  function renderInstances(){
    const body=$('#detailBody'),rows=state.detail.instances||[];
    body.innerHTML=`<div class="aw-section-head"><div><h3>Runtime instances</h3><span class="aw-meta">Each instance is permanently bound to one Project.</span></div><button class="aw-btn primary" id="createInstanceInline">＋ Create Instance</button></div><section class="aw-section"><table class="aw-table"><thead><tr><th>ID</th><th>Project</th><th>Version</th><th>Status</th><th>Current Work</th><th>Model</th></tr></thead><tbody>${rows.map(i=>`<tr><td class="aw-code">${esc(short(i.id))}</td><td>${esc(projectName(i.project_id))}</td><td class="aw-code">${esc(short(i.version_id))}</td><td><span class="aw-state ${esc(i.state)}">${esc(i.state)}</span></td><td class="aw-code">${esc(i.current_work_order_id?short(i.current_work_order_id):'—')}</td><td>${esc([i.model_provider,i.model_id].filter(Boolean).join(' / ')||'Auto')}</td></tr>`).join('')||'<tr><td colspan="6" class="aw-muted">No instances yet.</td></tr>'}</tbody></table></section>`;
    $('#createInstanceInline').addEventListener('click',openInstanceDialog);
  }
  function renderProjects(){
    const body=$('#detailBody'),d=state.detail,ids=agentProjects(d);
    body.innerHTML=`<div class="aw-section-head"><div><h3>Project assignments</h3><span class="aw-meta">Teams are isolated by Project.</span></div><button class="aw-btn primary" id="buildTeam">Build Team</button></div>${ids.map(id=>{const members=(d.instances||[]).filter(i=>i.project_id===id);return `<div class="aw-project-card"><strong>${esc(projectName(id))}</strong><small>${members.length} ${esc(d.name)} instance(s)</small><div class="aw-project-members">${members.map(i=>`<span class="aw-project-member">${esc(short(i.id))} · ${esc(i.state)}</span>`).join('')}</div></div>`}).join('')||'<div class="aw-section"><span class="aw-muted">This agent is not assigned to a Project yet.</span></div>'}<section class="aw-section"><div class="aw-note">Creating a team always adds a Project Manager. Agent instances cannot be moved across Projects; Vishnu creates a fresh instance instead.</div></section>`;
    $('#buildTeam').addEventListener('click',openTeamDialog);
  }
  function renderVersions(){
    const body=$('#detailBody');body.innerHTML=`<div class="aw-section-head"><div><h3>Agent Versions</h3><span class="aw-meta">Historical versions remain attributable to their work.</span></div><button class="aw-btn primary" id="createVersionInline">＋ New Candidate</button></div><div>${(state.detail.versions||[]).map(v=>`<article class="aw-version"><div class="aw-version-top"><h4>${esc(v.version)} ${stateBadge(v.state)}</h4><span class="aw-code">${esc(short(v.id))}</span></div><div class="aw-version-meta"><span>${esc((v.capabilities||[]).length)} capabilities</span><span>${esc((v.tools||[]).length)} tools</span><span>memory: ${esc(v.memory_policy)}</span><span>${esc(fmtTime(v.created_at))}</span></div><p>${esc(v.instructions||'No version-specific instructions.')}</p></article>`).join('')||'<div class="aw-muted">No versions.</div>'}</div><section class="aw-section"><div class="aw-note">Candidate versions do not self-promote. Stable/preferred adoption requires qualification evidence; old versions remain stored and existing assignments keep their exact version.</div></section>`;$('#createVersionInline').addEventListener('click',openVersionDialog)
  }
  function renderSkills(){const p=preferred(state.detail);$('#detailBody').innerHTML=`<section class="aw-section"><h3>Declared capabilities · ${esc(p?.version||'—')}</h3><div class="aw-chip-row">${(p?.capabilities||[]).map(x=>`<span class="aw-chip">${esc(x)}</span>`).join('')||'<span class="aw-muted">No capabilities declared.</span>'}</div></section><section class="aw-section"><div class="aw-note">Capabilities affect model/worker matching only. They do not grant tool permissions or execution authority.</div></section>`}
  function renderTools(){const p=preferred(state.detail);$('#detailBody').innerHTML=`<section class="aw-section"><h3>Requested tools · ${esc(p?.version||'—')}</h3><div class="aw-chip-row">${(p?.tools||[]).map(x=>`<span class="aw-chip">${esc(x)}</span>`).join('')||'<span class="aw-muted">No version-specific tool requests.</span>'}</div></section><section class="aw-section"><div class="aw-note">Installed/requested tools are not permission. Every consequential tool action still passes Vishnu policy, scope, approval, effect receipt and Evidence gates.</div></section>`}
  function renderMemory(){const versions=state.detail.versions||[];$('#detailBody').innerHTML=`<section class="aw-section"><h3>Memory policy by version</h3><div class="aw-list">${versions.map(v=>`<div class="aw-row"><div class="aw-row-main"><strong>${esc(v.version)}</strong><small>${esc(v.memory_policy)} · ${esc(v.state)}</small></div></div>`).join('')}</div></section><section class="aw-section"><div class="aw-note">Project-only is the safe default. Direct agent chats never retrieve another Project's memory. Verified reusable learning is recorded as evidence-backed observations and cannot silently rewrite historical versions.</div></section>`}
  function renderPerformance(){const rows=state.detail.observations||[],score=averageScore(state.detail);$('#detailBody').innerHTML=`<div class="aw-grid"><div class="aw-stat"><small>Evidence observations</small><strong>${rows.length}</strong></div><div class="aw-stat"><small>Mean recorded score</small><strong>${score==null?'—':score.toFixed(2)}</strong></div><div class="aw-stat"><small>Versions</small><strong>${(state.detail.versions||[]).length}</strong></div><div class="aw-stat"><small>Instances</small><strong>${(state.detail.instances||[]).length}</strong></div></div><section class="aw-section"><h3>Evidence-backed learning</h3>${rows.map(o=>`<div class="aw-observation"><strong>${esc(o.kind)} ${Number.isFinite(Number(o.score))?`<span class="aw-score">${esc(o.score)}</span>`:''}</strong><p>${esc(o.summary)}</p><span class="aw-meta">${esc(projectName(o.project_id))} · ${esc(fmtTime(o.created_at))}</span></div>`).join('')||'<div class="aw-muted">No learning observations recorded yet.</div>'}</section>`}
  function renderActivity(){const observations=state.detail.observations||[],instances=state.detail.instances||[];$('#detailBody').innerHTML=`<section class="aw-section"><h3>Current instance activity</h3><div class="aw-list">${instances.map(i=>`<div class="aw-row"><span class="aw-state ${esc(i.state)}">${esc(i.state)}</span><div class="aw-row-main"><strong>${esc(projectName(i.project_id))}</strong><small>${esc(short(i.id))} · version ${esc(short(i.version_id))}${i.current_work_order_id?` · Work ${esc(short(i.current_work_order_id))}`:''}</small></div></div>`).join('')||'<div class="aw-muted">No instance activity.</div>'}</div></section><section class="aw-section"><h3>Learning activity</h3>${observations.slice(0,30).map(o=>`<div class="aw-observation"><strong>${esc(o.kind)}</strong><p>${esc(o.summary)}</p><span class="aw-meta">${esc(fmtTime(o.created_at))}</span></div>`).join('')||'<div class="aw-muted">No observations yet.</div>'}</section>`}
  function renderSettings(){const d=state.detail;$('#detailBody').innerHTML=`<section class="aw-section"><h3>Identity</h3><div class="aw-row"><div class="aw-row-main"><strong>${esc(d.name)}</strong><small>${esc(d.slug)} · role ${esc(d.role)}</small></div><span>${d.system_owned?'System agent':'Custom agent'}</span></div></section><section class="aw-section"><h3>Safety boundary</h3><div class="aw-note">Agent configuration may shape reasoning, model routing and declared capabilities. It cannot modify owner authority, approval rules, Emergency Stop, audit integrity, tool policy, Evidence requirements or Completion Judge authority.</div></section>`}

  function openInstanceDialog(){
    const dialog=$('#instanceDialog'),form=$('#instanceForm'),versions=state.detail.versions||[];
    form.innerHTML=`<div class="aw-dialog-head"><div><h2>Create ${esc(state.detail.name)} Instance</h2><p>The instance is permanently scoped to the selected Project.</p></div><button value="cancel" class="aw-icon-btn">×</button></div><label>Project<select name="project_id" required>${state.projects.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select></label><label>Version<select name="version_id"><option value="">Preferred stable version</option>${versions.filter(v=>v.state!=='archived').map(v=>`<option value="${esc(v.id)}">${esc(v.version)} · ${esc(v.state)}</option>`).join('')}</select></label><div class="aw-two"><label>Provider override<input name="model_provider" placeholder="Auto" /></label><label>Model override<input name="model_id" placeholder="Auto" /></label></div><div class="aw-dialog-actions"><button value="cancel" class="aw-btn">Cancel</button><button type="submit" class="aw-btn primary">Create Instance</button></div>`;
    form.onsubmit=async event=>{event.preventDefault();const fd=new FormData(form);try{await api(`/${encodeURIComponent(state.detail.id)}/instances`,{method:'POST',body:JSON.stringify({project_id:fd.get('project_id'),version_id:fd.get('version_id')||null,model_provider:fd.get('model_provider')||null,model_id:fd.get('model_id')||null})});dialog.close();toast('Agent instance created');await selectAgent(state.detail.id)}catch(error){toast(error.message,true)}};
    dialog.showModal();
  }
  function openTeamDialog(){
    const dialog=$('#instanceDialog'),form=$('#instanceForm');
    form.innerHTML=`<div class="aw-dialog-head"><div><h2>Build Project Agent Team</h2><p>Vishnu always adds at least one Project Manager.</p></div><button value="cancel" class="aw-icon-btn">×</button></div><label>Project<select name="project_id" required>${state.projects.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select></label><div class="aw-two">${['coding','research','browser','data','qa','reviewer','security','design'].map((slug,index)=>`<label>${slug.replace('-',' ')}<input type="number" name="${slug}" min="0" max="100" value="${index<2?1:0}" /></label>`).join('')}</div><div class="aw-dialog-actions"><button value="cancel" class="aw-btn">Cancel</button><button type="submit" class="aw-btn primary">Create Team</button></div>`;
    form.onsubmit=async event=>{event.preventDefault();const fd=new FormData(form),requirements={};['coding','research','browser','data','qa','reviewer','security','design'].forEach(slug=>{const n=Number(fd.get(slug)||0);if(n>0)requirements[slug]=n});try{await api(`/projects/${encodeURIComponent(fd.get('project_id'))}/team`,{method:'POST',body:JSON.stringify({requirements})});dialog.close();toast('Project agent team created');await selectAgent(state.detail.id)}catch(error){toast(error.message,true)}};
    dialog.showModal();
  }
  function openVersionDialog(){
    const dialog=$('#versionDialog'),form=$('#versionForm'),versions=state.detail.versions||[],parent=preferred(state.detail)||versions[0];
    form.innerHTML=`<div class="aw-dialog-head"><div><h2>Create Agent Version</h2><p>New versions start as candidates and require qualification before promotion.</p></div><button value="cancel" class="aw-icon-btn">×</button></div><div class="aw-two"><label>Version<input name="version" required placeholder="1.1" /></label><label>Parent<select name="parent_version_id" required>${versions.map(v=>`<option value="${esc(v.id)}" ${v.id===parent?.id?'selected':''}>${esc(v.version)} · ${esc(v.state)}</option>`).join('')}</select></label></div><label>Instructions<textarea name="instructions" maxlength="32000">${esc(parent?.instructions||'')}</textarea></label><div class="aw-two"><label>Capabilities<input name="capabilities" value="${esc((parent?.capabilities||[]).join(', '))}" /></label><label>Tools<input name="tools" value="${esc((parent?.tools||[]).join(', '))}" /></label></div><div class="aw-dialog-actions"><button value="cancel" class="aw-btn">Cancel</button><button type="submit" class="aw-btn primary">Create Candidate</button></div>`;
    form.onsubmit=async event=>{event.preventDefault();const fd=new FormData(form),split=value=>String(value||'').split(',').map(x=>x.trim()).filter(Boolean);try{await api(`/${encodeURIComponent(state.detail.id)}/versions`,{method:'POST',body:JSON.stringify({version:fd.get('version'),parent_version_id:fd.get('parent_version_id'),instructions:fd.get('instructions')||'',capabilities:split(fd.get('capabilities')),tools:split(fd.get('tools')),model_policy:{routing:'auto',authority:false}})});dialog.close();toast('Candidate version created');await selectAgent(state.detail.id)}catch(error){toast(error.message,true)}};
    dialog.showModal();
  }
  function bindCreateAgent(){
    const dialog=$('#createAgentDialog'),form=$('#createAgentForm');$('#createAgentButton')?.addEventListener('click',()=>dialog.showModal());
    form?.addEventListener('submit',async event=>{event.preventDefault();const fd=new FormData(form),split=value=>String(value||'').split(',').map(x=>x.trim()).filter(Boolean);try{const data=await api('',{method:'POST',body:JSON.stringify({name:fd.get('name'),role:fd.get('role'),description:fd.get('description')||'',instructions:fd.get('instructions')||'',capabilities:split(fd.get('capabilities')),tools:split(fd.get('tools')),model_policy:{routing:'auto',authority:false}})});dialog.close();form.reset();toast('Custom agent candidate created');await loadCatalog();if(data?.template?.id)await selectAgent(data.template.id)}catch(error){toast(error.message,true)}});
  }
  async function loadCatalog(){const [summary,catalog]=await Promise.all([api('/summary'),api('')]);state.agents=catalog.agents||[];renderKpis(summary);renderAgentList()}
  async function loadProjects(){try{const data=await projectApi('');state.projects=data.projects||[]}catch{state.projects=[]}}
  async function initialLoad(){
    state.loading=true;$('#agentList').innerHTML='<div class="aw-loading">Loading workforce…</div>';
    try{await Promise.all([loadProjects(),loadCatalog()]);const first=filteredAgents()[0];if(first)await selectAgent(first.id);else renderDetail()}catch(error){$('#healthCopy').textContent='Workforce unavailable';$('#agentList').innerHTML=`<div class="aw-error">${esc(error.message)}</div>`;$('#agentDetail').innerHTML=empty('Workforce unavailable',error.message);toast(error.message,true)}finally{state.loading=false}
  }
  function bindChrome(){
    $('#menuButton')?.addEventListener('click',()=>document.body.classList.toggle('sidebar-open'));
    $('.aw-sidebar')?.addEventListener('click',event=>{if(event.target.closest('a')&&matchMedia('(max-width:820px)').matches)document.body.classList.remove('sidebar-open')});
    $('[data-action="new-project"]')?.addEventListener('click',()=>location.href='/iphone/#projects');
    ['agentSearch','globalSearch','statusFilter','sortFilter'].forEach(id=>$('#'+id)?.addEventListener(id.includes('Filter')?'change':'input',renderAgentList));
    $$('#catalogTabs [data-filter]').forEach(btn=>btn.addEventListener('click',()=>{$$('#catalogTabs [data-filter]').forEach(x=>x.classList.remove('active'));btn.classList.add('active');state.catalog=btn.dataset.filter;renderAgentList()}));
    window.addEventListener('keydown',event=>{if(event.key==='Escape')document.body.classList.remove('sidebar-open')});
  }
  document.addEventListener('DOMContentLoaded',()=>{bindChrome();bindCreateAgent();initialLoad()});
})();
