import { chromium } from "playwright";
import { fileURLToPath } from "url";
import path from "path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const q = new URLSearchParams({
  access: "pc_photo_vieweditor",
  position: "image_topright_upgrade_button",
  paid_features: "image_premium",
  module: "photo",
  sub_module: "pc_photo_vieweditor",
  component: "photo",
  feature: "wps",
  version: "12.1.0.25242",
  distsrc: "119.119",
  lang: "en-US",
  tzone_offset: "28800000",
  country: "CN",
  disableGlobalInfoCollect: "false",
  frame: "client",
  supportTemplateVip: "1",
  update_min_version: "201905",
  firstOpen: "0",
  loginRetentionPlan: "b",
  premiumcode: "1",
  product_version: "2019",
  app_type: "wps_pc_2019",
  ai_support: "1",
});
const url = `http://127.0.0.1:8765/index.html#/v3?${q.toString()}`;
const shot = path.join(__dirname, "_payment_offline_photo.png");

const browser = await chromium.launch({
  channel: "msedge",
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const logs = [];
const errs = [];
page.on("console", (msg) => logs.push(`[${msg.type()}] ${msg.text()}`));
page.on("pageerror", (e) => errs.push(String(e.message)));

await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(5000);
await page.screenshot({ path: shot, fullPage: true });
console.log("URL:", url);
console.log("Screenshot:", shot);
console.log("--- console (last 30) ---");
console.log(logs.slice(-30).join("\n") || "(none)");
console.log("--- page errors ---");
console.log(errs.join("\n") || "(none)");
console.log("--- title ---", await page.title());
await browser.close();
