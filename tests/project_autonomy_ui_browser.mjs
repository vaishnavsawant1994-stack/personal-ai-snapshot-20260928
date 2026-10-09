import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require=createRequire(import.meta.url);const {chromium}=require('playwright');
const root=new URL('../',import.meta.url);const controls=await readFile(new URL('pwa/project-autonomy-controls.js',root),'utf8');
const html=`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#07101c;color:#eef5ff;font:14px system-ui}.project-btn{border:1px solid #35506f;background:#101f33;color:#eef5ff;border-radius:10px;padding:8px 10px}.project-btn.primary{background:#2563a8}#host{max-width:1180px;margin:auto;padding:16px;box-sizing:border-box}.cw-page{display:grid;gap:14px}.cw-head{display:flex;justify-content:space-between}</style></head><body><main id="host"></main><script>
window.prEsc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
window.projectCurrent={id:'project-1',name:'Launch Project'};window.projectTab='plan';window.__calls=[];window.__toasts=[];window.__mode={mode:'assisted',semantics:{automatic_execution:false},execution_authority:'existing_p10_p6_runtime'};
window.__vishnuCanonicalProjectWork={installed:true,snapshotCache:new Map([['project-1',{p10_plan:{id:'plan-1'}}]])};
window.api=async(path,options={})=>{const method=options.method||'GET';window.__calls.push({path,method,body:options.body||null});if(path.endsWith('/work/autonomy')&&method==='GET')return structuredClone(window.__mode);if(path.endsWith('/work/autonomy')&&method==='PUT'){window.__mode={mode:JSON.parse(options.body).mode,semantics:{automatic_execution:JSON.parse(options.body).mode==='active'},execution_authority:'existing_p10_p6_runtime'};return structuredClone(window.__mode)}if(path.endsWith('/work/plan-1/advance')&&method==='POST')return {project_id:'project-1',plan_id:'plan-1',mode:'active',executed_task_ids:[],stop_reason:'task_state:waiting_approval',execution_authority:'existing_p10_p6_runtime'};throw new Error('Unhandled API '+method+' '+path)};
window.showToast=message=>window.__toasts.push(String(message));window.refreshCanonicalProjectWork=async()=>{};
window.renderProjectPlan=(host,p)=>{host.innerHTML='<div class="cw-page"><header class="cw-head"><div><h2>Work plan</h2><p>'+p.name+'</p></div></header><section>Canonical work</section></div>'};
window.renderProjectLive=(host,p)=>{host.innerHTML='<div class="cw-page"><header class="cw-head"><div><h2>Live work</h2><p>'+p.name+'</p></div></header><section>Live canonical work</section></div>'};
window.renderProjectTab=()=>{};
</script><script src="/project-autonomy-controls.js"></script></body></html>`;
const server=createServer((req,res)=>{if(req.url==='/project-autonomy-controls.js'){res.writeHead(200,{'content-type':'application/javascript','cache-control':'no-store'});return res.end(controls)}res.writeHead(200,{'content-type':'text/html; charset=utf-8','cache-control':'no-store'});res.end(html)});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const address=server.address();const browser=await chromium.launch({headless:true});
try{
  for(const viewport of [{width:390,height:844,isMobile:true},{width:1440,height:1000,isMobile:false}]){
    const page=await browser.newPage({viewport,deviceScaleFactor:viewport.isMobile?2:1,isMobile:viewport.isMobile,hasTouch:viewport.isMobile});const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`http://127.0.0.1:${address.port}/`,{waitUntil:'networkidle'});await page.waitForFunction(()=>window.__vishnuProjectAutonomyUI?.installed===true);
    await page.evaluate(()=>window.renderProjectPlan(document.querySelector('#host'),window.projectCurrent));await page.locator('[data-project-autonomy-controls]').waitFor();
    let text=await page.locator('[data-project-autonomy-controls]').innerText();assert.match(text,/Project autonomy · Assisted/i);assert.match(text,/Automatic advancement disabled/i);assert.equal(await page.locator('[data-pa-advance]').count(),0);
    await page.locator('[data-pa-mode="active"]').click();await page.waitForFunction(()=>window.__mode.mode==='active');await page.locator('[data-pa-advance]').waitFor();text=await page.locator('[data-project-autonomy-controls]').innerText();assert.match(text,/Project autonomy · Active/i);assert.match(text,/Automatic advancement enabled/i);
    await page.locator('[data-pa-advance]').click();await page.waitForFunction(()=>window.__calls.some(call=>call.path.endsWith('/work/plan-1/advance')));await page.waitForTimeout(20);text=await page.locator('[data-project-autonomy-controls]').innerText();assert.match(text,/Vishnu stopped safely/i);assert.match(text,/Approval is required/i);
    await page.locator('[data-pa-mode="shadow"]').click();await page.waitForFunction(()=>window.__mode.mode==='shadow');text=await page.locator('[data-project-autonomy-controls]').innerText();assert.match(text,/Project autonomy · Shadow/i);assert.match(text,/execution is disabled/i);assert.equal(await page.locator('[data-pa-advance]').count(),0);
    const mutations=await page.evaluate(()=>window.__calls.filter(call=>call.method!=='GET').map(call=>({path:call.path,method:call.method})));
    assert.deepEqual(mutations,[{path:'/projects/project-1/work/autonomy',method:'PUT'},{path:'/projects/project-1/work/plan-1/advance',method:'POST'},{path:'/projects/project-1/work/autonomy',method:'PUT'}]);
    if(viewport.isMobile){const geometry=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth,columns:getComputedStyle(document.querySelector('.pa-mode-options')).gridTemplateColumns}));assert.ok(geometry.scroll<=geometry.viewport+2,`autonomy UI overflows mobile: ${JSON.stringify(geometry)}`);assert.ok(!geometry.columns.includes(' '),`mobile mode controls should be one column: ${geometry.columns}`)}
    assert.deepEqual(errors,[],`Project autonomy UI page errors at ${viewport.width}px: ${errors.join(' | ')}`);await page.close();
  }
}finally{await browser.close();await new Promise(resolve=>server.close(resolve))}
console.log('Project autonomy controls Chromium qualification passed.');