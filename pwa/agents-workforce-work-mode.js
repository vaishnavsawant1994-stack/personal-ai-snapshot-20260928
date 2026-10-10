(()=>{
  'use strict';
  if(window.__vishnuAgentWorkMode)return;
  window.__vishnuAgentWorkMode=true;

  const esc=value=>String(value??'').replace(/[&<>'"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const toast=(message,error=false)=>{const el=document.querySelector('#toast');if(!el)return;el.textContent=message;el.className='aw-toast show'+(error?' error':'');setTimeout(()=>{if(el.textContent===message)el.className='aw-toast'},3200)};
  async function json(response){
    if(response.ok)return response.json();
    let message=`Request failed (${response.status})`;
    try{const body=await response.json();message=typeof body.detail==='string'?body.detail:(body.detail?.message||body.message||message)}catch{}
    throw new Error(message);
  }
  function selectedAgent(){return document.querySelector('.aw-agent-card.active[data-agent-id]')?.dataset.agentId||null}
  function selectedProject(){return document.querySelector('#chatProjectSelect')?.value||null}
  function selectedConversation(){return document.querySelector('.aw-chat-thread.active[data-chat-id]')?.dataset.chatId||null}
  async function ensureConversation(agentId,projectId){
    const current=selectedConversation();if(current)return current;
    const response=await fetch(`/iphone/api/agents/${encodeURIComponent(agentId)}/conversations`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify({project_id:projectId,title:'Direct work request'})});
    const data=await json(response);return data.conversation.id;
  }
  function appendMessage(role,content,meta=''){
    const root=document.querySelector('#chatMessages');if(!root)return;
    const empty=root.querySelector('.aw-chat-empty');if(empty)empty.remove();
    root.insertAdjacentHTML('beforeend',`<div class="aw-message ${role==='user'?'user':'assistant'}"><div class="bubble">${esc(content)}</div><small>${esc(meta)}</small></div>`);root.scrollTop=root.scrollHeight;
  }
  async function createWork(button){
    const input=document.querySelector('#agentChatInput');
    const prompt=String(input?.value||'').trim();
    const agentId=selectedAgent(),projectId=selectedProject();
    if(!prompt){input?.focus();toast('Describe the work you want this agent to do.',true);return}
    if(!agentId||!projectId){toast('Select an agent and Project first.',true);return}
    button.disabled=true;if(input)input.disabled=true;
    try{
      const conversationId=await ensureConversation(agentId,projectId);
      appendMessage('user',prompt,'creating canonical Work…');
      if(input)input.value='';
      const response=await fetch(`/iphone/api/agents/${encodeURIComponent(agentId)}/work-requests`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify({project_id:projectId,prompt,conversation_id:conversationId})});
      const data=await json(response);
      appendMessage('assistant',data.message||'Canonical Work created.','Vishnu Work Orchestrator');
      toast('Canonical Project Work created');
    }catch(error){toast(error.message||String(error),true)}finally{button.disabled=false;if(input){input.disabled=false;input.focus()}}
  }
  function enhanceChat(){
    const form=document.querySelector('#agentChatForm');
    if(!form||form.querySelector('[data-create-work]'))return;
    const send=form.querySelector('button[type="submit"]');if(!send)return;
    const button=document.createElement('button');button.type='button';button.className='aw-btn';button.dataset.createWork='true';button.textContent='Create Work';button.title='Create governed canonical Project Work from this specialist request';button.addEventListener('click',()=>createWork(button));send.insertAdjacentElement('beforebegin',button);
    const controls=document.querySelector('.aw-chat-controls');if(controls&&!controls.querySelector('[data-work-mode-note]')){const note=document.createElement('span');note.dataset.workModeNote='true';note.className='aw-meta';note.textContent='Chat = advice · Create Work = governed execution plan';controls.append(note)}
  }

  function orchestratorVisible(){
    const filter=document.querySelector('#catalogTabs button.active')?.dataset.filter||'all';
    const q=String(document.querySelector('#agentSearch')?.value||document.querySelector('#globalSearch')?.value||'').trim().toLowerCase();
    const type=document.querySelector('#typeFilter')?.value||'all';
    const version=document.querySelector('#versionFilter')?.value||'all';
    return ['all','system','active'].includes(filter)&&['all','project_manager'].includes(type)&&['all','preferred'].includes(version)&&(!q||'vishnu main ai orchestrator orchestration planning management'.includes(q));
  }
  function ensureVishnuCard(){
    const list=document.querySelector('#agentList');if(!list)return;
    const apiVishnu=[...list.querySelectorAll('.aw-agent-card')].find(card=>/^vishnu\b/i.test(card.querySelector('.aw-agent-copy strong')?.textContent||''));
    let card=list.querySelector('[data-global-vishnu]');
    if(apiVishnu){card?.remove();return}
    if(!orchestratorVisible()){card?.remove();return}
    const projects=document.querySelector('[data-kpi="projects_using_agents"]')?.textContent||'—';
    const workers=document.querySelector('[data-kpi="active_instances"]')?.textContent||'—';
    const success=document.querySelector('[data-kpi="success_rate"]')?.textContent||'—';
    if(!card){
      card=document.createElement('article');card.className='aw-agent-card';card.dataset.globalVishnu='true';card.dataset.agentId='vishnu-global';card.dataset.role='vishnu';card.tabIndex=0;
      card.innerHTML=`<span class="aw-agent-icon">V</span><span class="aw-agent-copy"><strong>Vishnu <span class="aw-badge preferred">Core</span></strong><small>Main AI · Global Orchestrator</small></span><span class="aw-agent-status">Online</span><div class="aw-agent-metrics"><span><small>Projects</small><b data-vishnu-projects>—</b></span><span><small>Workers</small><b data-vishnu-workers>—</b></span><span><small>Success</small><b data-vishnu-success>—</b></span></div><button class="aw-agent-chat" type="button">◯ Chat</button>`;
      const open=()=>{window.location.href='/iphone/#conversations'};card.addEventListener('click',open);card.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open()}});list.prepend(card);
    }
    card.querySelector('[data-vishnu-projects]').textContent=projects;card.querySelector('[data-vishnu-workers]').textContent=workers;card.querySelector('[data-vishnu-success]').textContent=success;
  }
  const rankCard=card=>{
    if(card.dataset.globalVishnu==='true'||/^vishnu\b/i.test(card.querySelector('.aw-agent-copy strong')?.textContent||''))return 0;
    const name=(card.querySelector('.aw-agent-copy strong')?.textContent||'').toLowerCase(),role=card.dataset.role||'';
    if(name.startsWith('project manager'))return 1;
    return {coding:2,research:3,browser:4,data:5,qa:6,security:7,design:8,reviewer:9,files:10,communications:11,knowledge:12}[role]??20;
  };
  function orderReferenceCards(){
    const list=document.querySelector('#agentList');if(!list||document.querySelector('#sortFilter')?.value!=='usage')return;
    const cards=[...list.querySelectorAll(':scope > .aw-agent-card')];if(cards.length<2)return;
    const sorted=[...cards].sort((a,b)=>rankCard(a)-rankCard(b));
    if(cards.every((card,index)=>card===sorted[index]))return;
    const fragment=document.createDocumentFragment();sorted.forEach(card=>fragment.append(card));list.append(fragment);
  }

  let landingRestored=false;
  function stabilizeReferenceLayout(){
    const list=document.querySelector('#agentList');
    if(list){const compact=window.matchMedia('(min-width:1281px)').matches;list.style.maxHeight=compact?'240px':'';list.style.overflowY=compact?'auto':'';list.style.scrollbarWidth=compact?'none':'';}
    if(!landingRestored&&document.querySelector('#agentDetail .aw-detail-head')){landingRestored=true;requestAnimationFrame(()=>window.scrollTo({top:0,left:0,behavior:'auto'}));}
  }

  function enhance(){enhanceChat();ensureVishnuCard();orderReferenceCards();stabilizeReferenceLayout()}
  let pending=false;const schedule=()=>{if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;enhance()})};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',schedule,{once:true});else schedule();
  new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});
  window.addEventListener('resize',schedule,{passive:true});
  document.addEventListener('input',event=>{if(event.target?.matches?.('#agentSearch,#globalSearch'))schedule()});
  document.addEventListener('change',event=>{if(event.target?.matches?.('#typeFilter,#versionFilter,#sortFilter,#statusFilter'))schedule()});
})();
