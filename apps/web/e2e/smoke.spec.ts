import { expect, test, type Page } from "@playwright/test";

// 核心冒烟：登录 → 工作台 → 画廊 → 图片生成闭环 → 素材库。
// 运行：E2E_BASE_URL=http://<host>:5000 pnpm --filter @aigc/web test:e2e

async function login(page: Page) {
  await page.goto("/login", { waitUntil: "networkidle" });
  await page.getByLabel(/用户名/).fill("admin");
  await page.getByLabel(/密码/).fill("admin123");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByText("你想创作什么？")).toBeVisible({ timeout: 15000 });
}

test("登录后进入创作首页", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("button", { name: /开始创作/ })).toBeVisible();
});

test("提示词库加载真实作品", async ({ page }) => {
  await login(page);
  await page.getByRole("link", { name: "提示词库" }).click();
  await expect(page).toHaveURL(/\/prompts$/);
  // 画廊至少渲染一张提示词卡片（无封面时显示占位而非 img）
  await expect(page.locator("figure").first()).toBeVisible({ timeout: 15000 });
  // 分类 chip
  await expect(page.getByRole("button", { name: "全部" })).toBeVisible();
});

test("图片生成闭环：创建任务→出图", async ({ page }) => {
  await login(page);
  await page.goto("/create/image", { waitUntil: "networkidle" });
  await page.getByPlaceholder(/参考人物气质/).fill("e2e smoke test cat");
  await page.getByRole("button", { name: /生成图片/ }).click();
  // 任务完成后结果区出现图片
  await expect(page.getByAltText(/生成结果/)).toBeVisible({ timeout: 25000 });
});

test("素材库直接访问不 404/403", async ({ page }) => {
  await login(page);
  await page.goto("/assets", { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { name: "素材库" })).toBeVisible();
});

test("模板变量表单：填写变量后带入创作页", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await login(page);
  await page.goto("/prompts", { waitUntil: "networkidle" });
  // 画廊 86% 的提示词带变量；搜索命中模板卡片
  await page.getByPlaceholder(/搜索提示词…/).fill("火车摄影");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/q=/);
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
  await login(page);
  await page.getByRole("link", { name: /提示词/ }).first().click();
  await expect(page).toHaveURL(/\/prompts$/);
  await page.getByRole("button", { name: "更多" }).click();
  await page.getByRole("link", { name: "素材库" }).click();
  await expect(page.getByRole("heading", { name: "素材库" })).toBeVisible();
});
