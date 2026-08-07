import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

// 核心冒烟：登录 → 工作台 → 画廊 → 图片生成闭环 → 素材库。
// 运行：E2E_BASE_URL=http://<host>:5000 pnpm --filter @aigc/web test:e2e
// 登录态由 global-setup 准备（storageState + sessionStorage refresh 注入），
// login() 幂等：已登录直接返回，避免每个用例真实登录触发限流。

const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5000";
const adminUser = process.env.E2E_ADMIN_USER ?? "admin";
const adminPass = process.env.E2E_ADMIN_PASS ?? "admin123";

let latestRefresh = (() => {
  try {
    const __dirname = path.dirname(fileURLToPath(import.meta.url));
    return fs.readFileSync(path.join(__dirname, ".auth", "refresh.txt"), "utf-8").trim();
  } catch {
    return "";
  }
})();

// refresh token 每次静默换新都会轮换 → 每个测试前用 API 登录拿最新值注入
test.beforeEach(async ({ context }) => {
  try {
    const res = await fetch(`${baseURL}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: adminUser, password: adminPass }),
    });
    if (res.ok) {
      const data = (await res.json()) as { refresh_token?: string };
      if (data.refresh_token) latestRefresh = data.refresh_token;
    }
  } catch {
    /* 忽略：退回静态 token */
  }
  await context.addInitScript(
    (rt) => {
      if (rt) sessionStorage.setItem("aigc-refresh-token", rt);
    },
    latestRefresh,
  );
});

// 登录态由 storageState + refresh 注入保证（global-setup 已走真实登录表单），
// ensureAuth 等"退出登录"按钮出现（登录态真正的标志，静态文案不可靠），
// 避免测试间重复登录触发限流/竞态
async function ensureAuth(page: Page) {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible({ timeout: 20000 });
}

test("登录态恢复后进入创作首页", async ({ page }) => {
  await ensureAuth(page);
  await expect(page.getByRole("button", { name: /开始创作/ })).toBeVisible({ timeout: 20000 });
});

test("提示词库加载真实作品", async ({ page }) => {
  await page.goto("/prompts", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "提示词库" })).toBeVisible({ timeout: 20000 });
  // 画廊至少渲染一张提示词卡片（无封面时显示占位而非 img）
  await expect(page.locator("figure").first()).toBeVisible({ timeout: 15000 });
  // 分类 chip
  await expect(page.getByRole("button", { name: "全部" })).toBeVisible();
});

// 重测试（真实 AI 出图，可能耗时 60s+）：默认套件排除（--grep-invert @heavy），
// 需要时单独跑：--grep "@heavy"
test("图片生成闭环：创建任务→出图", { tag: "@heavy" }, async ({ page }) => {
  await page.goto("/create/image", { waitUntil: "domcontentloaded" });
  await page.getByPlaceholder(/参考人物气质/).fill("e2e smoke test cat");
  await page.getByRole("button", { name: /生成图片/ }).click();
  // 任务完成后结果区出现图片
  await expect(page.getByAltText(/生成结果/)).toBeVisible({ timeout: 60000 });
});

test("素材库直接访问不 404/403", async ({ page }) => {
  await page.goto("/assets", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "素材库" })).toBeVisible({ timeout: 20000 });
});

test("模板变量表单：填写变量后带入创作页", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/prompts", { waitUntil: "domcontentloaded" });
  // 页面真正渲染完（heading 出现）再操作，避免偶发慢渲染
  await expect(page.getByRole("heading", { name: "提示词库" })).toBeVisible({ timeout: 30000 });
  // 画廊 86% 的提示词带变量；搜索命中模板卡片
  await page.getByPlaceholder(/搜索提示词/).fill("火车摄影");
  await page.keyboard.press("Enter");
  // 搜索结果渲染（前端状态式搜索，URL 不变，轮询结果区）
  const card = page.locator("figure", { hasText: /变量 \d+/ }).first();
  await expect(card).toBeVisible({ timeout: 15000 });
  await card.getByRole("button", { name: /查看提示词/ }).click();
  // 变量表单出现
  await expect(page.getByText(/模板变量/)).toBeVisible();
  const firstInput = page.locator("[role=dialog] input").first();
  await firstInput.fill("太空站");
  // 复制按钮复制替换后的文本
  await page.getByRole("button", { name: "复制", exact: true }).click();
  const clipboard = await page.evaluate(() => navigator.clipboard.readText());
  expect(clipboard).toContain("太空站");
  expect(clipboard).not.toContain("{argument");
  // 用于创作 → 图片创作页带上替换后的提示词
  await page.getByRole("button", { name: /用于创作/ }).click();
  await expect(page.getByPlaceholder(/保持参考人物气质/)).toHaveValue(clipboard);
});

// 移动端：底部导航直达核心模块，「更多」抽屉覆盖素材库/Agent/技能/工作流
test("移动端底部导航直达提示词库与素材库", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  // 登录态恢复后底部导航出现
  await expect(page.getByRole("link", { name: /提示词/ }).first()).toBeVisible({ timeout: 20000 });
  await page.getByRole("link", { name: /提示词/ }).first().click();
  await expect(page).toHaveURL(/\/prompts$/);
  await page.getByRole("button", { name: "更多" }).click();
  await page.getByRole("link", { name: "素材库" }).click();
  await expect(page.getByRole("heading", { name: "素材库" })).toBeVisible();
});
