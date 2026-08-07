# 漫画生成功能说明

> 维护：2026-08-02（气泡 + 角色一致性增强 + 封面页 + 条漫布局）
> 入口：前端「创作 → 漫画生成」（`/create/comic`）

## 流程

```
用户输入（主题 + 格数 + 风格 + 角色设定 + 布局）
  → 分镜：cpa 文本模型（gpt-oss-120b-medium）生成 JSON 分镜
    {title: 漫画标题, panels: [{scene: 画面描述(中文绘画提示词), dialogue: 对白}]}
  → 出图：逐格调 grok2api（串行）
      · 首格成功后 chat vision 看图 → 视觉角色卡 → 注入后续格 prompt
      · 有 image_edit 账号时走 /v1/images/edits 图生图（自动降级）
  → 封面：海报文生图 + PIL 合成封面页（标题大字）
  → 拼合：PIL 网格（grid）/ 条漫（manga）+ 每格底部对白气泡 → JPEG
  → 资产：封面页 + 每格图 + 拼合页全部存入素材库
```

## 跨格角色一致性（三级策略）

1. **视觉角色卡（当前主路径）**：panel1 出图后用 `grok-chat-fast` vision
   看图 → 输出结构化角色卡（外貌/服装/发型/眼睛/配饰）→ 注入后续格 prompt
   （"角色形象：<角色卡>（保持此形象完全一致）"）。**不需要 image_edit 账号**，
   已实测可用（grok2api v3 支持 OpenAI `image_url` 块格式）。
2. **图生图（首选，需账号能力）**：参考图走 `POST /v1/images/edits`
   （模型 `grok-imagine-image-edit`）。当前账号池无 image_edit 能力
   （`available=false, accounts=0`）→ 自动降级；未来导入带 edit 能力的账号即自动生效。
3. **用户 characters 注入**：vision 失败时回退用户填写的角色设定。

## 封面页（2026-08-02 新增）

- 标题由分镜模型自动生成（JSON 顶层 `title`，缺失时主题截断兜底）
- 封面图：海报文生图（"电影海报构图，标题《X》，{style}，主体角色居中"），
  失败用首张成功 panel 兜底
- 合成：`compose_cover_page` 竖版 768x1024（封面图上部 + 标题大字 + 副标题）
- 独立资产：`comic-{id}-cover.jpg`，前端封面区展示

## 条漫布局（2026-08-02 新增）

- `layout: "grid" | "manga"`（默认 grid），前端布局选择器
- manga：单列宽 600，高度自适应，格间 GAP，气泡不变
- 实现：`compose_comic_page(..., layout="manga")` → `_compose_manga`

## 文字气泡

- 样式：格内底部居中白底圆角矩形 + 黑字 + 小尾三角，最多 3 行截断
- 中文字体：`fonts-noto-cjk`（Noto Sans CJK）打进 API 镜像
- **找不到字体时跳过气泡、不崩溃**

## 已知边界

- 拼合页不画角色名牌/场景标题（仅对白气泡）
- 角色一致性为视觉描述级（非像素级）—— 当前账号能力下的最优解
- 出图耗时：4 格约 2-4 分钟（串行 + vision 一次约 10s；风控期可能更长）
- 单格失败自动灰格占位，任务仍 succeeded

## 验证

```bash
# 单测（18 个：分镜/标题/气泡/封面/条漫/edits 降级/参考图链/vision 角色卡）
cd apps/api && .venv/Scripts/python.exe -m pytest tests/test_comic_service.py -q

# 真实 E2E
POST /api/v1/generations/comic/generate
  {"prompt":"...","panels":4,"style":"日式漫画","characters":"...","layout":"grid|manga","model":"grok-imagine-image"}
GET  /api/v1/tasks/{id}   # succeeded 后 result.comic = {title, cover, panels, assets, storyboard}
```

## 相关文件

| 路径 | 说明 |
|---|---|
| `apps/api/app/services/comic_service.py` | 分镜/标题/出图/角色卡/封面/拼合/气泡全链路 |
| `apps/api/app/services/task_runner.py` | comic 任务分支 + 封面/多资产保存 |
| `apps/api/tests/test_comic_service.py` | 18 个单测 |
| `apps/web/src/pages/ComicGenPage.tsx` | 前端表单（布局选择器）+ 封面/标题/结果展示 |
| `apps/api/Dockerfile` | `fonts-noto-cjk` 中文字体 |
| `docs/superpowers/specs/2026-08-02-comic-advanced-design.md` | 设计文档 |
| `docs/superpowers/plans/2026-08-02-comic-advanced.md` | 实施计划 |

> 部署提醒：改动代码后必须 `docker compose build api` 再 `up -d --force-recreate api worker`（restart/force-recreate 不重载代码）；前端 `npm run build` 后 `docker cp` dist 到 frontend 容器。

## 文字气泡（2026-08-02 新增）

- 样式：格内底部居中白底圆角矩形 + 黑字 + 小尾三角，最多 3 行超出截断
- 中文字体：`fonts-noto-cjk`（Noto Sans CJK）打进 API 镜像（`apps/api/Dockerfile`）
  - 查找路径：`/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` → wqy → glob 兜底
  - **找不到字体时跳过气泡、不崩溃**（本地无字体跑测试也安全）
- 实现：`comic_service._draw_speech_bubble()`（在 `compose_comic_page` paste 每格前绘制）

## 跨格角色一致性

两级策略（`comic_service._generate_one_panel`）：

1. **图生图（首选）**：首格文生图成功后，其字节转 data URI 作为参考图，
   后续格走 grok2api `POST /v1/images/edits`（模型 `grok-imagine-image-edit`），
   prompt 追加"保持参考图中角色的形象完全一致"。
2. **降级（当前实际生效）**：edits 失败（404 `model_not_found`）→ 该格回退
   纯文生图 `/images/generations`。
3. **角色注入（弱一致性）**：`characters` 角色设定始终注入每格图片 prompt
   （"角色设定：X（所有格角色形象保持一致）"），保证无 edit 能力时仍按文字
   描述保持角色。

### 现状：账号池无 image_edit 能力

grok2api 管理 API（`/api/admin/v1/models`）实测：`grok-imagine-image-edit`
在模型目录中（enabled）但 `available=false, accounts=0` —— 当前 2088 个
grok 网页账号**均无 image_edit 能力**，`models/sync` 同步后仍为 0。
因此一致性走「角色注入」路径；未来若有带 edit 能力的账号导入，自动切图生图
（无需改代码）。

## 已知边界

- 拼合页不画角色名牌/场景标题（仅对白气泡）
- 跨格一致性依赖模型能力（当前为文字描述级，非像素级）
- 出图耗时：4 格约 2-4 分钟（串行 + 每格 30-60s；风控期可能更长）
- 单格失败自动灰格占位，任务仍 succeeded（`comic.panels` 保留完整分镜）

## 验证

```bash
# 单测（10 个：分镜兜底/宽松解析/拼合/气泡/edits 降级/参考图链/角色注入）
cd apps/api && .venv/Scripts/python.exe -m pytest tests/test_comic_service.py -q

# 真实 E2E：创建任务 → 轮询 → 校验资产
POST /api/v1/generations/comic/generate
  {"prompt":"...","panels":4,"style":"日式漫画","characters":"...","model":"grok-imagine-image"}
GET  /api/v1/tasks/{id}   # succeeded 后 result.comic.assets = 每格 + 拼合页
```

## 相关文件

| 路径 | 说明 |
|---|---|
| `apps/api/app/services/comic_service.py` | 分镜/出图/拼合/气泡全链路 |
| `apps/api/app/services/task_runner.py` | comic 任务分支 + 多资产保存 |
| `apps/api/tests/test_comic_service.py` | 10 个单测 |
| `apps/web/src/pages/ComicGenPage.tsx` | 前端表单 + 结果展示 |
| `apps/api/Dockerfile` | `fonts-noto-cjk` 中文字体 |

> 部署提醒：改动代码后必须 `docker compose build api` 再 `up -d --force-recreate api worker`（restart/force-recreate 不重载代码）。
