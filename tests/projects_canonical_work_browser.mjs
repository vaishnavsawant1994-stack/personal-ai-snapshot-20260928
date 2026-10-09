import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const root = new URL('../', import.meta.url);
const runtime = await readFile(new URL('pwa/projects-work-runtime.js', root), 'utf8');

const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#07101c;color:#eef5ff;font:14px system-ui}.project-btn{border:1px solid #35506f;background:#101f33;color:#eef5ff;border-radius:10px;padding:8px 10px}.project-btn.primary{background:#2563a8}.project-btn:disabled{opacity:.5}#host{max-width:1180px;margin:auto;padding:16px;box-sizing:border-box}</style></head><body><main id="host"></main><script>
window.prEsc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
window.projectCurrent={id:'project-1',name:'Canonical Project',goal:'Ship a verified launch'};
window.projectTab='plan';
window.__calls=[];window.__toasts=[];
window.__snapshot={project_id:'project-1',available:true,authority:'existing_p10_p6_runtime',state:'planned',goal:{id:'goal-1',objective:'Ship a verified launch'},p10_plan:{id:'plan-1',state:'READY',replan_count:1,tasks:[{id:'research',status:'WAITING'},{id:'publish',status:'WAITING_APPROVAL'}]},work_plan:{id:'plan-1:v2',goal_id:'goal-1',version:2,summary:'Research, review and publish the verified launch.',readiness:'ready',status:'ready',milestones:[{id:'m1',title:'Launch evidence',objective:'Establish verified launch inputs',success_criteria:['Inputs are verified'],work_order_ids:['plan-1:v2:research','plan-1:v2:publish']}],work_orders:[{id:'plan-1:v2:research',plan_id:'plan-1:v2',title:'Research inputs',objective:'Collect verified launch evidence',worker_type:'research',status:'queued',priority:80,dependencies:[],expected_output:'Verified research brief',success_criteria:['Sources verified'],resource_scope:{metadata:{p10_task_id:'research',requested_tool:'web_search_browser'}},evidence_contract:{requirements:[{kind:'tool_execution_verification',min_provenance:'tool_verified'}]}},{id:'plan-1:v2:publish',plan_id:'plan-1:v2',title:'Publish launch',objective:'Publish the approved launch',worker_type:'communications',status:'waiting_approval',priority:70,dependencies:['plan-1:v2:research'],expected_output:'Published launch',success_criteria:['Publication confirmed'],resource_scope:{metadata:{p10_task_id:'publish',requested_tool:'publish_content'}},evidence_contract:{requirements:[{kind:'tool_execution_verification',min_provenance:'tool_verified'}]}}],latest_review:{status:'ready',score:100,blockers:[],warnings:[]},latest_delta:{reason:'New evidence required publication review',items:[{action:'modify',task_id:'publish'}]}},live_work:{state:'READY',task_counts:{WAITING:1,WAITING_APPROVAL:1},ready_task_ids:['research'],active_task_ids:[],waiting_approval_task_ids:['publish'],blocked_task_ids:[],replan_count:1},evidence:{total:1,by_task:{research:[{verification_state:'verified',provenance:'tool_verified',observation:'Research result was verified by the governed tool path.',tool_name:'web_search_browser'}],publish:[]}}};
window.__history={plans:[{source_p10_plan_id:'plan-1',versions:[{version:1,status:'ready',summary:'Initial plan'},{version:2,status:'ready',summary:'Research, review and publish the verified launch.'}],deltas:[{reason:'New evidence required publication review',items:[{action:'modify',task_id:'publish'}]}]}]};
window.api=async(path,options={})=>{window.__calls.push({path,method:options.method||'GET'});if(path.endsWith('/work/history'))return structuredClone(window.__history);if(path.endsWith('/work/plan'))return {created:true};if(path.includes('/tasks/research/execute')){window.__snapshot.p10_plan.state='RUNNING';window.__snapshot.p10_plan.tasks[0].status='RUNNING';window.__snapshot.live_work.state='RUNNING';window.__snapshot.live_work.ready_task_ids=[];window.__snapshot.live_work.active_task_ids=['research'];window.__snapshot.live_work.task_counts={RUNNING:1,WAITING_APPROVAL:1};return structuredClone(window.__snapshot)}if(path.endsWith('/pause')){window.__snapshot.p10_plan.state='PAUSED';window.__snapshot.live_work.state='PAUSED';return structuredClone(window.__snapshot)}if(path.endsWith('/resume')){window.__snapshot.p10_plan.state='READY';window.__snapshot.live_work.state='READY';return structuredClone(window.__snapshot)}if(path.endsWith('/cancel')){window.__snapshot.p10_plan.state='CANCELLED';window.__snapshot.live_work.state='CANCELLED';return structuredClone(window.__snapshot)}if(path.endsWith('/work'))return structuredClone(window.__snapshot);throw new Error('Unhandled API '+path)};
window.showToast=message=>window.__toasts.push(String(message));window.sendProjectMessage=async()=>{};window.confirm=()=>true;
window.renderProjectPlan=(host,p)=>{host.textContent='legacy plan'};window.renderProjectLive=(host,p)=>{host.textContent='legacy live'};
window.renderProjectTab=()=>window.projectTab==='live'?window.renderProjectLive(document.querySelector('#host'),window.projectCurrent):window.renderProjectPlan(document.querySelector('#host'),window.projectCurrent);
window.renderProjectDetail=window.renderProjectTab;
</script><script src="/projects-work-runtime.js"></script></body></html>`;

const server = createServer((req,res)=>{
  if(req.url==='/projects-work-runtime.js'){res.writeHead(200,{'content-type':'application/javascript','cache-control':'no-store'});return res.end(runtime)}
  res.writeHead(200,{'content-type':'text/html; charset=utf-8','cache-control':'no-store'});res.end(html);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const address=server.address();
const browser=await chromium.launch({headless:true});
try{
  for(const viewport of [{width:390,height:844,isMobile:true},{width:1440,height:1000,isMobile:false}]){
    const page=await browser.newPage({viewport,deviceScaleFactor:viewport.isMobile?2:1,isMobile:viewport.isMobile,hasTouch:viewport.isMobile});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(`http://127.0.0.1:${address.port}/`,{waitUntil:'networkidle'});
    await page.waitForFunction(()=>window.__vishnuCanonicalProjectWork?.installed===true);

    await page.evaluate(()=>window.renderProjectPlan(document.querySelector('#host'),window.projectCurrent));
    await page.locator('.cw-page').waitFor();
    assert.match(await page.locator('#host').innerText(),/Work plan/i);
    assert.match(await page.locator('#host').innerText(),/WorkOrders · 2/i);
    assert.match(await page.locator('#host').innerText(),/Readiness · Ready/i);
    assert.match(await page.locator('#host').innerText(),/Plan v2/i);
    const evidenceDetails=page.locator('.cw-order details').first();
    assert.equal(await evidenceDetails.count(),1);
    await evidenceDetails.evaluate(node=>{node.open=true});
    assert.match(await evidenceDetails.innerText(),/Research result was verified/i);
    assert.equal(await page.locator('[data-cw-execute="research"]').count(),1);

    await page.locator('[data-cw-execute="research"]').click();
    await page.waitForFunction(()=>window.__snapshot.p10_plan.tasks[0].status==='RUNNING');
    await page.waitForTimeout(30);
    assert.match(await page.locator('#host').innerText(),/Running through existing executor/i);
    assert.equal(await page.evaluate(()=>window.__calls.some(call=>call.path.includes('/tasks/research/execute'))),true);

    await page.evaluate(()=>{window.projectTab='live';window.renderProjectLive(document.querySelector('#host'),window.projectCurrent)});
    await page.locator('.cw-live-list').waitFor();
    const liveText=await page.locator('#host').innerText();
    assert.match(liveText,/Live work/i);
    assert.match(liveText,/Waiting Approval/i);
    assert.match(liveText,/Actual P10 WorkOrder state/i);
    assert.match(liveText,/Evidence · 1/i);
    assert.equal(await page.locator('[data-cw-live-select="publish"]').count(),1);

    await page.locator('[data-cw-live-select="publish"]').click();
    assert.match(await page.locator('#host').innerText(),/Approval is not granted from this view/i);

    if(viewport.isMobile){
      const geometry=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth,columns:getComputedStyle(document.querySelector('.cw-layout')).gridTemplateColumns}));
      assert.ok(geometry.scroll<=geometry.viewport+2,`mobile canonical work UI overflows: ${JSON.stringify(geometry)}`);
      assert.ok(!geometry.columns.includes(' '),`mobile layout should collapse to one column: ${geometry.columns}`);
    }
    assert.deepEqual(errors,[],`canonical Work UI page errors at ${viewport.width}px: ${errors.join(' | ')}`);
    await page.close();
  }
} finally {
  await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
console.log('Canonical Projects Work browser qualification passed.');
