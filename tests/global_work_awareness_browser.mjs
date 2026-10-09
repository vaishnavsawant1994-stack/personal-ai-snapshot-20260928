import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require=createRequire(import.meta.url);
const { chromium }=require('playwright');
const root=new URL('../',import.meta.url);
const runtime=await readFile(new URL('pwa/global-work-awareness.js',root),'utf8');
const requests=[];

const summary={
  authority:'read_only_projection',execution_authority:'existing_p10_p6_runtime',updated_at:'2026-10-09T09:12:00Z',projects_total:2,projects_with_work:2,active_projects:2,
  counts:{active:2,verifying:1,recovering:1,waiting_approval:1,blocked:1,ready:1,completed:1,work_orders:6},
  living:{state:'approval',detail:'1 WorkOrder waiting for your approval.'},
  projects:[{project_id:'p1',project_name:'Launch Project',state:'RUNNING'},{project_id:'p2',project_name:'Research Project',state:'READY'}],
  work_orders:[
    {project_id:'p1',project_name:'Launch Project',plan_id:'plan-1',task_id:'publish',work_order_id:'wo-publish',title:'Publish approved launch',worker_type:'communications',status:'WAITING_APPROVAL',ready:false},
    {project_id:'p2',project_name:'Research Project',plan_id:'plan-2',task_id:'recover',work_order_id:'wo-recover',title:'Recover failed browser step',worker_type:'browser',status:'RECOVERY_REQUIRED',ready:false},
    {project_id:'p1',project_name:'Launch Project',plan_id:'plan-1',task_id:'verify',work_order_id:'wo-verify',title:'Verify launch claims',worker_type:'reviewer',status:'VERIFYING',ready:false},
    {project_id:'p1',project_name:'Launch Project',plan_id:'plan-1',task_id:'research',work_order_id:'wo-research',title:'Research launch evidence',worker_type:'research',status:'RUNNING',ready:false},
    {project_id:'p2',project_name:'Research Project',plan_id:'plan-2',task_id:'synthesize',work_order_id:'wo-synthesize',title:'Synthesize findings',worker_type:'data',status:'WAITING',ready:true},
    {project_id:'p2',project_name:'Research Project',plan_id:'plan-2',task_id:'collect',work_order_id:'wo-collect',title:'Collect sources',worker_type:'research',status:'COMPLETED',ready:false},
  ],
};
const attention={
  authority:'read_only_projection',updated_at:'2026-10-09T09:12:00Z',
  counts:{total:4,approval:1,recovery:1,review:1,blocked:1,urgent:2},
  items:[
    {id:'attn-approval',kind:'approval_required',severity:'urgent',project_id:'p1',work_order_id:'wo-publish',approval_id:'ap1',deep_link:'/iphone/?project=p1&section=approvals&work_order=wo-publish'},
    {id:'attn-recovery',kind:'recovery_required',severity:'urgent',project_id:'p2',work_order_id:'wo-recover',deep_link:'/iphone/?project=p2&section=live&work_order=wo-recover'},
    {id:'attn-review',kind:'review_failed',severity:'review',project_id:'p1',work_order_id:'wo-verify',deep_link:'/iphone/?project=p1&section=plan&work_order=wo-verify'},
    {id:'attn-blocked',kind:'blocked',severity:'attention',project_id:'p2',work_order_id:'wo-synthesize',deep_link:'/iphone/?project=p2&section=live&work_order=wo-synthesize'},
  ],
};

const html=`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#03060b;color:#eef5ff;font:14px system-ui}.home-wrap,.today-wrap{max-width:1000px;margin:auto;padding:16px}.today-section{margin:12px 0}.hidden{display:none!important}#homeProjectsSection{min-height:20px}.today-section-head{display:flex;justify-content:space-between}.sidebar-nav-row{display:flex;align-items:center;gap:8px;min-height:44px}</style></head><body>
<nav><button class="sidebar-nav-row" data-app-module="projects">Projects</button><button id="sidebarInbox" class="sidebar-nav-row">Inbox <span id="sidebarInboxCount" class="hidden">0</span></button></nav>
<div class="home-wrap"><div class="state"><strong id="stateLabel">Active</strong><span id="status">Vishnu is ready.</span></div><section id="homeProjectsSection"></section></div>
<div class="today-wrap"><button class="today-tab" data-today-filter="all">All</button><button class="today-tab" data-today-filter="meetings">Meetings</button><div id="todayTasksSection" class="today-section"><div class="today-section-head"><h2>Tasks</h2></div></div></div>
<script>
var stateName='active';var todayScreenFilter='all';window.__opened=[];window.__modules=[];window.__approvalReviews=0;window.__approvalClicked=0;
window.openModule=id=>window.__modules.push(id);
window.openProject=async(id,tab)=>{window.__opened.push({id,tab});const marker=document.createElement('div');marker.dataset.workOrderId=id==='p2'?'wo-recover':'wo-publish';marker.textContent='canonical WorkOrder';document.body.append(marker)};
window.openProjectApprovalReview=async()=>{window.__approvalReviews+=1;const button=document.createElement('button');button.dataset.approvalOpen='ap1';button.onclick=()=>window.__approvalClicked+=1;document.body.append(button)};
</script>
<script src="/global-work-awareness.js"></script></body></html>`;

const server=createServer((req,res)=>{
  requests.push({url:req.url,method:req.method});
  if(req.url==='/global-work-awareness.js'){res.writeHead(200,{'content-type':'application/javascript','cache-control':'no-store'});return res.end(runtime)}
  if(req.url==='/iphone/api/work/summary'){res.writeHead(200,{'content-type':'application/json'});return res.end(JSON.stringify(summary))}
  if(req.url==='/iphone/api/work/attention'){res.writeHead(200,{'content-type':'application/json'});return res.end(JSON.stringify(attention))}
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
    await page.waitForFunction(()=>window.__vishnuGlobalWorkAwareness?.snapshot?.work_orders?.length===6&&window.__vishnuGlobalWorkAwareness?.attention?.counts?.total===4);

    assert.equal(await page.locator('#globalWorkPulse').count(),1);
    const homeText=await page.locator('#globalWorkPulse').innerText();
    assert.match(homeText,/Needs Attention/i);
    assert.match(homeText,/4 need attention/i);
    assert.match(homeText,/2 active/i);
    assert.match(homeText,/1 approval/i);
    assert.match(homeText,/1 recovery/i);
    assert.match(homeText,/1 review/i);
    assert.match(homeText,/1 blocked/i);
    assert.match(homeText,/Canonical Work state only/i);

    assert.equal(await page.locator('#sidebarInboxCount').innerText(),'4');
    assert.equal(await page.locator('#sidebarInboxCount').evaluate(node=>node.classList.contains('hidden')),false);
    assert.equal(await page.locator('[data-app-module="projects"] > .gwa-nav-count').innerText(),'4');
    assert.equal(await page.evaluate(()=>document.body.dataset.workAttentionCount),'4');

    assert.equal(await page.locator('#globalWorkTodaySection').count(),1);
    const todayText=await page.locator('#globalWorkTodaySection').innerText();
    assert.match(todayText,/Vishnu work/i);
    assert.match(todayText,/4 attention/i);
    assert.match(todayText,/Publish approved launch/i);
    assert.match(todayText,/Recover failed browser step/i);
    assert.match(todayText,/Synthesize findings/i);

    assert.equal(await page.locator('#stateLabel').innerText(),'Needs Attention');
    assert.match(await page.locator('#status').innerText(),/4 owner attention items require review/i);
    assert.equal(await page.evaluate(()=>document.body.dataset.globalWorkState),'needs_attention');

    await page.locator('[data-gwa-order]').first().click();
    assert.deepEqual(await page.evaluate(()=>window.__opened.at(-1)),{id:'p1',tab:'live'});

    const deepResult=await page.evaluate(async item=>window.__vishnuGlobalWorkAwareness.openAttention(item),attention.items[1]);
    assert.equal(deepResult,true);
    await page.waitForTimeout(180);
    assert.deepEqual(await page.evaluate(()=>window.__opened.at(-1)),{id:'p2',tab:'live'});
    assert.equal(await page.evaluate(()=>window.__modules.at(-1)),'projects');
    assert.match(await page.evaluate(()=>location.search),/project=p2/);
    assert.match(await page.evaluate(()=>location.search),/work_order=wo-recover/);

    const unsafeResult=await page.evaluate(async()=>window.__vishnuGlobalWorkAwareness.openAttention({deep_link:'https://evil.example/'}));
    assert.equal(unsafeResult,false);

    await page.evaluate(()=>{history.replaceState(null,'','/?section=approvals&approval=ap1');window.__vishnuGlobalWorkAwareness.openAttention({deep_link:'/iphone/?section=approvals&approval=ap1'})});
    await page.waitForTimeout(80);
    assert.equal(await page.evaluate(()=>window.__approvalReviews),1);
    assert.equal(await page.evaluate(()=>window.__approvalClicked),1);

    await page.evaluate(()=>{todayScreenFilter='meetings'});
    await page.locator('.today-tab[data-today-filter="meetings"]').click();
    await page.waitForTimeout(20);
    assert.equal(await page.locator('#globalWorkTodaySection').evaluate(node=>node.classList.contains('hidden')),true);

    await page.evaluate(()=>{stateName='thinking';document.getElementById('stateLabel').textContent='Thinking';document.getElementById('status').textContent='Foreground thinking';window.dispatchEvent(new Event('focus'))});
    await page.waitForTimeout(80);
    assert.equal(await page.locator('#stateLabel').innerText(),'Thinking');
    assert.equal(await page.locator('#status').innerText(),'Foreground thinking');

    if(viewport.isMobile){
      const geometry=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}));
      assert.ok(geometry.scroll<=geometry.viewport+2,`mobile global Work awareness overflows: ${JSON.stringify(geometry)}`);
    }
    assert.deepEqual(errors,[],`global Work awareness page errors at ${viewport.width}px: ${errors.join(' | ')}`);
    await page.close();
  }
} finally {
  await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
assert.equal(requests.some(request=>request.method!=='GET'),false,`global Work awareness made a mutation request: ${JSON.stringify(requests)}`);
assert.ok(requests.filter(request=>request.url==='/iphone/api/work/summary').length>=2,'each viewport should read the owner-scoped global Work summary');
assert.ok(requests.filter(request=>request.url==='/iphone/api/work/attention').length>=2,'each viewport should read the canonical owner attention projection');
console.log('Global canonical Work awareness + attention badge/deep-link browser qualification passed.');
