import { chromium, type FullConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

// 全局 setup：登录一次并保存 storageState，所有测试复用（避免触发平台登录限流）
export default async function globalSetup(_config: FullConfig) {
  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  const authFile = path.join(__dirname, ".auth", "user.json");
  fs.mkdirSync(path.dirname(authFile), { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5000";
  await page.goto(baseURL + "/login", { waitUntil: "domcontentloaded" });
  await page.getByLabel(/用户名/).fill(process.env.E2E_ADMIN_USER ?? "admin");
  await page.getByLabel(/密码/).fill(process.env.E2E_ADMIN_PASS ?? "admin123");
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL(/^(?!.*\/login)/, { timeout: 20000 }).catch(async () => {
    // 登录页可能因限流偶发失败：重试一次
    await page.getByRole("button", { name: "登录" }).click();
    await page.waitForURL(/^(?!.*\/login)/, { timeout: 20000 });
  });
  await page.context().storageState({ path: authFile });
  // refresh token 存 sessionStorage（前端安全策略），Playwright storageState 不支持
  // sessionStorage → 单独导出，测试用 addInitScript 注入
  const refresh = await page.evaluate(() => sessionStorage.getItem("aigc-refresh-token"));
  fs.writeFileSync(path.join(__dirname, ".auth", "refresh.txt"), refresh ?? "");
  await browser.close();
}
