# 前端 UI 审计报告（2026-08-07）

> 范围：apps/web 全部 35 页 + AppShell + 组件库。方法：playwright 程序化 DOM 审计（浅色/深色）+ 静态扫描。当前模型不支持看图，截图已存 `.cowork-temp/ui-{light,dark}-*.png` 供人工复核。

## 总体结论

- ✅ **控制台零错误**：11 个抽样页浅色/深色均无 console error / pageerror（前几轮 CSP/401 修复稳固）
- ✅ **主题令牌生效**：深色模式无硬编码颜色残留（运行时扫描 prompts/asmr 等页 hardcoded 类 = 0）
- ✅ 无破损图片（登录页 1 张 R2 挂图已容错隐藏）
- 🔶 审计脚本曾报 prompts 96 / asmr 24 硬编码类，经运行时实测为**脚本选择器转义 bug 的误报**，实际为 0

## 发现的问题（按优先级）

1. **对比度不达标**：`--color-primary` #e8912a 在 `--color-background` #faf9f6 上约 2.9:1，低于 WCAG AA 正文 4.5:1。琥珀金只宜作大号标题/图形/强调色，正文链接/按钮文字需加深（建议 #c87818 或引入 `--color-primary-text`）。
2. **展示字体覆盖不全**：`font-display`（Fraunces）仅 Dashboard 标题使用（1/4 headings）；其余页面标题仍走系统字体。建议统一页面级 h1 用 `font-display`，数字统计一律 Fraunces。
3. **focus-visible 不一致**：Button/Input/Dialog 有 ring，但 Card/可点击 div/自定义按钮多处缺键盘焦点态（如 Dashboard 任务卡 onClick div、灵感图 button 有但部分 tab 无 focus 样式）。需全局 `.focus-ring` 工具类。
4. **Workflow 画布样式孤立**：`WorkflowCanvasEditor.tsx` 63KB 单文件 + `components/workflow/*`（SkillNode/PromptNode 含少量硬编码色）自成一系，未复用 Card/Button/Field 原语。重构候选（低风险拆组件 + 换原语）。
5. **登录页拼贴装饰图**：9 张 img alt=""（装饰图语义正确），建议补 `aria-hidden="true"` 减少读屏噪音（可选）。
6. **移动端「更多」抽屉**：3 列网格在 320px 下偏挤，管理项混排；建议分组两段式列表。
7. **深色轮次覆盖不全**：审计脚本在深色下半段导航时序异常（tasks/create/knowledge/workflows 拍到登录页），需在精修阶段重测这 4 页深色。
8. **空态/加载态不统一**：部分页面自绘 spinner/文案，未用 `States.tsx` 的 LoadingState/EmptyState/ErrorState（抽样：tasks 列表、story 章节列表有自绘）。

## 后续阶段（对齐 PLAN）

- 阶段 2：原语补齐——Select / Tabs / Tooltip / Skeleton 变体 / EmptyQuery；Field 支持组合
- 阶段 3：重点页应用——Dashboard/Prompts/Roleplay/Story/Generation/ASMR/Assets/Tasks/Workflows 统一 PageHeader、数字 font-display、Card hoverable、States 三件套
- 阶段 4：可访问性（对比度/focus/aria）+ 深色重测 + 视觉回归截图对比 + PROJECT_SUMMARY 更新
