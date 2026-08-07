# 漫画更进一步（方案 C）设计文档

> 日期：2026-08-02
> 状态：已批准（用户选择方案 C）
> 前置：漫画功能增强已完成（气泡 + edits 降级 + 角色注入），见 `docs/comic-generation.md`

## 背景与目标

漫画当前最大短板：跨格角色一致性只有"文字级"（用户手写 characters 注入），
因为账号池无 image_edit 能力。本设计用 **chat vision 生成视觉角色卡** 实现
不需要 edit 账号的强一致性；同时补齐封面页与条漫布局，提升漫画成品的完整度。

## 1. 视觉角色卡（一致性核心）

### 流程
```
panel1 文生图成功
  → grok-chat-fast vision 看图
  → 结构化角色卡 JSON
  → 注入 panel2+ 图片 prompt
```

### 实现
- `comic_service._describe_character(image_bytes) -> str | None`：
  - POST `{IMAGE_BASE}/chat/completions`，模型 `grok-chat-fast`
  - messages: `[{role: user, content: [{type: text, text: 指令}, {type: image_url, image_url: {url: data_uri}}]}]`
  - 指令要求输出 JSON 角色卡：`{appearance, clothing, hair, eyes, accessories}`
  - 宽松解析（复用 `_chat_json` 思路），失败返回 None
- `generate_panels` 增强：首格成功后先调 `_describe_character`，后续格
  img_prompt 追加 `，角色形象：<角色卡>（保持此形象完全一致）`
- 优先级：vision 角色卡 > 用户 characters > 无
- 失败兜底：vision 返回 None → 回落现有 characters 注入逻辑
- 每任务仅 1 次 vision 调用

### 关键未知项
grok2api v3.0.11 的 chat vision 请求格式（OpenAI `image_url` 块）需先实测：
- 二进制已确认含 `image_url` 内容块字符串（探索报告）
- 实现第一步：手动 curl 实测一次 vision 调用，确认格式可用后写代码

## 2. 封面页（单独资产）

### 标题
- 分镜 system prompt 扩展：JSON 顶层加 `title`（漫画标题，中文，简短）
- `generate_storyboard` 返回 `ComicStory(title, panels)`（新 dataclass）
- title 宽松解析，取不到用主题截断（前 20 字）兜底

### 封面图
- 单独文生图：`电影海报构图，标题《{title}》，{style}，{角色卡/characters}，主体角色居中`
- 失败 → 用 panel1 图作封面图兜底（仍可合成封面页）

### 封面页合成
- 新函数 `compose_cover_page(cover_img: bytes, title: str, subtitle: str) -> bytes`
- PIL 竖版画布 768x1024：封面图占上部（等比缩放），底部深色条 + 标题大字
  （Noto CJK，字号 ~56，居中，自动换行）+ 副标题（主题，字号 ~24，灰色）
- 无中文字体时跳过文字（仅图 + 深色条，不崩溃）

### 资产
- 任务产出两个资产：封面页 `comic-{id}-cover.jpg` + 内容页（原主资产）
- result.comic 扩展：`title`、`cover`（{asset_id, url}）

## 3. 条漫布局

- `ComicGenerationRequest` 加 `layout: str = "grid"`（grid | manga）
- `compose_comic_page` 支持两种布局：
  - grid：现有 PANEL_GRID 网格（2x2 / 3x2 / 3x3）
  - manga：单列，统一宽度 `MANGA_WIDTH = 600`，每格等比缩放（宽 600 高自适应），
    格间 GAP，页面宽 = 600 + 2*GAP，高 = 各格高累加 + 格间距；气泡绘制不变
- 前端 ComicGenPage：布局选择器（网格/条漫 2 个 pill），请求体带 layout

## 4. 数据流（改动点）

| 文件 | 改动 |
|---|---|
| `apps/api/app/services/comic_service.py` | `ComicStory` dataclass；storyboard 产 title；`_describe_character`（vision）；`generate_panels` 注入角色卡；`compose_cover_page` 新函数；`compose_comic_page` 支持 manga 布局 |
| `apps/api/app/services/task_runner.py` | comic 分支：拆 title/panels、插 vision、封面图 + 封面页合成、双资产保存（cover + 内容页），result.comic 加 title/cover |
| `apps/api/app/schemas/generation.py` | `ComicGenerationRequest` 加 `layout` |
| `apps/web/src/pages/ComicGenPage.tsx` | 布局选择器；封面页展示 + 下载；标题展示 |
| `apps/api/tests/test_comic_service.py` | 新增测试（见下） |

## 5. 测试

- storyboard title 解析（含缺失兜底 → 主题截断）
- vision 角色卡注入（mock chat vision 响应 → 断言后续格 prompt 含角色卡）+ vision 失败回退 characters
- compose_cover_page（标题文字渲染、尺寸 768x1024、无字体不崩）
- compose_comic_page manga 布局（单列、宽统一 600、高累加、气泡仍在）
- 现有 10 测试保持

## 6. 验证

- 后端：ruff + mypy + pytest 全绿
- 真实 E2E：1 个 4 格任务（含 layout=manga），验证：
  - vision 角色卡真实可用性（关键未知项）
  - 封面页资产（标题渲染）
  - 条漫页像素验证（单列布局 + 气泡）
- 部署：`docker compose build api` + recreate api worker

## 边界（本次不做）

- 对白多气泡堆叠（现有 3 行内显示够用）
- 角色一致性仍非像素级（vision 描述是当前账号能力下的最优解）
- 封面不生成角色插画特写（海报 prompt 合成即可）
- 不做布局记忆/用户偏好持久化
