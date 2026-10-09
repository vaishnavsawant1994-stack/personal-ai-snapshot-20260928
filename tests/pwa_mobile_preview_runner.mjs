import { readFile, writeFile, unlink } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

// The browser suite owns Node-side API fixtures. Playwright's selectOption()
// waits for DOM input/change dispatch, but not for the async PATCH and follow-up
// Ambient Memory reload started by the change listener. Run the canonical suite
// with explicit network/UI boundaries so its existing assertions observe the
// completed save and rendered review queue. Assertions and accepted values stay unchanged.
const sourceUrl = new URL('./pwa_mobile_preview.mjs', import.meta.url);
const generatedUrl = new URL('./.pwa_mobile_preview.generated.mjs', import.meta.url);
const source = await readFile(sourceUrl, 'utf8');
const before = `  await page.locator('[data-mx-retention]').selectOption('6_months');\n  assert.equal(ambientSettings.retention,'6_months','Ambient retention selection persists');`;
const after = `  const ambientRetentionSaved=page.waitForResponse(response=>response.url().includes('/iphone/api/memory/ambient/settings')&&response.request().method()==='PATCH'&&response.ok());\n  const ambientRetentionReloaded=page.waitForResponse(response=>new URL(response.url()).pathname.endsWith('/iphone/api/memory/ambient')&&response.request().method()==='GET'&&response.ok());\n  await page.locator('[data-mx-retention]').selectOption('6_months');\n  await ambientRetentionSaved;\n  await ambientRetentionReloaded;\n  await page.waitForFunction(()=>document.querySelectorAll('.rp-page[data-rp-page="memory"] .mx-candidate').length===1);\n  assert.equal(ambientSettings.retention,'6_months','Ambient retention selection persists');`;

if (!source.includes(before)) {
  throw new Error('Canonical Ambient retention assertion changed; update the synchronization runner explicitly.');
}

await writeFile(generatedUrl, source.replace(before, after), 'utf8');
try {
  await import(generatedUrl.href + '?run=' + Date.now());
} finally {
  await unlink(fileURLToPath(generatedUrl)).catch(() => {});
}