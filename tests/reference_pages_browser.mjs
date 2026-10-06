import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const root = new URL('../', import.meta.url);
const read = path => readFile(new URL(path, root));
const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const send = (body, type = 'application/javascript') => { res.writeHead(200, { 'content-type': type, 'cache-control': 'no-store' }); res.end(body); };
  if (url.pathname === '/') return send(`<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/reference-pages.css"><div class="app-shell"><header class="topbar">Vishnu</header><nav class="nav">Home</nav><section class="module-panel open"><header class="module-head">Old module header</header><div class="module-body" id="moduleBody"></div></section></div><script>
    window.escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    window.sectionIcon = () => '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/></svg>';
    window.showToast = () => {};
    window.createConversation = async () => ({ id: 'new' });
    window.openConversation = async id => { document.body.dataset.openConversation = id; };
    window.updateSidebarPin = async () => {};
    window.openMemoryDetail = async () => {};
    window.openKnowledgeDetail = async () => {};
    window.openProject = async () => {};
    window.openAppDrawer = () => { let drawer = document.getElementById('fixtureDrawer'); if (!drawer) { drawer = document.createElement('aside'); drawer.id = 'fixtureDrawer'; drawer.innerHTML = '<button id="appConversations">Conversations</button>'; document.body.append(drawer); } drawer.hidden = false; };
    window.closeAllDrawers = () => { const drawer = document.getElementById('fixtureDrawer'); if (drawer) drawer.hidden = true; };
    window.api = async path => {
      if (path.startsWith('/everyday/timeline')) return { items: [
        { id:'task-1',kind:'task',title:'Review Personal AI mobile UI',description:'Review screens',due_at:new Date(new Date().setHours(9,30,0,0)).toISOString(),status:'scheduled' },
        { id:'meeting-1',kind:'commitment',title:'Design review',due_at:new Date(new Date().setHours(11,0,0,0)).toISOString(),status:'scheduled' },
        { id:'plan-1',kind:'plan',title:'Plan tomorrow',due_at:new Date(new Date().setHours(16,30,0,0)).toISOString(),status:'scheduled' }
      ]};
      if (path.startsWith('/projects/timeline')) return { items: [] };
      if (path.startsWith('/conversations')) return { conversations: [{ id:'conversation-1',title:'Today page spacing review',preview:'Review the spacing changes.',updated_at:new Date().toISOString() }] };
      if (path === '/preferences') return { pinned_sidebar_items: [] };
      return { items: [], memories: [], collections: [], sources: [], activities: [] };
    };
    window.openModule = () => { window.closeAllDrawers(); return Promise.resolve(); };
  </script><script src="/reference-pages.js"></script>`,'text/html; charset=utf-8');
  if (url.pathname === '/reference-pages.css') return send(await read('pwa/reference-pages.css'), 'text/css');
  if (url.pathname === '/reference-pages.js') return send(await read('pwa/reference-pages.js'));
  res.writeHead(404); res.end();
});

await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const address = server.address();
const browser = await chromium.launch({ headless: true });
try {
  for (const viewport of [{ width: 390, height: 844 }, { width: 768, height: 1024 }, { width: 1440, height: 900 }]) {
    const page = await browser.newPage({ viewport, isMobile: viewport.width < 500, hasTouch: viewport.width < 500 });
    await page.goto(`http://127.0.0.1:${address.port}/?uiDemo=1`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(() => window.openModule('today'));
    await page.locator('.rp-page[data-rp-page="today"]').waitFor();
    await page.getByRole('button', { name: /3 Tasks/ }).waitFor();
    await page.getByRole('button', { name: /1 Meetings/ }).waitFor();
    await page.getByRole('button', { name: /1 Plans/ }).waitFor();
    const layout = await page.evaluate(() => ({
      width: innerWidth,
      bodyWidth: document.documentElement.scrollWidth,
      mainWidth: document.querySelector('.rp-main').clientWidth,
      pageWidth: document.querySelector('.rp-page').getBoundingClientRect().width,
      topbarDisplay: getComputedStyle(document.querySelector('.topbar')).display,
      headingCount: document.querySelectorAll('.rp-heading').length,
      menuCount: document.querySelectorAll('.rp-top-mobile [data-rp-menu]').length,
      pageName: document.querySelector('.rp-page').dataset.rpPage
    }));
    assert.ok(layout.bodyWidth <= layout.width + 1, `No horizontal page overflow at ${viewport.width}px: ${JSON.stringify(layout)}`);
    assert.equal(layout.headingCount, 1, 'One page heading should render');
    assert.equal(layout.menuCount, 1, 'One working hamburger should render');
    assert.equal(layout.topbarDisplay, 'none', 'Global app header should not duplicate reference page header');
    if (viewport.width <= 760) {
      assert.equal(await page.locator('.rp-page[data-rp-page="today"] .rp-top-mobile strong').evaluate(el => getComputedStyle(el).display), 'block');
      assert.equal(await page.locator('.rp-page[data-rp-page="today"] .rp-heading h1').evaluate(el => getComputedStyle(el).display), 'none');
      const filters = await page.locator('.rp-filters').first().evaluate(el => ({ width: el.clientWidth, scrollWidth: el.scrollWidth }));
      assert.ok(filters.width <= layout.width + 1, 'Filter row should stay within the viewport');
    }
    await page.locator('[data-rp-menu]').click();
    await page.locator('#appConversations').click();
    await page.locator('.rp-page[data-rp-page="conversations"]').waitFor();
    assert.equal(await page.locator('#fixtureDrawer').isVisible(), false, 'Conversation navigation should leave the drawer and open the page');
    assert.equal(await page.locator('.rp-page[data-rp-page="conversations"] .rp-conversation-layout').count(), 1);
    await page.close();
  }
  console.log('Reference-page browser checks passed at 390px, 768px, and 1440px: no page overflow, one header/hamburger, correct Today counts, and Conversations opens as a page from the menu.');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
