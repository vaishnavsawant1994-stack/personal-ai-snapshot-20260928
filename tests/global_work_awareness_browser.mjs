import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require=createRequire(import.meta.url);
const { chromium }=require('playwright');
const root=new URL('../',import.meta.url);
const runtime=await readFile(new URL('pwa/global-work-awareness.js',root),'utf8');
const requests=[];

const projects={projects:[
  {id:'p1',name:'Launch Project',status:'active',updated_at:'2026-10-09T09:00:00Z'},
  {id:'p2',name:'Research Project',status:'active',updated_at:'2026-10-09T08:00:00Z'},
]};
const snapshots={
  p1:{state:'planned',p10_plan:{id:'plan-1',state:'RUNNING',tasks:[
    {id:'research',title:'Research launch evidence',status:'RUNNING',worker_type:'research',dependencies:[]},
    {id:'verify',title:'Verify launch claims',status:'VERIFYING',worker_type:'reviewer',dependencies:['research']},
    {id:'publish',title:'Publish approved launch',status:'WAITING_APPROVAL',worker_type:'communications',dependencies:['verify']},
  ]},live_work:{state:'RUNNING',updated_at:'2026-10-09T09:10:00Z'}},
  p2:{state:'planned',p10_plan:{id:'plan-2',state:'READY',tasks:[
    {id:'collect',title:'Collect sources',status:'COMPLETED',worker_type:'research',dependencies:[]},
    {id:'synthesize',title:'Synthesize findings',status:'WAITING',worker_type:'data',dependencies:['collect']},
    {id:'recover',title:'Recover failed browser step',status:'RECOVERY_REQUIRED',worker_type:'browser',dependencies:[]},
  ]},live_work:{state:'READY',updated_at:'2026-10-09T09:11:00Z'}},
};

const html=`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#03060b;color:#eef5ff;font:14px system-ui}.home-wrap,.today-wrap{max-width:1000px;margin:auto;padding:16px}.today-section{margin:12px 0}.hidden{display:none!important}#homeProjectsSection{min-height:20px}.today-section-head{display:flex;justify-content:space-between}</style></head><body>
<div class="home-wrap"><div class="state"><strong id="stateLabel">Active</strong><span id="status">Vishnu is ready.</span></div><section id="homeProjectsSection"></section></div>
<div class="today-wrap"><button class="today-tab" data-today-filter="all">All</button><button class="today-tab" data-today-filter="meetings">Meetings</button><div id="todayTasksSection" class="today-section"><div class="today-section-head"><h2>Tasks</h2></div></div></div>
<script>var stateName='active';var todayScreenFilter='all';window.__opened=[];window.openProject=(id,tab)=>window.__opened.push({id,tab});window.openModule=()=>{};</script>
<script src="/global-work-awareness.js"></script></body></html>`;

const server=createServer((req,res)=>{
  requests.push({url:req.url,method:req.method});
  if(req.url==='/global-work-awareness.js'){res.writeHead(200,{'content-type':'application/javascript','cache-control':'no-store'});return res.end(runtime)}
  if(req.url==='/iphone/api/projects?status=all'){res.writeHead(200,{'content-type':'application/json'});return res.end(JSON.stringify(projects))}
  const match=req.url?.match(/^\/iphone\/api\/projects\/(p[12])\/work$/);
  if(match){res.writeHead(200,{'content-type':'application/json'});return res.end(JSON.stringify(snapshots[match[1]]))}
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
    await page.waitForFunction(()=>window.__vishnuGlobalWorkAwareness?.snapshot?.workOrders?.length===6);

    assert.equal(await page.locator('#globalWorkPulse').count(),1);
    const homeText=await page.locator('#globalWorkPulse').innerText();
    assert.match(homeText,/Needs Attention/i);
    assert.match(homeText,/2 active/i);
    assert.match(homeText,/1 approval/i);
    assert.match(homeText,/1 blocked/i);
    assert.match(homeText,/1 ready/i);
    assert.match(homeText,/Canonical Work state only/i);

    assert.equal(await page.locator('#globalWorkTodaySection').count(),1);
    const todayText=await page.locator('#globalWorkTodaySection').innerText();
    assert.match(todayText,/Vishnu work/i);
    assert.match(todayText,/Research launch evidence/i);
    assert.match(todayText,/Recover failed browser step/i);
    assert.match(todayText,/Synthesize findings/i);

    assert.equal(await page.locator('#stateLabel').innerText(),'Needs Attention');
    assert.match(await page.locator('#status').innerText(),/blocked or require recovery/i);

    await page.locator('[data-gwa-order]').first().click();
    assert.deepEqual(await page.evaluate(()=>window.__opened.at(-1)),{id:'p1',tab:'live'});

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
console.log('Global canonical Work awareness browser qualification passed.');
