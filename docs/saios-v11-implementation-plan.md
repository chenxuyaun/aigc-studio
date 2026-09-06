# saiOS v11「极简心流」落地规划

> 输入：设计老师回稿 `saios_v11_0.html`（v11.0 极简心流版）+ 现状 v3（五场所）。
> 目标：不重写 39 个页面，用「设计令牌 + 导航壳 + 场景包装」三层把全站收敛到设计稿口径，
> 功能零丢失、路由零破坏、真链不动。
> 版本：2026-09-05 ｜ 状态：规划稿，待动工。

---

## 一、设计稿解读（v11 到底是什么）

v11 是「东方极简心流」版：宣纸白/玄墨黑双主题、青瓷+朱砂点缀、Noto Serif SC 衬线排版、
**顶栏四场所胶囊导航**（派活中枢/创作工坊/资产藏馆/角色宇宙）+ 移动端底部 Dock。

与现状 v3 的关键差异（不是功能差异，是**呈现与入口**差异）：

| 维度 | v3（现状） | v11（设计稿） |
|---|---|---|
| 导航 | 左侧 228px 侧栏 + 顶栏搜索 | 顶栏居中胶囊四键，无侧栏 |
| 场所数 | 5（含系统组 adminOnly） | 4（系统功能去向 = 收进「更多/设置」或省略） |
| 首页 | AI 对话（会话流） | 派活中枢（初始命题/作品回显双态，大输入框居中） |
| 语言 | 技术黑话（引擎/任务/资产） | 心流白话（派活/出卷/藏馆/题跋钤印） |
| 形制 | 直角卡片、渐变高饱和 | 大圆角、纸感阴影、大面积留白、衬线题跋 |

**设计稿里是静态示意（SVG 假作品/假音频），落地时全部换成真实 API 产物。**

---

## 二、总路线：三层接入，功能一行不改

```
L1 设计令牌层——把 v11 色板/字体/圆角/阴影注入现有 @theme
    → 全站 39 页面自动换肤（现有 class 全部兼容，只改变量值）

L2 导航壳层——AppShell 从「侧栏+顶搜索」改「v11 顶栏胶囊四键+移动底栏」
    → 系统组/搜索/用户/主题收进右上角「更多」抽屉，路由不变

L3 场景包装层——四个场所各套 v11 场景壳（场所头 + 内容区）
    → 派活中枢(/) = 类设计稿 hub 页；工坊(/studio) / 藏馆(/library/*) / 宇宙(/roleplay)
    → 各场所在「现有页面组件上下文里做顶层容器重构」，组件内部不重写
```

这样 P0（令牌+壳）阶段不动任何页面逻辑即可肉眼变脸；P1-P3 逐个场所提质。

---

## 三、场所映射（v11 4 场所 ←→ 现有路由）

| v11 场所 | 设计稿 id | 落点（现有路由） | 现有组件 | 动作 |
|---|---|---|---|---|
| 派活中枢 | venue-hub | `/` | AssistantHomePage (2091 行) | 重做 hub 双态容器，会话流保留为「对话模式」，输入框居中化 |
| 创作工坊 | venue-studio | `/studio` | StudioPage (1094 行) | 保留五域引擎，改标题栏 + 「导出 PDF」实装（storyboard 已有） |
| 资产藏馆 | venue-library | `/library/:tab` | LibraryPage（10 tab 壳） | 改 tab 置顶胶囊样式 + 网格化卡片；文献/相册/灵感预览页保持 |
| 角色宇宙 | venue-universe | `/roleplay` | RoleplayPage (836 行) + PersonaPage | 保留会话+卡/世界书/记忆 tab，桌面端左右分栏结构对齐设计稿 |
| （系统兜底） | — | `/dashboard` `/settings/*` | DashboardPage 等 | 不进主导航；右上「更多」菜单 + 深链直达（adminOnly 保留） |

**休眠/深链页不动但全部保持可达**：/story /storyboard /workflows /team /search /growth /persona
（这些有直达路由；组件内部 v11 化属于 P4 可选，先保开门）。

Routes.tsx **零删除**：只有 `/` 指向新 hub 容器；其余路由全部原样。

---

## 四、分阶段实施

### P0 —— 设计令牌 + 导航壳（1 天，全站变脸）

**P0.1 令牌（`apps/web/src/styles/index.css`）**
- `@theme` 新增 v11 色版：`--color-background: #F9F8F6`（宣纸）、`--color-ink: #141518`、
  `--color-surface: #FFFFFF`、`--color-celadon: #2F6359`/`#448275`（朱砂 seal 或
  `--color-seal: #A82E35`/`#C23B43`）；深色换 night 色板 `#111215/#1A1C20/#22252A`。
- 不动现有语义名（`--color-background/primary/...`）——直接把**现值换成 v11 色值**，现有组件自动变脸。
  – 现有 SKINS（cyan/purple/emerald/mono）保留为「皮肤」选项，默认设为 v11 色系（celadon 属 emerald 近邻，可新增 `zen` skin 直给）。
- 字体栈：`--font-display` 试验 Noto Serif SC 中文衬线（现有 Fraunces 拉丁 + 中文回退，微调即可）。
- 圆角：`--radius-card` 18→20/22，`--radius-button` 12→14，卡片阴影换 paper 感 `box-shadow`。

**1.2 导航壳（`src/components/layout/AppShell.tsx`）**
- `NAV_GROUPS` 改 4 项：派活中枢(/) 创作工坊(/studio) 资产藏馆(/library/works) 角色宇宙(/roleplay)。
- 桌面：去掉左侧 228px 栏 → 顶栏中间一枚胶囊四键（`md:flex`），右侧 = 主题/更多/头像。
- 移动：底部 dock 四键（已有，改 label/icon 按 v11）。
- 系统组（看板/模型/用户/日志）收进右上角「⚙️ 更多」下拉；search 保留顶栏放大镜按钮（点击展开与现状同交互）。
- 兼容 `compact` host 模式不受影响（`{!compact && …}` 已有）。

**P0 验收**：`npx tsc --noEmit` 绿；E2E smoke 5 用例绿；Chrome 截图对比设计稿四屏形制。

### P1 —— 派活中枢（1 天，hub 页重做，净化主入口）

`AssistantHomePage.tsx` 顶层改造（不重写 2091 行，只换容器）：
- 拆「双态」：空态（居中大输入框 + 能力卡）↔ 工作态（作品回显卡 + 追加微调 dock），对应设计稿
  `hub-state-empty / hub-state-active`；现有语料/会话列表/流式逻辑下沉为工作态内部。
- 输入框提到页面中线以上、两句话引导（设计稿「宋瓷天青釉色中的江南初春雨景…」占位愿照搬）。
- 生成按钮 = 「生成出卷」，回车/点击进工作态；卡片区 = 真实 media 回显（图片/音频/漫画封面）。

**P1 验收**：空态→出图→回显闭环 E2E；截图与设计稿 hub 高度一致。

### P2 —— 工坊 + 藏馆（3-4 天，两场所提质）

- **工坊**：StudioPage 标题换 `工坊`副标题；五域引擎卡改为大圆角斑纹；「导出 PDF」实装
  （storyboard 导出或简介页导出，选简版先做「大纲导出」）。
- **藏馆**：LibraryPage tab 条改 v11 风格（顶部胶囊过度 → 纸张 tab）；藏品卡网格、非对称
  （首卡大图）；相册/灵感/分享墙三个强视觉子页保持各自组件，只换 tab 壳样式。

**P2 验收**：/studio 与 /library/* 截图与设计稿签名牌一致；E2E 全部 tab 可用回归。

### P3 —— 角色宇宙 + 收尾（2-3 天）

- **宇宙**：RoleplayPage 桌面端整体左「角色卡/记忆/设置」右「对话」分栏（对应设计稿宇宙形态）；
  移动端保留 tab 模式。Persona 页链接「角色宇宙」入口。
- **收尾**：全站文案扫一眼（「任务」→「工序」可选做）；深链页一级标题统一 v11 字体；
  PWA 图标/标题同步；gallery/static 资源走根路径不拼前缀（既有规定）。nginx SPA 白名单无需变
  （无新路由）。

**P3 验收**：全量 E2E（14 14 或当前集）绿；生产服务器同步 + 公网 E2E 截图。

### 尾期（可选）
- 设计稿前进化：题跋钤印（作品末行自动生成）、主题复古字（v11 品牌要素）卡片化。
- story/team/workflows 深链页 v11 化（按浏览频率排队）。

---

## 五、风险与对策

| 风险 | 对策 |
|---|---|
| 令牌换色影响 39 页对比 | 语境颜色变量名不变只变值——旧组件仍「送变脸」；E2E 全量回归兜底（playwright 截图 diff 可选） |
| 删侧栏后「系统组」找不到 | 更多抽屉 + 深链书签；adminOnly 权限逻辑不动 |
| hub 重写伤及会话/持久化 | 工作态内保 `usePersistedChat`，若入只换容器不换状态流 |
| 「/persons 入口」需求原在侧栏 | 放进「更多」+ 宇宙场所首屏卡（角色可分跳转） |
| 设计稿演示资产（SVG/假 wav）被误当真 | 全部替换为真实 API 产物搬运路径（generation 字段 → card）——设计稿仅做视觉参照 |

## 附：v11 视觉令牌速查（从设计稿摘录）

```css
/* 设计稿 zen（浅） */
--zen-bg:      #F9F8F6;  /* 宣纸 */
--zen-surface: #FFFFFF;
--zen-surface-sub: #F3F2EE;
--zen-line:    rgba(0,0,0,.06);
--zen-ink:     #141518;  --zen-ink-sub: #60646C;
--zen-celadon: #2F6359;  --zen-seal: #A82E35;
/* night (深色) */
--night-bg: #111215; --night-surface: #1A1C20; --night-surface-sub: #22252A;
--night-line: rgba(255,255,255,.08); --night-ink: #F0F2F5; --night-ink-sub: #9197A3;
--night-celadon: #448275; --night-seal: #C23B43;
/* 字体 */
--font-serif: "Noto Serif SC"; --font-sans: "Plus Jakarta Sans", …; --font-mono: "JetBrains Mono";
/* 形制 */
--radius-2xl: 16px（卡片/输入框大圆角）; 阴影 paper: 0 12px 32px -8px rgba(0,0,0,.06)+内高光;
滚动条 4px 细窄；移动 dock 底部悬浮圆角条。
```