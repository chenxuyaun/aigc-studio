# Personal Voice Engine（去 AI 味 → 像具体的人）— 技术方案与实施记录

> 2026-09-03 立项。分支 refactor/v1，5 个 commit（d26b929 → 8ef9b54），每批全量 pytest 绿。

## 1. 问题与方向

**现象**：saiOS 写音乐/写文输出 AI 味重，老师/用户反馈「一看就是 AI 写的」。

**方向判断（关键）**：不做「AI 降重 / 禁词表降 AI 检测」——那是换皮游戏（禁了「值得注意的是」
模型就换「需要特别强调的是」）。真正有效的是 **Personal Voice Engine**：
让 AI 输出**越来越像用户自己**（保留用户习惯、节奏、立场、具体性），
而不是越来越像某个「人类文本模板」。

```
AI 原始生成 → ① Voice/人格层 → ② Context → ③ 写作技法 → ④ Critic 审稿 → ⑤ Rewrite → FINAL
                    ↑（最重要）         ↑复用现有           ↑ai_voice_checker
                 voice_profiles     ai_memory_entries     已 voice-aware
```

调研参考：Humanizer 系 Skill（ankshvayt/milock/spuvr）——从「替换 AI 高频词」演进到
「语气建模 → 结构重写 → 自审 → 二次修改」；共同趋势 = 从骗检测器转向真实作者声音。

## 2. 复用与接缝（落地前已核实）

| 现有资产 | 位置 | Voice Engine 复用 |
|---|---|---|
| 长期记忆 | `ai_memory_entries`(growth) + `build_memory_injection` | 语料来源（偏好/事实） |
| 反 AI 味底子 | `AssistantHomePage.tsx` 文风铁律 / `music/prompts.py` / `music/quality.py` | 保留为通用基线 |
| AI 腔检测器 | `applications/ai_voice_checker.py` | 升级 voice-aware |
| 注入点 | `applications/agent_chat.py` 记忆注入后 | 并列加 voice 注入 |
| 文本路由 | `resolve_text_provider`（hub 链/failover） | voice 层不碰模型层 |
| 用户真实文字 | `ChatSession.messages` / `TextDocument` / 创作历史 | auto-extract 语料 |

**架构原则**：voice 是创作 Runtime 之上的一层（Memory + Voice + Experience + Critic），
不是新系统；注入/提取失败静默降级，绝不影响主链路（同 growth 模式）。

## 3. 数据层（P0，d26b929）

### voice_profiles（每用户一份文风档案）

| 列 | 类型 | 说明 |
|---|---|---|
| id | String36 PK | uuid |
| user_id | String36 idx | 一用户一行 |
| name | String50 | 默认「我的文风」 |
| voice_dna | JSON | Voice DNA（见下） |
| samples | JSON | `[{title, text}]` 范文（≤10 条，单条 400 字） |
| source | String10 idx | **manual**（用户编辑，不覆盖）/ **auto**（LLM 提取） |
| updated_at | DateTime | |

### voice_dna JSON 结构

```json
{
  "sentence_length": "short|medium|long|mixed",
  "vocabulary": "simple|medium|rich",
  "formality": "casual|medium|formal",
  "emotion": "restrained|warm|expressive",
  "humor": "none|dry|witty",
  "opinion_strength": "low|medium|high",
  "preferred": ["短句", "偶尔反问", "直接表达判断"],
  "avoid": ["套话", "总结式结尾", "过度解释", "企业宣传口吻"],
  "openings": [], "endings": []
}
```

### voice_corpus（个人语料）

`user_id / kind(article|chat|note|lyric|story) / text_snippet(400) / source_ref / created_at`
每用户 200 条上限，超出淘汰最旧。**先 prune 再 add**——同事务 DELETE 会连带删刚
add 的新行（第 201+ 条时 commit 后 refresh 报 InvalidRequestError，测试抓到）。

### 迁移

`alembic/versions/a1c3e5d7b9f1_voice_profiles.py`，down_revision = `e5f7a9b1d3c5`
（community_posts，2026-09-03 文件图单头核实——先查单头再挂，防双 head 崩溃）。

## 4. 服务层（P0/P1）

`app/applications/voice_service.py`（`app/services/voice_service.py` 为 sys.modules 别名 facade）：

| 函数 | 行为 |
|---|---|
| `get_profile` | 读档案；不存在返回 None（读路径不落库） |
| `get_or_create_profile` | 读取或初始化（仅 flush 不 commit——读路径无副作用） |
| `update_profile` | **upsert** 手动编辑；`source=manual`；dna 缺省字段补默认 |
| `auto_extract_profile` | LLM 从语料提炼 DNA；**manual 档案不覆盖**；LLM 失败静默降级规则统计（句长/情绪） |
| `build_voice_injection` | system 注入文案（≤900 字）：基调 + 喜欢 + 忌讳 + ≤2 条范文 |
| `add_corpus` / `list_corpus` | 语料管理（prune 先于 add） |

`auto_extract` 语料来源：ai_memory_entries(preference/fact) + ChatSession 用户消息
+ TextDocument(confirmed) + VoiceCorpus，总预算 4000 字送 LLM。
`_gather_corpus` 结果为空 → 返回 None（不建档，extract API 报 ok:false）。

## 5. 注入（P1，06d96fc）

`agent_chat_stream`：记忆注入后并列：

```python
if user_id:
    try:
        voice_text = await build_voice_injection(db, user_id)
        if voice_text:
            messages = [{"role": "system", "content": voice_text}, *messages]
    except Exception:
        pass
```

无档案 → 空串自动跳过；失败静默。覆盖所有 agent 对话（含多模态创作请求），
与「歌词文风铁律」前端 system prompt 共存（前端是通用基线，后端 voice 是个人化层）。

## 6. API（P1，06d96fc）——`app/api/v1/voice.py`，前缀 `/voice`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/profile` | `{exists:false}` 或 `{exists:true, profile}` |
| PUT | `/profile` | upsert 建档/编辑（manual） |
| POST | `/profile/extract` | 自动提取；无语料 `{ok:false, reason}` |
| DELETE | `/profile` | 停用（删档案即停 voice 注入） |
| GET | `/corpus?kind=&limit=` | 语料列表 |
| POST | `/corpus` | 加语料（`min_length=8` pydantic 拦 422） |

## 7. 前端（P1b，0725838）——VoiceBadge

`components/voice/VoiceBadge.tsx`（自包含，挂在 AssistantHomePage 顶栏模型选择器旁）：
- 有档案：高亮徽标 + 面板预览 preferred/avoid 标签 → 粘贴新样本 → POST corpus +
  extract 更新 → 停用（DELETE）
- 无档案：引导贴 1~3 段自己的文字 → 提取我的文风
- 注入本身后端自动做，组件只负责用户感知与控制

## 8. Critic voice-aware（P2，4cd6a22）——`ai_voice_checker`

`check_ai_voice(text, voice_dna=None)` 签名向后兼容（roundtable/story 调用不动）：
- **voice_avoid(high)**：命中用户 voice_dna.avoid 的个人忌讳表达（≥2 字防误报），
  suggestion 带原词「这是你文风档案里忌讳的表达」
- **voice_rhythm(medium)**：档案 sentence_length=short 但文本半数以上句子 >30 字 → 提示拆句

从「通用 AI 腔」升级为「对照具体用户的写作习惯」。

## 9. Style Reference MCP（P3，8ef9b54）——`mcp/server.py`

| 工具 | 说明 |
|---|---|
| `get_voice_profile(ctx)` | 用户要求「按我的风格写/像我这样说话/去 AI 味」时模型主动查档案（DNA + 前 2 范文） |
| `add_voice_sample(text, kind, ctx)` | 用户给一段自己的文字 → 存语料（≥8 字） |

随 `_openai_tools()` 自动进 agent 工具循环（工具总数 20→22）。用户隔离走
`_request_user_id(ctx)` 惯例；工具函数内延迟 import（测试可 patch AsyncSessionLocal）。

## 10. 与七层/四阶段的映射

| 你给的方案 | 实现状态 |
|---|---|
| P0 humanizer+anti-cliché+rhythm+self-critique | ✅ ai_voice_checker voice-aware + music/quality 已有自检 |
| P1 voice-profile + style-reference + corpus | ✅ voice_profiles + voice_corpus + get_voice_profile/add_voice_sample |
| P2 experience-injection + memory + history | ✅ auto_extract 从记忆/聊天/文档语料提炼（自动层） |
| P3 multi-agent critic + style evaluator | ⏳ 未做（story_crew 一致性审查可扩展 style 审查） |

## 11. 测试与验证

- `tests/test_voice_service.py` 10 个：CRUD/upsert/manual 优先/LLM 提取/规则降级/
  无语料 None/corpus 上限（prune 先于 add 修复）
- `tests/test_voice_api.py` 5 个：CRUD 流/extract 无料/prompt 含与不含文风注入
- `tests/test_voice_mcp.py` 5 个：建档读取/入库/过短/注册（fixture 自插 admin——测试库只建表不 seed）
- `tests/test_ai_voice.py` +5 voice-aware；`test_mcp_tools.py` 计数 20→22
- 每批全量 pytest 绿；前端 tsc 零错误 + vite build 通过
- ⚠️ 既有 flaky：`test_security_hardening::test_task_cancel_marks_cancelled`
  （cancel 竞态，AGENTS.md 已记录，与 voice 无关）

## 12. 后续方向（未做，需用户拍板）

1. **music/roundtable/story 垂直接入**：engine 出稿后跑 voice-aware check_ai_voice
   （传当前用户档案），命中触发 rewrite 轮（音乐场景已有 quality 自检，可传 profile）
2. **Experience Injector**：创作时注入用户真实经历（记忆里有 event 类）——现只注入了
   voice 档案，事件素材未注入创作 prompt
3. **自动提取时机**：现在 extract 是手动触发（前端按钮/API）；可加「对话积累后自动
   auto_extract」或「每日一次」
4. **Style evaluator（P3 multi-agent）**：story_crew 加 style 审查环节
5. **前端展示**：VoiceBadge 可升级为可编辑表单（现只能贴样本 + 停用，dna 字段不能手改）

## 13. 部署注意（上线时执行）

- 迁移会在 api 容器 entrypoint `alembic upgrade head` 自动执行（先确认服务器 DB 单头
  `SELECT version_num FROM alembic_version`，若与文件图不符先对齐）
- 后端改动需 `docker compose up -d --build api worker`（源码在镜像构建时 COPY）
- frontend 需 `docker compose up -d --build frontend`；api 重启后 frontend 若 502 需
  `--force-recreate`（nginx 缓存旧 IP）
- 部署后冒烟：health / 登录 / GET /api/v1/voice/profile / agent chat 带 voice
