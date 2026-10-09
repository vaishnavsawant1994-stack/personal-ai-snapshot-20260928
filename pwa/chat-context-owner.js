/* Final owner for Chat project-context controls. Loaded after the Home/core adapters so
   older Home wiring cannot replace the current conversation-context behavior. */
(()=>{
  if(window.__vishnuChatContextOwner)return;
  window.__vishnuChatContextOwner=true;
  const $=id=>document.getElementById(id);
  const bridge=()=>window.vishnuChatBridge;
  let selectedProjectId='';

  // Chat Details remains reachable through the canonical three-dot conversation menu.
  // The responsive Chat stylesheet introduced a second top-details button and hid the
  // canonical menu; override that presentation-only rule after all Chat CSS is loaded.
  // Empty Chat is its own state, not Home landing, so restore its intro container without
  // reviving Home quick actions.
  const menuStyle=document.createElement('style');
  menuStyle.dataset.chatCanonicalMenu='true';
  menuStyle.textContent='body.chat-experience .topbar-actions .chat-menu-button:not(.hidden){display:grid!important}body.chat-experience .chat-top-details{display:none!important}body.chat-experience.chat-new-empty .home-intro{display:flex!important}body.chat-experience.chat-new-empty .v-shortcuts{display:none!important}';
  document.head.append(menuStyle);

  function setLabel(name=''){
    const label=name?'Project · '+name:'General chat · No project context';
    const chip=$('vContextChip');
    if(chip){
      const span=chip.querySelector('span');
      if(span)span.textContent=label;
      chip.setAttribute('aria-label','Conversation context: '+label+'. Choose context');
    }
    const scope=$('vScopeButton');
    if(scope){
      const strong=scope.querySelector('strong'),small=scope.querySelector('span');
      if(strong)strong.textContent=name?'Project · '+name:'Vishnu · System-wide';
      if(small)small.textContent=name?'Project-scoped conversation':'Ask anything · Updates · Give Vishnu work';
      scope.setAttribute('aria-label',name?'Project-scoped chat for '+name+'. Choose context':'Vishnu system-wide chat. Choose a project context');
    }
  }

  async function projects(){
    const b=bridge();
    if(!b)throw new Error('Conversation controls are unavailable.');
    const data=await b.api('/projects?status=active');
    return Array.isArray(data.projects)?data.projects:[];
  }

  async function chooseContext(){
    const b=bridge();
    if(!b||typeof window.projectDialog!=='function')throw new Error('Project context selection is unavailable.');
    const rows=await projects();
    if(!rows.length){b.showToast('No active projects are available. Create a project first.');return}
    const current=b.current,draft=b.getDraft();
    const inferred=rows.find(project=>project.conversation_id===current?.id);
    if(inferred)selectedProjectId=inferred.id;
    const choice=await window.projectDialog('Choose conversation context',[
      {name:'project_id',label:'Conversation context',type:'select',required:false,value:selectedProjectId,options:[['','General chat · No project context'],...rows.map(project=>[project.id,project.name||'Untitled project'])]},
      {name:'note',label:'',type:'note',value:'Project conversations use the selected project’s own conversation and remain scoped to that project.'}
    ]);
    if(!choice)return;
    if(!choice.project_id){
      if(selectedProjectId||inferred){
        if(draft.trim()){
          const input=$('message');if(input)input.value='';
          await b.createConversation();
          b.setDraft(draft);
        }else await b.createConversation();
      }
      selectedProjectId='';
      setLabel('');
      return;
    }
    const project=rows.find(row=>row.id===choice.project_id);
    if(!project)throw new Error('That project is no longer available.');
    let conversationId=project.conversation_id;
    if(!conversationId){
      const result=await b.api('/projects/'+encodeURIComponent(project.id)+'/conversation',{method:'POST',body:'{}'});
      conversationId=result?.conversation_id;
    }
    if(!conversationId)throw new Error('The project conversation could not be opened.');
    await b.openConversation(conversationId);
    if(draft)b.setDraft(draft);
    selectedProjectId=project.id;
    setLabel(project.name||'Project');
  }

  function intercept(event){
    const target=event.target?.closest?.('#vContextChip,#vScopeButton');
    if(!target)return;
    event.preventDefault();
    event.stopImmediatePropagation();
    chooseContext().catch(error=>bridge()?.showToast(error?.message||'Could not change conversation context.'));
  }

  document.addEventListener('click',intercept,true);
  window.addEventListener('vishnu:new-chat',()=>{
    selectedProjectId='';
    document.body.classList.remove('home-landing');
    document.body.classList.add('chat-new-empty');
    setLabel('');
  });
  // Synchronize an already-active project conversation without blocking first paint.
  queueMicrotask(async()=>{
    try{
      const b=bridge(),current=b?.current;if(!b||!current?.id)return;
      const rows=await projects(),project=rows.find(row=>row.conversation_id===current.id);
      selectedProjectId=project?.id||'';setLabel(project?.name||'');
    }catch{}
  });
})();
