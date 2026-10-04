import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.route("**/iphone/api/**", route => {
    const isStatus = new URL(route.request().url()).pathname.endsWith("/status");
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(isStatus
        ? { model: { state: "ready" }, conversations: [], conversation: null }
        : {}),
    });
  });
  await page.route("https://accounts.google.com/**", route => route.abort());
  await page.goto("http://127.0.0.1:4173/iphone/", { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => !document.querySelector("#voicePanel").classList.contains("hidden"));
  await page.evaluate(() => {
    document.querySelector("#stateLabel").textContent = "Ready";
    document.querySelector("#status").textContent = "Tap the microphone once and speak naturally.";
    const stream = document.querySelector("#messageStream");
    const fixture = [
      ["assistant", "Hi, Vaishnav. I can help answer questions, plan, write, and organize information. What would you like to do today?"],
      ["user", "Can you explain how the whole system works inside you?"],
      ["assistant", "I’m your personal AI. I can help with questions, planning, writing, and your saved knowledge. Ask me about any part, and I’ll explain it clearly."],
    ];
    for (const [role, text] of fixture) {
      const message = document.createElement("div");
      message.className = "message " + role;
      message.textContent = text;
      stream.append(message);
    }
    document.body.classList.add("has-conversation");
    stream.scrollTop = stream.scrollHeight;
  });
  await page.waitForFunction(() => {
    const canvas = document.querySelector("#neuralCanvas");
    return canvas.width > 0 && canvas.height > 0;
  });
  await page.waitForTimeout(500);
  const initialCanvasInk = await page.evaluate(() => {
    const canvas = document.querySelector("#neuralCanvas");
    const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    let ink = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i + 3] > 12 && (pixels[i] > 80 || pixels[i + 1] > 100 || pixels[i + 2] > 150)) ink++;
    }
    return ink;
  });
  assert.ok(initialCanvasInk > 200, "neural mesh did not paint at 390x844");
  await page.screenshot({ path: "artifacts/personal-ai-iphone-390x844.png" });

  const checkLayout = async (width, height) => {
    await page.setViewportSize({ width, height });
    await page.waitForTimeout(500);
    const screenshotNames = new Map([[320, "personal-ai-phone-small-320x568.png"], [390, "personal-ai-phone-standard-390x844.png"], [768, "personal-ai-tablet-portrait-768x1024.png"], [1024, "personal-ai-tablet-landscape-1024x768.png"], [1366, "personal-ai-desktop-1366x768.png"], [1920, "personal-ai-wide-desktop-1920x1080.png"]]);
    if (screenshotNames.has(width)) await page.screenshot({ path: `artifacts/${screenshotNames.get(width)}` });
    const data = await page.evaluate(() => {
      const rect = selector => {
        const r = document.querySelector(selector).getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, width: r.width, height: r.height };
      };
      const canvas = document.querySelector("#neuralCanvas");
      const pixels = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
      let canvasInk = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i + 3] > 12 && (pixels[i] > 80 || pixels[i + 1] > 100 || pixels[i + 2] > 150)) canvasInk++;
      }
      const visibleLabels = [...document.querySelectorAll(".nav button")]
        .filter(item => item.getBoundingClientRect().width > 0)
        .map(item => item.querySelector("span")?.textContent.trim());
      return {
        canvasInk,
        viewportWidth: innerWidth,
        documentWidth: document.documentElement.scrollWidth,
        core: rect(".core-stage"),
        canvas: rect("#neuralCanvas"),
        messages: rect("#messageStream"),
        composer: rect("#composer"),
        nav: rect(".nav"),
        visibleLabels,
        finalMessageBottom: document.querySelector("#messageStream").lastElementChild?.getBoundingClientRect().bottom ?? 0,
      };
    });
    console.log(`layout diagnostics ${width}x${height}: ${JSON.stringify({data,pageErrors})}`);
    assert.deepEqual(data.visibleLabels, ["Home", "Memory", "Knowledge", "Activities", "More"], `wrong visible nav labels at ${width}x${height}`);
    assert.ok(data.documentWidth <= data.viewportWidth, `horizontal overflow at ${width}x${height}`);
    assert.ok(data.core.height > 0 && data.canvas.height > 0, `Core missing at ${width}x${height}`);
    assert.ok(data.messages.height > 0, `message viewport missing at ${width}x${height}`);
    assert.ok(data.canvasInk > 200, `neural mesh did not repaint after viewport change to ${width}x${height}`);
    assert.ok(data.finalMessageBottom <= data.messages.bottom + 1, `latest message is clipped at ${width}x${height}`);
    assert.ok(data.composer.bottom <= height + 1, `composer is clipped at ${width}x${height}`);
    if (width <= 900) {
      assert.ok(data.composer.bottom < data.nav.top, `composer overlaps bottom navigation at ${width}x${height}`);
    } else {
      assert.ok(data.nav.bottom < data.composer.top, `desktop navigation overlaps composer at ${width}x${height}`);
    }
  };
  await checkLayout(320, 568);
  await checkLayout(390, 844);
  await checkLayout(430, 932);
  await checkLayout(768, 1024);
  await checkLayout(1024, 768);
  await checkLayout(1366, 768);
  await checkLayout(1920, 1080);

  // 200% browser zoom leaves roughly half the CSS viewport. Verify the compact
  // phone layout at that effective size without pretending this is a native zoom test.
  await page.setViewportSize({ width: 195, height: 422 });
  const zoomLayout = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
    composerVisible: document.querySelector("#composer").getBoundingClientRect().height > 0,
  }));
  assert.ok(zoomLayout.width <= zoomLayout.viewport, "horizontal overflow at a 200%-zoom-equivalent viewport");
  assert.ok(zoomLayout.composerVisible, "composer missing at a 200%-zoom-equivalent viewport");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const reducedMotionSeconds = await page.locator(".core-glow").evaluate(el => parseFloat(getComputedStyle(el).animationDuration));
  assert.ok(reducedMotionSeconds <= 0.00001, `reduced motion animation is not suppressed: ${reducedMotionSeconds}s`);
  await page.keyboard.press("Tab");
  const keyboardFocus = await page.evaluate(() => {
    const el = document.activeElement;
    return el !== document.body && !!el && el.getClientRects().length > 0 && el.tabIndex >= 0;
  });
  assert.ok(keyboardFocus, "Tab should move focus to a visible keyboard-operable control");
  assert.deepEqual(pageErrors, [], "page must render without uncaught JavaScript errors");
  console.log("PWA responsive layout passed for phone, tablet portrait/landscape, desktop, wide desktop, 200%-zoom-equivalent viewport, keyboard focus, and reduced motion.");
} finally {
  await browser.close();
}
