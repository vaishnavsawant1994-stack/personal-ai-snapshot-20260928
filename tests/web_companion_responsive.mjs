import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
const errors = [];
page.on("pageerror", error => errors.push(error.message));

try {
  await page.goto("http://127.0.0.1:4174/", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#home.active");
  const unnamedControls=await page.locator("button:visible").evaluateAll(buttons=>buttons
    .filter(button=>!((button.getAttribute("aria-label")||"").trim()||(button.innerText||button.textContent||"").trim()||button.getAttribute("title")))
    .map(button=>button.outerHTML));
  assert.deepEqual(unnamedControls,[],"visible buttons must have accessible names");
  for(const [id,name] of [["memory-query","Search memory"],["runtime-origin","Secure runtime URL"],["pair-token","Pairing token"],["pair-code","Pairing code"],["owner-secret","Owner secret"],["prompt","Ask Personal AI"]]){
    assert.equal(await page.locator(`#${id}`).getAttribute("aria-label"),name,`${id} must have a programmatic label`);
  }
  const widths = new Set([320, 360, 375, 390, 430, 600, 768, 820, 1024, 1280, 1440, 1920, 2560]);
  for (let width = 320; width <= 2560; width += 40) widths.add(width);
  for (const width of [...widths].sort((a, b) => a - b)) {
    await page.setViewportSize({ width, height: width < 700 ? 568 : 960 });
    const metrics = await page.evaluate(() => {
      const rect = selector => {
        const box = document.querySelector(selector).getBoundingClientRect();
        return { left: box.left, right: box.right, width: box.width, height: box.height };
      };
      return {
        viewport: innerWidth,
        document: document.documentElement.scrollWidth,
        composer: rect("footer form"),
        send: rect("footer form button"),
        title: getComputedStyle(document.querySelector("h1")).fontSize,
      };
    });
    assert.ok(metrics.document <= width, `Web companion page overflow at ${width}: ${JSON.stringify(metrics)}`);
    assert.ok(metrics.composer.left >= -1 && metrics.composer.right <= width + 1, `Composer escaped viewport at ${width}`);
    assert.ok(metrics.send.width >= 44 && metrics.send.height >= 44, `Send touch target under 44px at ${width}`);
    assert.ok(parseFloat(metrics.title) >= 22, `Title became too small at ${width}`);
    if ([320, 390, 768, 1440, 2560].includes(width)) {
      const name = width < 400 ? "phone" : width < 900 ? "tablet" : width < 2000 ? "desktop" : "wide";
      await page.screenshot({ path: `artifacts/web-companion-${name}-${width}.png`, fullPage: true });
    }
  }

  await page.setViewportSize({ width: 390, height: 360 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const reduced = await page.evaluate(() => ({
    requested: matchMedia("(prefers-reduced-motion: reduce)").matches,
    pulse: getComputedStyle(document.querySelector(".core"), "::before").animationName,
  }));
  assert.equal(reduced.requested, true);
  assert.equal(reduced.pulse, "none");
  await page.getByRole("button", { name: "Memory" }).focus();
  assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Memory");
  await page.getByRole("button", { name: "Control" }).click();
  assert.ok(await page.locator("#runtime-origin").isVisible(), "secure-pairing fields remain reachable on short screens");
  assert.deepEqual(errors, [], "web companion renders without uncaught JavaScript errors");
  console.log(`Web companion responsive qualification passed ${widths.size} widths from 320px through 2560px, 360px short-height layout, keyboard focus and reduced motion.`);
} finally {
  await browser.close();
}
