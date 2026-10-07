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
};
const profile={first_name:"Vishnu",last_name:"Owner",display_name:"Vishnu",email:"owner@example.test",email_verified:true,account_created_at:"2025-01-15T00:00:00Z",account_id_masked:"•••• 4821",avatar_available:false};
const notificationPreferences={
  events:{task_reminders:{enabled:false,channels:[]},work_completed:{enabled:true,channels:["in_app"]},needs_review:{enabled:true,channels:["in_app"]},blocked_work:{enabled:true,channels:["in_app"]},workflow_updates:{enabled:false,channels:[]},product_updates:{enabled:false,channels:[]}},
  quiet_hours:{enabled:true,start:"22:00",end:"08:00",timezone:"Asia/Kolkata"},allow_urgent_reviews:true,
  daily_summary:{enabled:true,time:"08:00"},weekly_summary:{enabled:false,weekday:0,time:"08:00"},
};
const availability={in_app:true,push:false,email:false,scheduler:true,supported_events:["work_completed","needs_review","blocked_work","workflow_updates"]};

try {
  const page=await browser.newPage({viewport:{width:1505,height:1045},deviceScaleFactor:1});
  const errors=[];page.on("pageerror",error=>errors.push(error.message));
  await page.route("**/iphone/api/**",async route=>{
    const request=route.request(),url=new URL(request.url()),path=url.pathname.replace("/iphone/api","");let body={};
    if(path==="/status")body={model:{state:"ready",providers:[]},conversations:[],memory_count:0,active_qualification:true};
    else if(path==="/system/status")body={model:{state:"ready",providers:[]},integrations:[],tools:[],emergency_stop:false};
    else if(path==="/devices")body={devices:[]};
    else if(path==="/access/security")body={password_configured:true,passkeys:[],google_configured:false};
    else if(path==="/preferences"&&request.method()==="PUT"){Object.assign(preferences,JSON.parse(request.postData()||"{}"));body=preferences;}
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
    ["profile","Profile"],["appearance","Appearance"],["notifications","Event preferences"],["chat","Chat preferences"],["data","Privacy & data"],
  ];
  for(const width of [1505,393,320]){
    await page.setViewportSize({width,height:width>700?1045:852});
    for(const [section,heading] of pages){
      if(width<=700)await page.evaluate(value=>renderSettings(value),section);
      else await page.locator(`[data-settings-section="${section}"]`).click();
      await page.waitForFunction(text=>document.querySelector("#moduleBody")?.innerText.includes(text),heading);
      const dimensions=await page.evaluate(()=>({scrollWidth:document.documentElement.scrollWidth,innerWidth,bodyWidth:document.body.scrollWidth}));
      assert.ok(dimensions.scrollWidth<=dimensions.innerWidth+1,`${section} overflows at ${width}px: ${JSON.stringify(dimensions)}`);
      if(width===1505)await page.screenshot({path:`artifacts/settings-${section}-desktop.png`,fullPage:true});
      if(width===393)await page.screenshot({path:`artifacts/settings-${section}-mobile.png`,fullPage:true});
      await page.evaluate(()=>renderSettingsIndex());
    }
  }
  assert.deepEqual(errors,[],"Settings screens must not create uncaught browser errors");
  console.log("Responsive Settings preview passed: Profile, Appearance, Notifications, Chat preferences, and Privacy & data at 1505px, 393px, and 320px.");
} finally { await browser.close(); }
