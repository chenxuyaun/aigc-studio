import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

// 核心业务模块 GUI 测试：站点壳导航 / ASMR 库 / 角色扮演 / 故事项目 / Studio 引擎 / Agent 库 / 知识库 / 任务中心。
// 登录态由 global-setup.ts 一次性准备（storageState 复用，避免触发登录限流）。
// refresh token 在 localStorage（auth.ts REFRESH_KEY）；storageState 固化旧值会过期，
// → beforeEach 用最新登录值覆盖注入（仅无值时注入，避免覆盖页面自己轮换的新值）。
// ⚠️ 本地库为空库（数据已迁服务器，本地 0 行真实数据）：本批断言以
//    「页面真实渲染 + 关键控件 + 空态」为准，不依赖本地业务数据。
// 运行：E2E_BASE_URL=http://127.0.0.1:5000 npx playwright test e2e/core-modules.spec.ts --project=chromium-desktop --workers=1

const refreshToken = (() => {
  try {
    const __dirname = path.dirname(fileURLToPath(import.meta.url));
    return fs.readFileSync(path.join(__dirname, ".auth", "refresh.txt"), "utf-8").trim();
  } catch {
    return "";
  }
})();

const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5000";
// API 请求必须打到 origin（/api 由 nginx 反代，不经过 SPA basename）
const apiBaseURL = new URL(baseURL).origin;
const adminUser = process.env.E2E_ADMIN_USER ?? "admin";
const adminPass = process.env.E2E_ADMIN_PASS ?? "admin123";

let latestRefresh = refreshToken;
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
    /* 登录失败时退回静态 token，后续用例会如实失败 */
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

test.describe("核心业务模块 GUI", () => {
  test("站点壳：四场所胶囊导航渲染（v11）", async ({ page }) => {
    await page.goto(baseURL + "/saios", { waitUntil: "domcontentloaded" });
    const nav = page.getByRole("navigation", { name: "场所" });
    await expect(nav.getByRole("link", { name: "派活中枢" })).toBeVisible({ timeout: 20000 });
    await expect(nav.getByRole("link", { name: "创作工坊" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "资产藏馆" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "角色宇宙" })).toBeVisible();
    // 系统组收进「更多」
    await expect(page.getByRole("button", { name: "更多" })).toBeVisible();
  });

  test("ASMR 库：页面渲染 + 搜索入口", async ({ page }) => {
    await page.goto(baseURL + "/saios/asmr", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "ASMR 库" })).toBeVisible({ timeout: 20000 });
    // 搜索入口 + 聚合统计（本地空库：聚合 0 部 · 本地保存）
    await expect(page.getByPlaceholder(/搜索标题 \/ 社团 \/ 声优/)).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(/聚合 \d+ 部/)).toBeVisible({ timeout: 15000 });
    await page.screenshot({ path: "gui-test-screenshots/g1_asmr.png" });
  });

  test("角色扮演：页面渲染 + 角色卡面板", async ({ page }) => {
    await page.goto(baseURL + "/saios/roleplay", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "角色扮演" })).toBeVisible({ timeout: 20000 });
    // 角色卡面板与「生成新卡」入口（空库仍有新卡路径）
    await expect(page.getByRole("link", { name: "生成新卡" })).toBeVisible({ timeout: 15000 });
    await expect(page.getByRole("checkbox", { name: /群聊模式/ })).toBeVisible();
    await page.screenshot({ path: "gui-test-screenshots/g2_roleplay.png" });
  });

  test("故事项目：空态 + 新建入口（本地空库）", async ({ page }) => {
    await page.goto(baseURL + "/saios/story", { waitUntil: "domcontentloaded" });
    // 创作工作室：标题 + 新建按钮 + 空态文案
    await expect(page.getByRole("heading", { name: "创作工作室" })).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("button", { name: /新建.*创作项目/ })).toBeVisible({ timeout: 15000 });
    await expect(page.getByText(/还没有创作项目/)).toBeVisible({ timeout: 15000 });
    await page.screenshot({ path: "gui-test-screenshots/g3_story.png" });
  });

  test("创作工坊 Studio：图像引擎入口（/create/image 收编）", async ({ page }) => {
    // v11 起 /create/* 收敛为 Studio 驾驶舱：断言驾驶舱图像&漫画引擎
    await page.goto(baseURL + "/saios/create/image", { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/SAIOS STUDIO/)).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("button", { name: /图像&漫画/ })).toBeVisible({ timeout: 15000 });
    await page.screenshot({ path: "gui-test-screenshots/g4_studio.png" });
  });

  test("Agent 库：页面渲染 + 描述", async ({ page }) => {
    await page.goto(baseURL + "/saios/agents", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Agent 库" })).toBeVisible({ timeout: 20000 });
    // 空库时仍有管理说明；搜索入口常驻（stats 有数据时展示）
    await expect(page.getByText(/管理可复用的 AI Agent/)).toBeVisible({ timeout: 15000 });
    await page.screenshot({ path: "gui-test-screenshots/g5_agents.png" });
  });

  test("知识库：页面渲染 + RAG 说明", async ({ page }) => {
    await page.goto(baseURL + "/saios/knowledge", { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("heading", { name: "知识库", exact: true }),
    ).toBeVisible({ timeout: 20000 });
    // 空库引导（RAG 说明文案）
    await expect(page.getByText(/RAG/).first()).toBeVisible({ timeout: 15000 });
    await page.screenshot({ path: "gui-test-screenshots/g6_knowledge.png" });
  });

  test("任务中心：历史任务列表加载", async ({ page }) => {
    await page.goto(baseURL + "/saios/tasks", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "任务中心" })).toBeVisible({ timeout: 20000 });
    // 有历史任务记录（本地有生成任务数据时）或空态；至少有一个可读行
    await expect(page.locator("main").getByText(/生成|任务/).first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("视频引擎：/create/video 收敛 Studio 驾驶舱", async ({ page }) => {
    await page.goto(baseURL + "/saios/create/video", { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/SAIOS STUDIO/)).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("button", { name: /视频引擎/ })).toBeVisible({ timeout: 15000 });
  });

  test("语音引擎：/create/audio 收敛 Studio 语音合成", async ({ page }) => {
    await page.goto(baseURL + "/saios/create/audio", { waitUntil: "domcontentloaded" });
    await expect(page.getByText(/SAIOS STUDIO/)).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("button", { name: /合成语音/ })).toBeVisible({ timeout: 15000 });
  });

  test("文本生成已下线：/create/text 归首页", async ({ page }) => {
    // TextGen 下线（AGENTS.md）：/create/text → /，与导航「派活中枢」合流
    await page.goto(baseURL + "/saios/create/text", { waitUntil: "domcontentloaded" });
    await expect(page.url()).toContain("/saios");
    await expect(page.getByRole("button", { name: /开启新创作对话/ })).toBeVisible({ timeout: 20000 });
  });
});