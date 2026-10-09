/* Sequential loader for Home/Chat plus canonical Projects Work surfaces. */
(()=>{
  const loadChatContextOwner=()=>{
    if(window.__vishnuChatContextOwner||document.querySelector('script[data-chat-context-owner]'))return;
    const context=document.createElement('script');
    context.src='/iphone/chat-context-owner.js';
    context.async=false;
    context.dataset.chatContextOwner='true';
    context.onerror=()=>console.warn('Chat project-context controller could not be loaded.');
    document.body.append(context);
  };
  const loadAttentionCenter=()=>{
    if(window.__vishnuWorkAttentionCenter){loadChatContextOwner();return}
    const existing=document.querySelector('script[data-work-attention-center]');
    if(existing){existing.addEventListener('load',loadChatContextOwner,{once:true});existing.addEventListener('error',loadChatContextOwner,{once:true});return}
    const attention=document.createElement('script');
    attention.src='/iphone/work-attention-center.js';
    attention.async=false;
    attention.dataset.workAttentionCenter='true';
    attention.onload=loadChatContextOwner;
    attention.onerror=()=>{console.warn('Work Attention Center could not be loaded.');loadChatContextOwner()};
    document.body.append(attention);
  };
  const loadGlobalAwareness=()=>{
    const loadGlobal=()=>{
      let global=document.querySelector('script[data-global-work-awareness]');
      if(window.__vishnuGlobalWorkAwareness){loadAttentionCenter();return}
      if(global){global.addEventListener('load',loadAttentionCenter,{once:true});return}
      global=document.createElement('script');
      global.src='/iphone/global-work-awareness.js';
      global.async=false;
      global.dataset.globalWorkAwareness='true';
      global.onload=loadAttentionCenter;
      global.onerror=()=>console.warn('Global canonical Work awareness could not be loaded.');
      document.body.append(global);
    };
    let detail=document.querySelector('script[data-workorder-detail]');
    if(window.__vishnuWorkOrderDetail){loadGlobal();return}
    if(detail){detail.addEventListener('load',loadGlobal,{once:true});return}
    detail=document.createElement('script');
    detail.src='/iphone/workorder-detail.js';
    detail.async=false;
    detail.dataset.workorderDetail='true';
    detail.onload=loadGlobal;
    detail.onerror=()=>console.warn('WorkOrder detail surface could not be loaded.');
    document.body.append(detail);
  };
  const loadVisualizations=()=>{
    let visual=document.querySelector('script[data-canonical-project-visualizations]');
    if(window.__vishnuCanonicalProjectVisualizations){loadGlobalAwareness();return}
    if(visual){visual.addEventListener('load',loadGlobalAwareness,{once:true});return}
    visual=document.createElement('script');
    visual.src='/iphone/projects-work-visualization-runtime.js';
    visual.async=false;
    visual.dataset.canonicalProjectVisualizations='true';
    visual.onload=loadGlobalAwareness;
    visual.onerror=()=>console.warn('Canonical Projects visualizations could not be loaded.');
    document.body.append(visual);
  };
  const loadProjectAutonomy=()=>{
    let controls=document.querySelector('script[data-project-autonomy-controls]');
    if(window.__vishnuProjectAutonomyUI){loadVisualizations();return}
    if(controls){controls.addEventListener('load',loadVisualizations,{once:true});return}
    controls=document.createElement('script');
    controls.src='/iphone/project-autonomy-controls.js';
    controls.async=false;
    controls.dataset.projectAutonomyControls='true';
    controls.onload=loadVisualizations;
    controls.onerror=()=>console.warn('Project autonomy controls could not be loaded.');
    document.body.append(controls);
  };
  const ensureCanonicalWork=()=>{
    let script=document.querySelector('script[data-canonical-project-work]');
    if(window.__vishnuCanonicalProjectWork){loadProjectAutonomy();return}
    if(script){script.addEventListener('load',loadProjectAutonomy,{once:true});return}
    script=document.createElement('script');
    script.src='/iphone/projects-work-runtime.js';
    script.async=false;
    script.dataset.canonicalProjectWork='true';
    script.onload=loadProjectAutonomy;
    script.onerror=()=>console.warn('Canonical Projects Work UI could not be loaded.');
    document.body.append(script);
  };
  const existingCore=document.querySelector('script[data-home-chat-core]');
  if(existingCore){
    if(window.__vishnuHomeChatCoreLoaded)ensureCanonicalWork();
    else existingCore.addEventListener('load',ensureCanonicalWork,{once:true});
    return;
  }
  const core=document.createElement('script');
  core.src='/iphone/home-chat-redesign-core.js';
  core.async=false;
  core.dataset.homeChatCore='true';
  core.onload=()=>{window.__vishnuHomeChatCoreLoaded=true;ensureCanonicalWork()};
  core.onerror=()=>console.warn('Home and Chat enhancements could not be loaded.');
  document.body.append(core);
})();