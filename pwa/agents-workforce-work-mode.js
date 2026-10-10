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
  function enhance(){
    const form=document.querySelector('#agentChatForm');
    if(!form||form.querySelector('[data-create-work]'))return;
    const send=form.querySelector('button[type="submit"]');if(!send)return;
    const button=document.createElement('button');button.type='button';button.className='aw-btn';button.dataset.createWork='true';button.textContent='Create Work';button.title='Create governed canonical Project Work from this specialist request';button.addEventListener('click',()=>createWork(button));send.insertAdjacentElement('beforebegin',button);
    const controls=document.querySelector('.aw-chat-controls');if(controls&&!controls.querySelector('[data-work-mode-note]')){const note=document.createElement('span');note.dataset.workModeNote='true';note.className='aw-meta';note.textContent='Chat = advice · Create Work = governed execution plan';controls.append(note)}
  }
  let pending=false;const schedule=()=>{if(pending)return;pending=true;requestAnimationFrame(()=>{pending=false;enhance()})};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',schedule,{once:true});else schedule();
  new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true});
})();
