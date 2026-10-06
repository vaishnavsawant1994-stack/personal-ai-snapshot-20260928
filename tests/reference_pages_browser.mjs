import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const root = new URL('../', import.meta.url);
const read = path => readFile(new URL(path, root));
const [css, source] = await Promise.all([read('pwa/reference-pages.css'), read('pwa/reference-pages.js')]);
const fixture = `
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
`;
const browser = await chromium.launch({ headless: true });
try {
  for (const viewport of [{ width: 390, height: 844 }, { width: 768, height: 1024 }, { width: 1440, height: 900 }]) {
    const page = await browser.newPage({ viewport, isMobile: viewport.width < 500, hasTouch: viewport.width < 500 });
    await page.setContent('<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><div class="app-shell"><header class="topbar">Vishnu</header><nav class="nav">Home</nav><section class="module-panel open"><header class="module-head">Old module header</header><div class="module-body" id="moduleBody"></div></section></div>');
    await page.addStyleTag({ content: css });
    await page.addScriptTag({ content: fixture });
    await page.addScriptTag({ content: source.replace("const preview=()=>new URLSearchParams(location.search).get('uiDemo')==='1';", 'const preview=()=>true;') });
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
      assert.equal(await page.locator('.rp-page[data-rp-page="today"] .rp-heading h1 .rp-mobile-date').evaluate(el => getComputedStyle(el).display), 'inline');
      const filters = await page.locator('.rp-filters').first().evaluate(el => ({ width: el.clientWidth, scrollWidth: el.scrollWidth }));
      assert.ok(filters.width <= layout.width + 1, 'Filter row should stay within the viewport');
      const order = await page.evaluate(() => ['.rp-summary','.rp-focus','.rp-timeline-wrap','.rp-sidebar>.rp-panel:not(.rp-focus)'].map(selector => document.querySelector(selector)?.getBoundingClientRect().top));
      assert.ok(order[0] < order[1] && order[1] < order[2] && order[2] < order[3], `Today mobile content should follow the reference order: ${order}`);
    }
    await page.locator('[data-rp-menu]').click();
    await page.locator('#appConversations').click();
    await page.locator('.rp-page[data-rp-page="conversations"]').waitFor();
    assert.equal(await page.locator('#fixtureDrawer').isVisible(), false, 'Conversation navigation should leave the drawer and open the page');
    assert.equal(await page.locator('.rp-page[data-rp-page="conversations"] .rp-conversation-layout').count(), 1);
    assert.equal(await page.locator('.rp-conv-tools>.rp-search').count(), 1, 'Conversation search should share the toolbar with its filters');
    assert.equal(await page.locator('.rp-page[data-rp-page="conversations"] .rp-actions-group .rp-button').isVisible(), true);
    if (viewport.width > 760) {
      const toolbarRows = await page.locator('.rp-conv-tools').evaluate(el => [...el.children].map(child => Math.round(child.getBoundingClientRect().top)));
      assert.ok(Math.max(...toolbarRows)-Math.min(...toolbarRows) <= 4, `Search, filters and sort should share one desktop toolbar row: ${toolbarRows}`);
      assert.equal(await page.locator('.rp-page[data-rp-page="conversations"] .rp-actions>[data-rp-new-chat]').isVisible(), false, 'Conversation footer should not duplicate New chat actions');
    }
    await page.evaluate(() => window.openModule('tools'));
    await page.locator('.rp-page[data-rp-page="tools"]').waitFor();
    assert.equal(await page.locator('.rp-page[data-rp-page="tools"] .rp-heading').count(), 1, 'Tools should have one page heading and shell');
    await page.getByRole('heading', { name: 'Web research' }).waitFor();
    assert.equal(await page.locator('.rp-tool-card').count(), 5, 'Tools page should show all five reference capabilities');
    assert.equal(await page.getByText('Tools run when you ask Vishnu to use them.').count(), 1);
    await page.getByPlaceholder('Search tools').fill('image');
    assert.equal(await page.locator('.rp-tool-card').count(), 1, 'Tools search should filter tool cards');
    await page.getByPlaceholder('Search tools').fill('');
    await page.getByRole('button', { name: 'Plan', exact: true }).click();
    assert.equal(await page.locator('.rp-tool-card').count(), 1, 'Tools category chips should filter by category');
    await page.getByPlaceholder('Search tools').fill('no such capability');
    await page.getByRole('button', { name: 'Clear search and filters' }).first().click();
    assert.equal(await page.locator('.rp-tool-card').count(), 5, 'Tools empty-state reset should restore the full list');
    if (viewport.width <= 760) {
      await page.locator('[data-rp-tool-select="web-research"]').click();
      assert.equal(await page.locator('.rp-mobile-tool-detail.open').count(), 1, 'Mobile tool details should open as a detail view');
      await page.locator('[data-rp-tool-back]').click();
    }
    assert.equal(await page.locator('.rp-page[data-rp-page="tools"] .rp-actions').isVisible(), true);
    await page.evaluate(() => window.openModule('workflows'));
    await page.locator('.rp-page[data-rp-page="workflows"]').waitFor();
    assert.equal(await page.locator('.rp-page[data-rp-page="workflows"] .rp-heading').count(), 1, 'Workflows should have one page heading and shell');
    assert.equal(await page.locator('.rp-workflow-card').count(), 5, 'Workflow preview includes fifth active item for truthful summary totals');
    assert.match(await page.locator('.rp-workflow-summary').innerText(), /3\s+active[\s\S]*1\s+paused[\s\S]*1\s+needs review/);
    await page.getByPlaceholder('Search workflows').fill('weekly planning');
    assert.equal(await page.locator('.rp-workflow-card').count(), 1, 'Workflow search should filter the persisted/demo source list');
    await page.getByPlaceholder('Search workflows').fill('');
    assert.equal(await page.locator('.rp-page[data-rp-page="workflows"] .rp-actions').isVisible(), true);
    await page.close();
  }
  console.log('Reference-page browser checks passed at 390px, 768px, and 1440px: no page overflow, one header/hamburger, correct Today counts, and Conversations opens as a page from the menu.');
} finally {
  await browser.close();
}
