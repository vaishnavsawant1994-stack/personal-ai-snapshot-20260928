import { chromium } from "playwright";

const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:390,height:568},isMobile:true,hasTouch:true});
try{
  await page.goto("http://127.0.0.1:4175/",{waitUntil:"domcontentloaded"});
  await page.waitForSelector("#home.active");
  for(const [width,height,name] of [[390,568,"phone-390x568"],[768,960,"tablet-768x960"],[1440,960,"desktop-1440x960"],[2560,960,"wide-2560x960"]]){
    await page.setViewportSize({width,height});
    await page.screenshot({path:`artifacts/web-companion-before-${name}.png`,fullPage:true});
  }
}finally{await browser.close()}
