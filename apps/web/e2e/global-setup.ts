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
  await page.goto(baseURL + "/saios/login", { waitUntil: "domcontentloaded" });
  await page.getByPlaceholder(/输入系统账户名称/).fill(process.env.E2E_ADMIN_USER ?? "admin");
  await page.getByPlaceholder(/输入访问密码/).fill(process.env.E2E_ADMIN_PASS ?? "admin123");
  await page.getByRole("button", { name: /登录创作中枢/ }).click();
  await page.waitForURL(/^(?!.*\/login)/, { timeout: 20000 }).catch(async () => {
    // 登录页可能因限流偶发失败：重试一次
    await page.getByRole("button", { name: /登录创作中枢/ }).click();
    await page.waitForURL(/^(?!.*\/login)/, { timeout: 20000 });
  });
  await page.context().storageState({ path: authFile });
  // refresh token 是轮换制：storageState 若固化旧值，后续测试的 localStorage 里永远
  // 有旧 token，beforeEach 的「仅无值注入」就注入不进最新值 → 第二个测试起 401 跳登录。
  // → 从 storageState 删掉 refresh token（保留 user/角色态），让 beforeEach 注入最新值；
  //   同时单独导出 refresh.txt 作为 API 不可用时兜底。
  const refresh = await page.evaluate(() => localStorage.getItem("aigc-refresh-token"));
  fs.writeFileSync(path.join(__dirname, ".auth", "refresh.txt"), refresh ?? "");
  const state = JSON.parse(fs.readFileSync(authFile, "utf-8"));
  for (const origin of state.origins ?? []) {
    origin.localStorage = (origin.localStorage ?? []).filter(
      (item: { name: string }) => item.name !== "aigc-refresh-token",
    );
  }
  fs.writeFileSync(authFile, JSON.stringify(state, null, 2));
  await browser.close();
}
