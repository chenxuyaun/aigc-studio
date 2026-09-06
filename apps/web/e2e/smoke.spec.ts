import { expect, test, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

// 核心冒烟：登录 → 工作台 → 画廊 → 图片生成闭环 → 素材库。
// 运行：E2E_BASE_URL=http://<host>:5000 pnpm --filter @aigc/web test:e2e
// 登录态由 global-setup 准备（storageState + localStorage refresh 注入），
// login() 幂等：已登录直接返回，避免每个用例真实登录触发限流。

const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5000";
// API 请求必须打到 origin（/api 由 nginx 反代，不经过 SPA basename）
const apiBaseURL = new URL(baseURL).origin;
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
    const res = await fetch(`${apiBaseURL}/api/v1/auth/login`, {
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
      // refresh token 是轮换制（刷新一次旧值即作废）：只在「无值」时注入，
      // 页面刷新后自行更新 localStorage 的版本绝不能被我方旧值覆盖。
      if (rt && !localStorage.getItem("aigc-refresh-token")) localStorage.setItem("aigc-refresh-token", rt);
    },
    latestRefresh,
  );
});

// 登录态由 storageState + refresh 注入保证（global-setup 已走真实登录表单）。
// v11 壳：顶栏胶囊四键（派活中枢/创作工坊/资产藏馆/角色宇宙）是登录后的标志
// （未登录会被重定向到 /login，页面上不存在该胶囊链接）
async function ensureAuth(page: Page) {
  await page.goto(baseURL + "/saios", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("link", { name: /派活中枢/ }).first()).toBeVisible({ timeout: 20000 });
}

test("登录态恢复后进入创作首页", async ({ page }) => {
  await ensureAuth(page);
  // 派活中枢首页 = 对话式创作台（欢迎态输入框）
  await expect(page.getByPlaceholder(/输入.*选择能力/).first()).toBeVisible({ timeout: 20000 });
});

test("派活中枢：v11 初态命题桌面 + 双态模式切换", async ({ page }) => {
  await page.goto(baseURL + "/saios", { waitUntil: "domcontentloaded" });
  // 初态命题：禅意桌面（衬线大标题 + 命题输入卡 + 生成出卷按钮）
  await expect(page.getByRole("heading", { name: /派活给 saiOS/ })).toBeVisible({ timeout: 20000 });
  await expect(page.getByPlaceholder(/用一句话创作/)).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("button", { name: /生成出卷/ })).toBeVisible();
  // 双态切换（顶部系统栏）：初态命题 选中 / 作品回显 未选中
  const tabs = page.getByRole("tablist", { name: "心流模式" });
  await expect(tabs).toBeVisible({ timeout: 15000 });
  await expect(tabs.getByRole("tab", { name: "初态命题" })).toHaveAttribute("aria-selected", "true");
  await expect(tabs.getByRole("tab", { name: "作品回显" })).toHaveAttribute("aria-selected", "false");
});

test("提示词库加载真实作品", async ({ page }) => {
  await page.goto(baseURL + "/saios/prompts", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "提示词库" })).toBeVisible({ timeout: 20000 });
  // 画廊至少渲染一张提示词卡片（无封面时显示占位而非 img）
  await expect(page.locator("figure").first()).toBeVisible({ timeout: 15000 });
  // 分类 chip（exact 匹配：顶栏「开启新创作对话」旁的"搜索全部"也含"全部"二字）
  await expect(page.getByRole("button", { name: "全部", exact: true }).first()).toBeVisible();
});

// 重测试（真实 AI 出图，可能耗时 60s+）：默认套件排除（--grep-invert @heavy），
// 需要时单独跑：--grep "@heavy"
test("图片生成闭环：创建任务→出图", { tag: "@heavy" }, async ({ page }) => {
  await page.goto(baseURL + "/saios/create/image", { waitUntil: "domcontentloaded" });
  await page.getByPlaceholder(/参考人物气质/).fill("e2e smoke test cat");
  await page.getByRole("button", { name: /生成图片/ }).click();
  // 任务完成后结果区出现图片
  await expect(page.getByAltText(/生成结果/)).toBeVisible({ timeout: 60000 });
});

test("素材库直接访问不 404/403", async ({ page }) => {
  await page.goto(baseURL + "/saios/assets", { waitUntil: "domcontentloaded" });
  await expect(
    page.getByRole("heading", { name: "素材库", exact: true }).first(),
  ).toBeVisible({ timeout: 20000 });
});

test("模板变量表单：填写变量后带入创作页", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  // 本地库可能无变量模板：测试前自建一条带变量的公开提示词，用后删除（不依赖数据环境）
  const loginRes = await fetch(`${apiBaseURL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: adminUser, password: adminPass }),
  });
  const accessToken = ((await loginRes.json()) as { access_token?: string }).access_token ?? "";
  const TITLE = `E2E 变量模板 ${Date.now()}`;
  const CONTENT = '火车摄影 {argument name="主体" default="蒸汽机车"} 与 {argument name="场景" default="雪原"}';
  let createdId = "";
  if (accessToken) {
    const created = await fetch(`${apiBaseURL}/api/v1/prompts/`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ title: TITLE, content: CONTENT, is_public: true, prompt_type: "image" }),
    });
    if (created.ok) {
      const data = (await created.json()) as { id?: string };
      createdId = data.id ?? "";
    }
  }
  try {
    await page.goto(baseURL + "/saios/prompts", { waitUntil: "domcontentloaded" });
    // 页面真正渲染完（heading 出现）再操作，避免偶发慢渲染
    await expect(page.getByRole("heading", { name: "提示词库" })).toBeVisible({ timeout: 30000 });
    // 搜索刚刚创建的模板卡片（标题唯一，前端状态式搜索，URL 不变，轮询结果区）
    await page.getByPlaceholder(/搜索提示词/).fill(TITLE);
    await page.keyboard.press("Enter");
    const card = page.locator("figure", { hasText: TITLE }).first();
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
    // 用于创作 → v11 创作工坊 Studio 的图像域（/create/* 已收编驾驶舱）带上替换后的提示词
    await page.getByRole("button", { name: /用于创作/ }).click();
    await expect(
      page.getByRole("textbox", { name: /描述你想生成的画面/ }),
    ).toHaveValue(clipboard, { timeout: 15000 });
  } finally {
    if (createdId && accessToken) {
      await fetch(`${apiBaseURL}/api/v1/prompts/${createdId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${accessToken}` },
      }).catch(() => {});
    }
  }
});

// 移动端：底部导航 = v11 四场所 + 「更多」；藏馆收纳全部资产 tab
test("移动端底部导航四场所 + 更多抽屉", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 667 });
  await page.goto(baseURL + "/saios", { waitUntil: "domcontentloaded" });
  // 登录态恢复后底部导航出现（四场所胶囊）
  await expect(page.getByRole("link", { name: /派活/ }).first()).toBeVisible({ timeout: 20000 });
  // 点「藏馆」进入资产库 tab（默认作品）
  await page.getByRole("link", { name: /藏馆/ }).first().click();
  await expect(page).toHaveURL(/\/library\/works/, { timeout: 15000 });
  // 「更多」抽屉含系统管理项
  await page.getByRole("button", { name: "更多" }).click();
  await expect(page.getByRole("link", { name: "系统看板" })).toBeVisible({ timeout: 10000 });
});
