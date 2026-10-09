/* Sequential loader for Home/Chat plus canonical Projects Work surfaces. */
(()=>{
  const loadGlobalAwareness=()=>{
    if(document.querySelector('script[data-global-work-awareness]'))return;
    const global=document.createElement('script');
    global.src='/iphone/global-work-awareness.js';
    global.async=false;
    global.dataset.globalWorkAwareness='true';
    global.onerror=()=>console.warn('Global canonical Work awareness could not be loaded.');
    document.body.append(global);
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
  const ensureCanonicalWork=()=>{
    let script=document.querySelector('script[data-canonical-project-work]');
    if(window.__vishnuCanonicalProjectWork){loadVisualizations();return}
    if(script){script.addEventListener('load',loadVisualizations,{once:true});return}
    script=document.createElement('script');
    script.src='/iphone/projects-work-runtime.js';
    script.async=false;
    script.dataset.canonicalProjectWork='true';
    script.onload=loadVisualizations;
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
