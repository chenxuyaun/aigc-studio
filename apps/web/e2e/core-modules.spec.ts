import { expect, test } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

// 核心业务模块 GUI 测试：ASMR 搜索 / 角色对话 / 故事项目。
// 登录态由 global-setup.ts 一次性准备（storageState 复用，避免触发登录限流）。
// refresh token 在 sessionStorage（storageState 不支持）→ beforeEach 注入。
// 运行：E2E_BASE_URL=http://127.0.0.1:5000 E2E_ADMIN_USER=<user> E2E_ADMIN_PASS=<pass> pnpm --filter @aigc/web test:e2e

const refreshToken = (() => {
  try {
    const __dirname = path.dirname(fileURLToPath(import.meta.url));
    return fs.readFileSync(path.join(__dirname, ".auth", "refresh.txt"), "utf-8").trim();
  } catch {
    return "";
  }
})();

const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5000";
const adminUser = process.env.E2E_ADMIN_USER ?? "admin";
const adminPass = process.env.E2E_ADMIN_PASS ?? "admin123";

// refresh token 每次静默换新都会轮换（安全策略），静态注入一次会失效 →
// 每个测试前用 API 登录拿最新 refresh（登录限流 20/min，3-4 个测试无压力）
let latestRefresh = refreshToken;
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
    /* 登录失败时退回静态 token，后续用例会如实失败 */
  }
  await context.addInitScript(
    (rt) => {
      if (rt) sessionStorage.setItem("aigc-refresh-token", rt);
    },
    latestRefresh,
  );
});

test.describe("核心业务模块 GUI", () => {
  test("ASMR 库：列表加载 + 搜索命中 + 结果渲染", async ({ page }) => {
    await page.goto("/asmr", { waitUntil: "domcontentloaded" });
    // 列表加载：作品卡片 = main 内带 img 的 button
    await expect(page.locator("main button img").first()).toBeVisible({ timeout: 20000 });
    const before = await page.locator("main button img").count();
    // 搜索（用已渲染作品标题里的真实词，保证命中）
    await page.getByPlaceholder(/搜索标题 \/ 社团 \/ 声优/).fill("夢見");
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    // 结果区重新渲染（数量变化且仍有结果）
    await expect
      .poll(async () => page.locator("main button img").count(), { timeout: 15000 })
      .toBeGreaterThan(0);
    await expect
      .poll(async () => page.locator("main button img").count(), { timeout: 15000 })
      .not.toBe(before);
    await page.screenshot({ path: "gui-test-screenshots/g1_asmr_search.png" });
  });

  test("角色扮演：选角色卡 → 聊天输入 → 消息上屏", async ({ page }) => {
    await page.goto("/roleplay", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "角色扮演" })).toBeVisible({ timeout: 20000 });
    // 点击第一个角色卡（按钮名含 character-*.png）
    const charCard = page.locator("main").getByRole("button").filter({ hasText: /character-/ }).first();
    await charCard.click();
    const input = page.getByPlaceholder(/对角色说点什么/);
    await expect(input).toBeVisible({ timeout: 15000 });
    await expect(input).toBeEnabled({ timeout: 15000 });
    await input.fill("你好，测试一下");
    await input.press("Enter");
    await expect(page.getByText("你好，测试一下")).toBeVisible({ timeout: 15000 });
    await page.screenshot({ path: "gui-test-screenshots/g2_roleplay_chat.png" });
  });

  test("故事项目：列表加载 + 进入创作项目", async ({ page }) => {
    await page.goto("/story", { waitUntil: "domcontentloaded" });
    // 项目标题 heading（真实数据：双城交换杀人）
    const project = page.getByRole("heading", { name: "双城交换杀人", level: 3 });
    await expect(project).toBeVisible({ timeout: 20000 });
    // 进入创作 → 项目详情（编辑器/章节面板出现）
    await page.getByRole("button", { name: "进入创作", exact: true }).first().click();
    await expect(page).toHaveURL(/\/story\/[0-9a-f-]+/, { timeout: 15000 });
    await expect(page.getByText(/章|章节/).first()).toBeVisible({ timeout: 15000 });
    await page.screenshot({ path: "gui-test-screenshots/g3_story_project.png" });
  });

  test("图片生成：从提示词库选择并带入提示词", async ({ page }) => {
    await page.goto("/create/image", { waitUntil: "domcontentloaded" });
    await expect(page.getByPlaceholder(/保持参考人物气质|参考人物气质/)).toBeVisible({
      timeout: 20000,
    });
    // 打开提示词库选择器
    await page.getByRole("button", { name: "从提示词库选择" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 10000 });
    // 搜索并出现结果
    await dialog.getByPlaceholder(/搜索提示词/).fill("摄影");
    await dialog.getByRole("button", { name: "搜索", exact: true }).click();
    const firstItem = dialog.locator("button").filter({ hasText: /摄影/ }).first();
    await expect(firstItem).toBeVisible({ timeout: 15000 });
    const selectedText = (await firstItem.locator("p").first().textContent()) ?? "";
    await firstItem.click();
    // 提示词框被填充（内容非空）
    const textarea = page.getByPlaceholder(/保持参考人物气质|参考人物气质/);
    await expect(textarea).not.toHaveValue("", { timeout: 10000 });
    await page.screenshot({ path: "gui-test-screenshots/g4_prompt_picker.png" });
  });

  test("Agent 库：列表加载", async ({ page }) => {
    await page.goto("/agents", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Agent 库" })).toBeVisible({ timeout: 20000 });
    // 统计与搜索入口渲染（90 个 Agent 真实数据）
    await expect(page.getByText(/共 \d+ 个 Agent/)).toBeVisible({ timeout: 15000 });
    await expect(page.getByPlaceholder(/搜索 Agent/)).toBeVisible();
  });

  test("知识库：推理框架文档可见可检索", async ({ page }) => {
    await page.goto("/knowledge", { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("heading", { name: "知识库", exact: true }),
    ).toBeVisible({ timeout: 20000 });
    // 入库的推理框架文档出现在列表（可检索）
    await expect(page.getByText(/推理框架/).first()).toBeVisible({ timeout: 15000 });
  });

  test("任务中心：历史任务列表加载", async ({ page }) => {
    await page.goto("/tasks", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "任务中心" })).toBeVisible({ timeout: 20000 });
    // 有历史任务记录（本地有 200+ 条生成任务）
    await expect(page.locator("main").getByText(/生成|任务/).first()).toBeVisible({
      timeout: 15000,
    });
  });
});
