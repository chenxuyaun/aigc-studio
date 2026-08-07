# SillyTavern 接入指南

> 维护：2026-08-02
> SillyTavern（角色扮演聊天）已通过 AIGC Studio 接入：统一 OpenAI 兼容网关 + 角色卡工厂。

## 一、架构

```
SillyTavern（http://localhost:8001，容器）
  ├─ OpenAI 兼容 API → AIGC 网关 http://localhost:8002/v1/chat/completions
  │     ├─ model=grok-chat-fast → grok2api
  │     └─ model=gpt-oss-120b-medium → cpa
  └─ 角色卡（PNG 拖入即用）← AIGC「角色卡生成」页
```

- SillyTavern 容器：`aigc-studio-sillytavern-1`（:8001，data 卷持久化角色卡/对话/世界书）
- 网关鉴权：Bearer AIGC 登录 token（工作台登录后拿到的 token）

## 二、首次配置（SillyTavern）

1. 打开 `http://localhost:8001` → 首次访问按引导设置管理员密码（403 是安全机制，属正常）
2. 右上角设置 → **API 连接**：
   - API：`Custom (OpenAI)`
   - Chat Completion 源：**`http://localhost:8002/v1`**（注意：SillyTavern 的 API 请求由**浏览器**直接发出，必须用浏览器可达的地址 —— 填 `localhost`，**不要**填 `host.docker.internal`，那是容器内域名，浏览器解析不了会报 502）
   - API Key：AIGC 工作台登录 token（`http://localhost:8002/api/v1/auth/login` 登录后 access_token；或前端浏览器 F12 里取）
   - 模型：`grok-chat-fast`（Grok）/ `gpt-oss-120b-medium`（cpa），可随时切换
3. 保存后即可开始角色扮演

> 若配置正确仍报 502/网络错误：确认 AIGC `.env` 的 `CORS_ALLOWED_ORIGINS` 包含 `http://localhost:8001`（已默认配置）；token 过期会 401。

## 三、角色卡工厂

工作台 → AI 创作 → **角色卡生成**（或 `http://localhost:5000/create/character-card`）：

1. 输入角色描述（如"一只会魔法的黑猫，喜欢恶作剧但心地善良"）+ 选头像风格
2. 生成：cpa 生成角色设定（名字/外貌/性格/初始场景/开场白）→ grok 生成头像 → 打包成 SillyTavern 标准 PNG 角色卡（tEXt 块内嵌 chara JSON）
3. 下载 PNG → 拖入 SillyTavern 角色卡管理即可使用

角色卡同时存入素材库（可在素材库查看）。

## 四、与 AIGC 的分工

| 能力 | 归属 |
|---|---|
| 角色扮演对话（角色卡/世界书/情绪） | SillyTavern（数据在容器 data 卷） |
| 角色卡生成（设定 + 头像） | AIGC 角色卡工厂 |
| 文本/图片/漫画/语音生成、任务、素材 | AIGC 工作台 |
| 网关聚合（双模型切换） | AIGC `/v1/chat/completions` |

## 五、排障

| 现象 | 处理 |
|---|---|
| SillyTavern 403 | 首次访问需设置管理员密码 |
| 网关 401 | token 过期（默认 24h），重新登录获取 |
| grok 模型报 upstream_error | grok.com 风控间歇（503），切 cpa 模型或稍后重试 |
| 角色卡头像为纯色底 | grok 图片上游暂不可用（自动 fallback），恢复后重新生成 |
| 网关 unknown model | SillyTavern 模型名填 grok-chat-fast 或 gpt-oss-120b-medium |

## 六、相关文件

| 路径 | 说明 |
|---|---|
| `apps/api/app/api/v1/openai_gateway.py` | OpenAI 兼容网关（/v1/chat/completions） |
| `apps/api/app/services/character_card.py` | 角色卡工厂（cpa 设定 + grok 头像 + PNG 打包） |
| `apps/api/app/api/v1/character_cards.py` | 角色卡端点 + 素材入库 |
| `apps/web/src/pages/CharacterCardPage.tsx` | 前端角色卡生成页 |
| `SillyTavern/` | SillyTavern 源码（官方仓库，AGPL-3.0，未改动） |
| `compose.yaml` | sillytavern 服务（:8001，restart unless-stopped） |

## 七、工作台原生角色扮演（SillyTavern 功能融入版，2026-08-03）

工作台内置原生「角色扮演」页（`/roleplay`，左侧导航「角色」），
把 SillyTavern（学习项目源码 `D:\software\code\ideas\writers\SillyTavern`，1.18.0）的核心机制
按"合理适配"原则融入（FastAPI + React + 本地多模型），覆盖：

| 功能 | 说明 |
|---|---|
| 角色卡 V2 全字段 | 生成/导入/导出（PNG V1/V2/V3 + JSON），备用开场白/系统提示/PHI/创作者备注/标签/话痨度 |
| 世界书引擎 | 多关键词（支持 `/正则/`）、常驻、选择性（次关键词 AND_ANY/AND_ALL/NOT_ANY/NOT_ALL）、位置（开头/结尾/聊天中部深度）、优先级、概率、整词/大小写、全局书（character_name 为空） |
| 服务端会话 | 会话列表/新建/切换/重命名/删除/清空，**导出 SillyTavern JSONL / 导入回放** |
| 流式输出 | SSE 逐字渲染，消息与情绪落库 |
| swipe 备选回复 | 「换一个」生成候选 + ‹ 1/N › 切换（不落库） |
| 续写 continue | 「继续写」从原回复末尾接续，合并到同一条消息落库 |
| 多开场白 | 首轮从 first_mes + 备用开场白随机选择 |
| 单条消息删除 | 气泡「删除」同步服务端会话 |
| 角色搜索 | 角色卡列表关键词过滤 |
| 上下文 token | 服务端返回 prompt_tokens 估算，标题栏展示 |
| 群聊策略/模式 | 轮流策略（自然/按序/随机）+ 注入模式（全员卡片/仅说话者） |
| 作者注频率 | 每 N 条用户消息注入一次（作者注注入 system prompt，深度注入由世界书 atDepth 承担） |
| 正则调试器 | 正则脚本测试区（本地实时预览） |
| 快捷回复自动触发 | auto 开关：发消息后自动建议并填入输入框 |
| 宏系统 | `{{char}}` `{{user}}` `{{group}}` `{{random::A::B}}` `{{pick::A::B}}` `{{roll::1d20}}` `{{time}}` `{{date}}` `{{newline}}` 等 |
| 群聊 | 多角色同场 + 全员卡片注入（APPEND）+ 群聊 nudge + 情绪标注 |
| 情绪/好感度 | `[情绪:XX]` 标签提取 → 气泡徽章 + 好感度累计（localStorage） |
| 正则脚本 | user_input 发送前 / ai_output 展示前的查找替换（全局/按角色） |
| 快捷回复 | 输入框上方按钮行（支持宏展开） |
| 用户形象 | persona（名字 + 描述注入 system prompt，`{{user}}` 替换） |
| 采样参数 | 温度 / 最大 token 透传 provider |
| 作者注 | 会话 note 注入 |

**Prompt 组装管线**（对齐 ST）：世界书 before → 角色卡主提示（system_prompt 覆盖）→
描述/性格/场景 → persona → 作者注 → 世界书 after → 扮演要求（情绪标签）
→ 历史（预算截断）→ 示例对话（mes_example）→ 群聊 nudge → 续写指令。

后端模块：
- `app/services/roleplay.py` —— 主流程（角色卡加载/世界书/prompt 管线/情绪/正则/会话落库）
- `app/services/worldbook.py` —— 世界书引擎（倒序深度扫描/常驻/选择性/概率/预算）
- `app/services/macros.py` —— 宏系统
- `app/services/character_card.py` —— V2 角色卡解析/生成/导入导出
- `app/services/sessions.py` —— 会话 CRUD + ST JSONL 导出导入
- `app/api/v1/roleplay.py` —— 全部端点（角色卡/会话/流式/世界书/正则/快捷回复/persona）

前端：`apps/web/src/pages/RoleplayPage.tsx` + `src/pages/roleplay/*`（会话侧栏/角色卡面板/世界书面板/正则面板）。

数据表（迁移 `f2a9d5e7b3c1`）：`roleplay_characters`、`roleplay_chats`、
`roleplay_lore_entries`（扩展）、`regex_scripts`、`quick_replies`、`roleplay_personas`。

与独立 SillyTavern 的分工：原生页覆盖核心角色扮演；SillyTavern 独立窗口（:8001）
保留高级玩法（扩展市场/向量/自定义 UI），角色卡与 JSONL 会话可双向互通。

### Grok 通道恢复（需手动操作，代理无法代劳）

grok2api 当前 2097 个账号全部为 SSO 一次性小号（`refreshable=false`、`quota=0`），
已探测所有疑似刷新端点均不存在，注册机亦无新注册能力 —— **恢复唯一途径**：
1. 浏览器登录 `https://grok.com`，确认账号能正常聊天
2. F12 → Application → Cookies → 复制 grok.com 域名下全部 cookie
3. 打开 grok2api 管理面板 `http://localhost:8000` → 账号管理 → 导入 cookie
   （或调 `POST /api/admin/v1/accounts` 导入，详见 `docs/grok2api-troubleshooting.md` 4.2）
4. 导入后本页模型选择 Grok 快模型即可恢复（导入前选 Grok 会收到友好错误提示而非卡死）

### 实测验证（2026-08-03）

- 单元测试 135 项全过（含世界书引擎 8 项/宏 3 项/JSONL 3 项/V2 解析）
- 真实 E2E 35 项全过：角色卡导入导出、会话 CRUD + JSONL 往返、流式 SSE（chunk/done/mood）、
  世界书全字段、正则实际替换 AI 回复（`*`→【】）、persona、快捷回复
- 浏览器 GUI 实测：新页面渲染、会话历史加载、消息发送、流式 200、无限请求循环修复（211→1 次/页）

### 部署注意（前端缓存）

- `index.html` / `sw.js` / `registerSW.js` 必须 `no-cache`（SPA 部署后用户才拿得到新版本）
- PWA `registerType: autoUpdate`，旧 Service Worker 用户**刷新一次**即升级到新版

---

# Story Forge · 角色扮演创作引擎（v2）

> 维护：2026-08-04
> 角色扮演从「聊天」升级为「内容创作基础设施」：以角色扮演的方式生成小说与剧本，
> 叠加技能 / 创作团队（agents）/ 流程（workflow 节点）/ 自动化（连载）。

## 一、入口

工作台侧栏 → **「创作工作室」**（`/story`）。新建项目：书名 / 类型 / 梗概 / 选择角色卡
（选中的卡自动成为故事角色实例，可补充目标、弧线、当前状态、技能）。

## 二、核心概念（五层）

| 层 | 能力 | 实现 |
|---|---|---|
| ① 创作项目 | story bible：项目 + 章节 + 角色实例 + 项目级世界书 | `story_projects` / `story_chapters` / `story_characters` 表；lore `project_id` 作用域 |
| ② 章节生成 | **叙事模式**（作者视角写小说正文）与**剧本模式**（群聊引擎让角色轮流发言拼装对话流）；SSE 流式 / 任务化 / 修订 | `app/services/story_forge.py`，复用角色卡/世界书/宏/正则/群聊管线 |
| ③ 创作流程 | 工作流新增 `outline_gen` / `chapter_gen` / `revise` 节点，产出直接落库 | `app/api/v1/workflows.py` `_run_story_node` |
| ④ 创作团队 | 主编（剧情方向）/ 作家 / 校对（一致性审校）/ 剧务（角色状态推进）；MCP 创作工具供 agent 调用 | `app/services/story_crew.py`；MCP 工具 `read_bible` / `write_chapter` / `update_character_state` / `list_outline` |
| ⑤ 自动连载 | celery beat 每分钟 tick，扫描到期调度生成下一章（上一章未完成自动跳过） | `app/tasks/story_tasks.py` `serial_tick` |

## 三、API 速查（前缀 `/api/v1/story`）

```
POST   /projects                         新建项目（自动建角色实例）
GET    /projects/{id}/bible              故事圣经聚合视图
POST   /projects/{id}/outline?chapters=N 生成全章大纲（批量建章节）
POST   /projects/{id}/crew               创作团队阶段：director/writer/editor/stagehand
GET    /projects/{id}/export?format=markdown|jsonl  导出整本
POST   /projects/{id}/schedules          启动连载（interval_minutes/batch_size/mode）
POST   /chapters/{id}/generate           同步生成（mode=narrative|script）
POST   /chapters/{id}/generate/stream    SSE 流式生成
POST   /chapters/{id}/generate/task      任务化生成（任务中心可见）
POST   /chapters/{id}/revise?instruction=  按指令修订
GET    /roleplay/lore?project_id={id}    项目级世界书
```

## 四、角色技能

`story_characters.skill_ids` 关联技能库（Skill）→ 技能 `instructions` 注入章节生成提示词；
MCP 创作工具进入工具循环（`_openai_tools` 自动转换），agent/角色可主动读写 bible 与章节。

## 五、工作流集成

现有「工作流」画布新增三种节点类型：
- `outline_gen`：params {project_id, chapters} → 生成大纲落库
- `chapter_gen`：params {project_id, chapter_no?} → 自动创建/定位章节并生成正文
- `revise`：params {project_id, chapter_id} → 按上游输出指令修订

执行结果在运行面板 `story_results` 中返回（含 chapter_id）。

## 六、测试

- `tests/test_story_forge.py`（服务级：CRUD/叙事/剧本/大纲/修订/导出/连载 tick）
- `tests/test_story_api.py`（API 级：端点/越权/任务化/lore 作用域）
- `tests/e2e/test_story_forge_e2e.py`（真实 E2E：23 项全流程）
