import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({
  headless: true,
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {}),
  ...(process.env.PLAYWRIGHT_CHROMIUM_ARGS ? { args: process.env.PLAYWRIGHT_CHROMIUM_ARGS.split(" ").filter(Boolean) } : {}),
});
const preferences = {
  appearance_theme:"dark",appearance_accent:"blue",appearance_density:"comfortable",appearance_motion:"standard",appearance_text_size:"default",
  chat_enter_sends:true,chat_keep_composer_visible:true,chat_response_detail:"detailed",chat_response_style:"clear_step_by_step",chat_show_sources:true,
  chat_show_timestamps:true,chat_show_actions:true,chat_message_spacing:"comfortable",chat_new_context:"general",chat_project_context_enabled:false,
  privacy_memory_enabled:true,privacy_review_before_saving:true,privacy_allow_project_context_general:false,privacy_save_conversations:true,
  privacy_retention:"until_deleted",privacy_share_anonymous_usage_data:false,profile_display_name:"Vishnu",
  locale_app_language:"en",locale_region:"IN",locale_time_zone:"Asia/Kolkata",locale_use_device_time_zone:false,
  locale_date_format:"day_month_year",locale_time_format:"12h",locale_week_start:"monday",locale_number_format:"indian",locale_temperature:"celsius",locale_measurement:"metric",
};
const profile={first_name:"Vishnu",last_name:"Owner",display_name:"Vishnu",email:"owner@example.test",email_verified:true,account_created_at:"2025-01-15T00:00:00Z",account_id_masked:"•••• 4821",avatar_available:false};
const notificationPreferences={
  events:{task_reminders:{enabled:false,channels:[]},work_completed:{enabled:true,channels:["in_app"]},needs_review:{enabled:true,channels:["in_app"]},blocked_work:{enabled:true,channels:["in_app"]},workflow_updates:{enabled:false,channels:[]},product_updates:{enabled:false,channels:[]}},
  quiet_hours:{enabled:true,start:"22:00",end:"08:00",timezone:"Asia/Kolkata"},allow_urgent_reviews:true,
  daily_summary:{enabled:true,time:"08:00"},weekly_summary:{enabled:false,weekday:0,time:"08:00"},
};
const availability={in_app:true,push:false,email:false,scheduler:true,supported_events:["work_completed","needs_review","blocked_work","workflow_updates"]};
let failNextPreferencesSave=false;

try {
  const page=await browser.newPage({viewport:{width:1505,height:1045},deviceScaleFactor:1});
  const errors=[];page.on("pageerror",error=>errors.push(error.message));
  await page.route("**/iphone/api/**",async route=>{
    const request=route.request(),url=new URL(request.url()),path=url.pathname.replace("/iphone/api","");let body={};
    if(path==="/status")body={model:{state:"ready",providers:[]},conversations:[],memory_count:0,active_qualification:true};
    else if(path==="/system/status")body={model:{state:"ready",providers:[]},integrations:[],tools:[],emergency_stop:false};
    else if(path==="/devices")body={devices:[]};
    else if(path==="/access/security")body={password_configured:true,passkeys:[],google_configured:false};
    else if(path==="/preferences"&&request.method()==="PUT"){if(failNextPreferencesSave){failNextPreferencesSave=false;return route.fulfill({status:503,contentType:"application/json",body:JSON.stringify({detail:"Temporarily unavailable"})})}Object.assign(preferences,JSON.parse(request.postData()||"{}"));body=preferences;}
    else if(path==="/preferences")body=preferences;
    else if(path==="/profile/metadata")body=profile;
    else if(path==="/profile"&&request.method()==="PUT"){Object.assign(profile,JSON.parse(request.postData()||"{}"));body={saved:true,...profile};}
    else if(path==="/profile/account-id/copy")body={account_id:"owner-real-id-4821"};
    else if(path==="/notifications/preferences"&&request.method()==="PUT"){Object.assign(notificationPreferences,JSON.parse(request.postData()||"{}"));body={preferences:notificationPreferences,availability};}
    else if(path==="/notifications/preferences")body={preferences:notificationPreferences,availability};
    else if(path==="/notifications/inbox")body={notifications:[],unread_count:0};
    return route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
  });
  await page.goto("http://127.0.0.1:4173/iphone/",{waitUntil:"domcontentloaded"});
  await page.waitForFunction(()=>document.querySelector("#ownerButton"));
  await page.evaluate(()=>openModule("settings"));
  await page.waitForFunction(()=>document.querySelector("[data-settings-section='profile']"));

  const pages=[
    ["profile","Profile"],["appearance","Appearance"],["notifications","Event preferences"],["chat","Chat preferences"],["data","Privacy & data"],["personal","Language & region"],
  ];
  for(const width of [1505,393,320]){
    await page.setViewportSize({width,height:width>700?1045:852});
    for(const [section,heading] of pages){
      if(width<=700)await page.evaluate(value=>renderSettings(value),section);
      else await page.locator(`[data-settings-section="${section}"]`).click();
      await page.waitForFunction(text=>document.querySelector("#moduleBody")?.innerText.includes(text),heading);
      if(section==="personal"&&width<=700)await page.evaluate(()=>{document.querySelector('#moduleBody')?.scrollTo(0,0);document.querySelector('.settings-content')?.scrollTo(0,0);window.scrollTo(0,0)});
      const dimensions=await page.evaluate(()=>({scrollWidth:document.documentElement.scrollWidth,innerWidth,bodyWidth:document.body.scrollWidth}));
      assert.ok(dimensions.scrollWidth<=dimensions.innerWidth+1,`${section} overflows at ${width}px: ${JSON.stringify(dimensions)}`);
      if(width===1505)await page.screenshot({path:`artifacts/settings-${section}-desktop.png`,fullPage:true});
      if(width===393)await page.screenshot({path:`artifacts/settings-${section}-mobile.png`,fullPage:true});
      if(section==="personal"&&width===393){
        await page.setViewportSize({width:393,height:1360});
        await page.evaluate(()=>renderSettings('personal'));
        await page.waitForFunction(()=>document.querySelector("#localePreviewDate"));
        await page.evaluate(()=>{document.querySelector('#moduleBody')?.scrollTo(0,0);document.querySelector('.settings-content')?.scrollTo(0,0);window.scrollTo(0,0)});
        await page.screenshot({path:"artifacts/settings-language-region-mobile-full.png",fullPage:true});
        await page.setViewportSize({width:393,height:852});
        await page.evaluate(()=>renderSettings('personal'));
        await page.waitForFunction(()=>document.querySelector("#localePreviewDate"));
        const usStyleSave=page.waitForResponse(response=>response.url().includes('/preferences')&&response.request().method()==='PUT');
        await page.locator('button[data-locale-key="locale_date_format"][data-locale-value="month_day_year"]').click();
        await page.waitForFunction(()=>document.querySelector("#localePreviewDate")?.textContent.includes("Oct 5, 2026"));
        await usStyleSave;
        const dateSave=page.waitForResponse(response=>response.url().includes('/preferences')&&response.request().method()==='PUT');
        await page.locator('button[data-locale-key="locale_date_format"][data-locale-value="numeric"]').click();
        await page.waitForFunction(()=>document.querySelector("#localePreviewDate")?.textContent.includes("05/10/2026"));
        await dateSave;
        assert.equal(preferences.locale_date_format,"numeric","date format must persist via the preferences API");
        const timeSave=page.waitForResponse(response=>response.url().includes('/preferences')&&response.request().method()==='PUT');
        await page.locator('[data-locale-key="locale_time_format"][data-locale-value="24h"]').click();
        await page.waitForFunction(()=>document.querySelector("#localePreviewTime")?.textContent.includes("05:57"));
        await timeSave;
        assert.equal(preferences.locale_time_format,"24h","time format must persist via the preferences API");
        assert.equal(await page.locator('option[value="hi"]').isDisabled(),true,"unsupported app languages must remain unavailable");
        const deviceToggle=page.locator('[data-locale-device-zone]');
        const deviceOnSave=page.waitForResponse(response=>response.url().includes('/preferences')&&response.request().method()==='PUT');
        await deviceToggle.click();
        assert.equal(await page.locator('[data-locale-key="locale_time_zone"]').isDisabled(),true,"device timezone must disable manual selection");
        await deviceOnSave;
        const deviceOffSave=page.waitForResponse(response=>response.url().includes('/preferences')&&response.request().method()==='PUT');
        await deviceToggle.click();
        await deviceOffSave;
        failNextPreferencesSave=true;
        const failedSave=page.waitForResponse(response=>response.url().includes('/preferences')&&response.request().method()==='PUT');
        await page.locator('[data-locale-key="locale_region"]').selectOption("US");
        await failedSave;
        await page.waitForFunction(()=>document.querySelector('#localeRetrySave')&&!document.querySelector('#localeRetrySave').hidden);
        assert.equal(await page.locator('[data-locale-key="locale_region"]').inputValue(),"US","failed save must retain the current selection");
        const retrySave=page.waitForResponse(response=>response.url().includes('/preferences')&&response.request().method()==='PUT');
        await page.locator('#localeRetrySave').click();
        await retrySave;
        assert.equal(preferences.locale_region,"US","retry must persist the selected region");
        await page.reload({waitUntil:"domcontentloaded"});
        await page.waitForFunction(()=>document.querySelector("#ownerButton"));
        await page.evaluate(()=>openModule("settings"));
        await page.waitForFunction(()=>document.querySelector("[data-settings-section='profile']"));
        await page.evaluate(()=>renderSettings('personal'));
        await page.waitForFunction(()=>document.querySelector('[data-locale-key="locale_region"]'));
        assert.equal(await page.locator('[data-locale-key="locale_region"]').inputValue(),"US","saved region must hydrate after refresh");
        assert.equal(await page.locator('[data-locale-key="locale_date_format"][data-locale-value="numeric"]').getAttribute('aria-pressed'),"true","saved date format must hydrate after refresh");
      }
      await page.evaluate(()=>renderSettingsIndex());
    }
  }
  assert.deepEqual(errors,[],"Settings screens must not create uncaught browser errors");
  console.log("Responsive Settings preview passed: Profile, Appearance, Notifications, Chat preferences, Privacy & data, and Language & region at 1505px, 393px, and 320px.");
} finally { await browser.close(); }
