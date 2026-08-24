# saiOS v2 重设计规格书 —— 从「功能仓库」到「创作驾驶舱」

> 缘起：用户评价当前 saiOS "太 low、好多功能不对、没落地"。本规格书基于全量页面审计
> （38 条路由逐页核查）+ 三轮历史改造复盘，给出完整的重设计方案。
> 状态：**草案 v1**（审计数据汇总后定稿）

---

## 一、产品定位

### 一句话
**saiOS 是你的创作驾驶舱——左边跟 AI 聊着派活，右边看着引擎出活，底下所有产出自动归档。**

### 定位演进史（为什么要 v2）
| 版本 | 定位 | 结果 |
|---|---|---|
| v1 | AIGC 工作台（34 功能平铺） | "功能太多找不到、太乱、平凡没亮点" |
| v1.5（08-20 收敛改造） | 创作 AI 助手 | 只收了导航（18→11 项折叠），**体验没变**；P-A3 验证与"首页最近作品预览"烂尾 |
| **v2（本方案）** | **创作驾驶舱** | 对话 × 引擎双模，资产自动闭环 |

v1.5 的教训：**收敛导航 ≠ 解决 low**。功能还在原地（甚至藏得更深），页面本身依然是表单堆砌，
产出去向不明——用户体感"好多功能不对、没落地"。

---

## 二、诊断：六宗罪（附实证）

### 罪 1：信息架构断裂——27 个页面没有固定入口 ⚠️ 最致命
路由 38 条，侧栏导航仅 11 项。以下页面**只能靠搜索/深链/记忆 URL 到达**：
- 全部 8 个生成引擎页：`/create/text|image|comic|character-card|video|audio|music|prompt`
- `/story`、`/story/:id`（故事工作室）
- `/skills`、`/skills/:id/chat`（技能）
- `/workflows`、`/workflows/new`、`/workflows/:id/edit`（工作流画布，62KB 大组件！）
- `/photography`、`/photography/:albumId`
- `/search`、`/agent-directory`、`/agents/:id/chat`、`/create/studio`（AI 导演）、`/create/prompt-optimize`

**用户视角 = 这些功能不存在。** 这就是"好多功能都没落地"的第一真相：做了，但你永远找不到。

### 罪 2：功能重复三兄弟
- 文字生成：`AssistantHomePage`(73KB 巨石) vs `TextGenPage` —— 同一件事两个入口
- 提示词：`PromptsPage` vs `PromptGeneratorPage` vs `PromptOptimizerPage` —— 库、生成、优化三页分立
- 角色/智能体：`AgentsPage` vs `SkillsPage` vs `AgentDirectoryPage` vs `RoleplayPage` vs `CharacterCardPage` vs `SillyTavernPage` —— 六个页面都在讲"跟谁聊"
- 产出管理：`WorksPage` vs `TasksPage` vs `AssetsPage` —— 作品/任务/素材边界模糊

### 罪 3：主题精神分裂
浅色主题 = 暖白底 × 琥珀金（Krea 风）；深色主题 = 暖炭底 × **青色 #00f2fe**。
同一产品两套品牌色，切个主题像换了个 App。

### 罪 4：巨石组件打补丁
AssistantHomePage.tsx 72.8KB（约 2000 行）——P0-P3 八轮补丁全部堆在一个文件里；
WorkflowCanvasEditor.tsx 62.2KB。无拆分、难维护、首屏负担重。

### 罪 5：名不副实的功能（比空壳更伤信任）
创作类十页审计结论：**无一纯 mock 空壳**——但"能点开 ≠ 能用"：
- `MusicGenPage`：号称音乐生成，**实际只产出歌词 + "去 suno.com 粘贴"包**——本页根本不产音频；
  而后端 `/generations/music/generate` 和作品库明明存在却没接
- `VideoGenPage`：代码真实但 hub video 槽位为空 → **线上不可出片**，连下载按钮都没有
- `ComicGenPage`：硬编码 `grok-imagine-image`（服务器账号池只有 lite 可用）→ **大概率全失败**
- `AudioGenPage`：发音人选项 female/male/child 后端只认 default → **疑为假选项**
- `StoryProjectPage`：`/providers/catalog` 返回裸数组、前端按 `{items}` 解析 → **模型下拉永远落在兜底列表**（真断链 bug）

### 罪 6：四套聊天 UI 并存
AssistantHome（agent/chat+MCP）、TextGenPage（SSE 直连）、MusicGen discuss、AgentChat/SkillChat ——
同一个"跟 AI 对话"做了四遍，体验各异、维护成本四倍。

### 罪 7：关键交互是假的（用户感知"不落地"的直接来源）
- **@ 引用造假**：助手输入框插"@资源名"纯文本，资源实体从不进 prompt 上下文——用户以为 AI 读到了资料
- **工作流运行造假**：画布编辑器 xyflow 部分完整（undo/redo/自动保存），但「运行」按钮只是每节点
  `setTimeout(600ms)` 打日志；后端真执行器 `POST /workflows/{id}/run`（Kahn 拓扑+真 LLM）存在却从未被调用；
  节点模型下拉列的是平台根本没有的 GPT-4o/Claude/Gemini
- **Skills 抽象空心**：inputs_schema 定义了从不填充校验，"可被 Agent 与工作流引用"从未兑现
- **发音人假选项**：female/male/child 后端只认 default

### 审计横向结论（创作域）
媒体四件套共用 useMediaTask 真链路是健康底座；真正 low 的是：
①video/music 链路名实不符或上游未配 ②聊天 UI 四处重复 ③**所有生成页无内嵌历史区**，
产物全靠跳转任务中心/素材库兜底——用户感知"生成完就丢了"。

---

## 三、重设计核心决策

### 决策 1：「对话 × 引擎」双模架构
```
┌─────────────────────────────────────────────────┐
│  对话模式（唯一首页 / ）                           │
│  Assistant 升级：聊天流 + 能力卡 + 最近产出条      │
│  → 一句话派活；复杂需求引导跳引擎模式              │
├─────────────────────────────────────────────────┤
│  引擎模式（统一创作工作台 /studio）                │
│  8 个生成页 → 1 个 Studio：                       │
│  左栏=参数面板(按能力切换) | 中央=预览画布          │
│  底部=本次会话产出条 | 右侧=可折叠历史              │
│  能力 tab：文本/图像/漫画(并入图像)/视频/语音/音乐  │
└─────────────────────────────────────────────────┘
```
**AssistantHome 升级清单**（对应审计六硬伤）：
- 会话上云（后端加 chat_sessions 表 + 同步端点；媒体改持久化 URL 或入库缓存）
- @ 引用做真：选中资源 → 后端注入其内容到 prompt 上下文（UI 显示"已引用 ✓"徽标）
- 模型选择器接 `/providers/catalog`（修裸数组解析），删两处硬编码
- 斜杠命令结构化：`/画图 <prompt>` 直接带参调用 MCP 工具，不再回填占位句
- 文案去黑话：欢迎语改为真实能力描述
- Mission 任务总控从 Dashboard 迁入（对话式目标→拆解→执行）

### 决策 2：资产自动闭环（治"产出裂成四处"）
- 「作品」单页 = 时间线流（图/音/视频/音乐/漫画/角色卡/章节全部类型）+ 类型筛选 + 进行中任务内联
- 生成完成 → 自动入作品库（task succeeded 钩子已存在，补 works 归属写入）
- 每个产物可：再生成 / 变体 / 转素材参考 / 分享链接
- WorksPage 现有音乐+剧本板块作为类型筛选保留，删除静默吞错

### 决策 3：知识与提示词成为助手的弹药库
- `PromptGenerator/Optimizer` 降级为助手结构化命令 `/gen-prompt` `/optimize`（配合决策 1 第 4 条）
- 提示词库支持 @引用进对话上下文；保留只读浏览视图
- （待资源域审计数据补充 PromptsPage/KnowledgePage 处置）

### 决策 4：角色宇宙归一
Roleplay + CharacterCard + SillyTavern 教程 → 「角色」一个域：
- 列表 = 自研角色卡 ∪ ST 卡库市场，一个 UI
- 聊天界面统一（Roleplay 主视图）；ST 接入降级为设置里的引导卡（修公网路径+token 直显）
- Agents/Skills 与角色的关系待资源域审计定夺

### 决策 5：视觉语言统一（需用户拍板方向）
- 方向 A · 暖金驾驶舱：深色也用琥珀金（暖炭底×金），延续 Krea 编辑感，与模型中心控制台的霓虹风形成"后台冷前台暖"层次
- 方向 B · 全面 Cyber：对齐模型中心控制台（深空蓝×青），全站一个气质，动效加码
- 共同底线：无论 A/B，**两套主题必须同一品牌色**；组件圆角/阴影/间距令牌化

---

## 四、页面处置清单（38 → 目标 ~15）
（处置动词：保留=原样进新 IA；合并=并入 X；降级=移入设置/抽屉；砍=删代码留 git 历史）

### 创作域（10 页审计完毕）
| 页面 | 审计评级 | 处置 |
|---|---|---|
| ImageGenPage | ✅ 完整可用（全站标杆） | **保留核心逻辑** → 统一 Studio「图像」tab，补会话产物墙 |
| TextGenPage | ✅ 完整可用 | **砍独立页**：SSE 写作模式并进 AI 助手（长文模式），会话上云 |
| ComicGenPage | ⚠️ 半成品（硬编码必败模型） | 修模型名后 **并入图像 tab**（漫画=多格图像预设） |
| VideoGenPage | ❌ 空壳级半成品（链路死） | **导航隐藏**直至 hub video 槽配好；代码保留为 Studio 视频 tab |
| AudioGenPage | ✅ 完整可用（窄） | → Studio「语音」tab；修发音人假选项映射 |
| MusicGenPage | ⚠️ 名不副实（不产音频） | **接通 `/generations/music/generate`** → Studio「音乐」tab（写词+出歌一体）；删 Suno 外包逻辑 |
| CharacterCardPage | ✅ 完整可用 | → 角色域「捏人」入口，产出直接进角色库 |
| CreationPage（AI 导演） | ✅ 完整可用 | 保留；计划落库防刷新丢 + SSE 进度流 |
| StoryStudioPage / StoryProjectPage | ✅ 完整可用 | 保留独立域；**修 catalog 解析 bug** |

### 资源/工具域（11 组审计完毕）
| 页面 | 审计评级 | 处置 |
|---|---|---|
| PromptsPage | ✅ 完整（本组最佳：服务端过滤+瀑布流+空态骨架） | 保留；@引用通道接助手（决策 3） |
| PromptGeneratorPage | 🟡 半成品（9 字段只展示 4 个） | 与优化器合并为一页双 tab |
| PromptOptimizerPage | 🟡 半成品（无保存无历史） | 同上 |
| AgentsPage+Chat | ✅ 完整但组织混乱（页内嵌 tab 双入口、模型自由文本输入） | 库保留；聊天收敛到 AI 助手 |
| SkillsPage+Chat | 🟡 空心半成品（inputs_schema 定义了从不使用；"被工作流引用"未兑现） | **砍独立抽象**：并入 Agent 的 system_prompt 模板 |
| KnowledgePage | ✅ 完整（ask 关键词 RAG 真、pending→confirm 防污染设计好） | 保留；补分页 |
| WorkflowsPage | ✅ 完整（后端 run_workflow Kahn 拓扑+真 LLM 执行存在！） | 保留 |
| WorkflowCanvasEditor | 🟡 **画布编辑器完整但运行造假**：setTimeout 打日志假装执行、节点模型下拉是平台不存在的 GPT-4o/Claude | 「运行」接真 `POST /workflows/{id}/run`；节点绑定真实库 ID；否则删播放按钮 |
| PhotographyPage×2 | 🟡 半成品（素材管理完整但与生成链路零集成） | 保留素材库属性；补 style-reference 出图闭环或砍"摄影"叙事 |
| AsmrPage | ✅ 完整（810 行、15 后端端点、门控设计完整） | 保留差异化功能；补站内播放 |
| SearchPage | ✅ 完整（后端五 scope 聚合非前端假过滤） | 保留 |

### 资源域结论
真正空壳几乎没有（7/11 组 API 链路为真）。问题集中在：画布假执行、Skills 抽象空心、
三套重复聊天、Photography 只存不用、Prompt 两工具页孤岛——全是**整合度**问题。

### 管理与其余域
| 页面 | 审计评级 | 处置 |
|---|---|---|
| DashboardPage | ✅ 完整但 1230 行五合一 | **拆**：Mission 任务总控并入 AI 助手；本页降级纯数据看板；删装饰性"六步循环条"；巡检卡移出用户视线 |
| WorksPage | ⚠️ 半成品（名不副实：仅音乐+剧本、吞错假空态） | **重做为「作品」聚合页**（见决策 2），吸收 Tasks 进行中态 |
| TasksPage | ✅ 完整 | 并入作品页"进行中"视图；从"系统"组移回创作侧 |
| AssetsPage | ✅ 完整 | 保留为素材库；"写真摄影 tab 占位"接 Photography 或删 |
| ProvidersPage | ✅ 指引页（符合设计） | 导航改名"模型中心 →"，不再叫"模型配置" |
| UsersPage / LogsPage | ✅ 完整（薄） | 保留设置区；UsersPage 补编辑/改密 |
| UpstreamPage | ⚠️ 注册按钮云端必挂 | "立即注册 grok 账号"按钮删除（服务未迁移）；状态卡并入数据看板 |
| RoleplayPage | ✅ 完整但超载（单页 7 tab 塞 540px 高度） | 拆：聊天主视图保留；世界书/正则/记忆等高级项收"设置"二级抽屉 |
| SillyTavernPage | ⚠️ 半成品教程页（端口硬编码公网失效 + token 明文展示） | **并入角色扮演页作"接入 ST"引导卡**，修相对路径、token 改点击复制不直显 |
| AgentDirectoryPage | ✅ 完整但与创作零耦合 | 移出主导航，入口降级到发现页/页脚 |
| AssistantHomePage | ✅ 功能完整 / ❌ 体验半成品 | 见 §三 决策 1 升级项 |

### AssistantHome 六个体验硬伤（v2 主攻）
1. **会话仅 localStorage**：换设备/清缓存全丢；媒体 access-url 过期后历史图文全裂
2. **@ 引用是假的**：只往输入框插"@资源名"文本，资源实体从不进 prompt 上下文
3. 斜杠命令只是回填含 `____` 占位的示例句，非结构化指令
4. 顶部模型 chip 与 payload 双处硬编码 `gpt-oss-120b`，换链要改代码
5. 欢迎文案黑话（"神经网络交互矩阵""神经算力渲染画廊"）与真实能力错位
6. "返回首页"硬编码 `/saios/login`

### 四大结构病总判（管理域审计结论）
"太 low、没落地"的感受**不源于功能缺失**（绝大多数 API 真实存在），而源于：
①产出裂成四处无处汇聚 ②双首页并存职责撞车 ③命名与导航归属失真 ④AI 助手缺最后一公里（持久化与真引用）。

---

## 五、分期交付

### P0 · 信息架构建复 + 止血（半天~1 天，见效最快）
1. 导航重组：新增「创作工具」组（Studio/Story/角色/工作流入口补全 27 缺失项的可达性）；
   任务中心移出系统组；AgentDirectory 移出主导航
2. 快修四个真 bug：
   - StoryProjectPage catalog 裸数组解析（模型下拉断链）
   - ComicGenPage 硬编码 `grok-imagine-image` → 接 hub image 链或 lite
   - AudioGenPage 发音人假选项 → 后端真实映射或 UI 收敛为"自动"
   - UpstreamPage 删云端必挂的注册按钮；SillyTavern 教程页修公网路径 + token 不直显
3. ProvidersPage 导航改名"模型中心 →"
4. 验收：38 路由全部 ≤2 点击可达；四 bug 复测通过

### P1 · 双模架构落地（2~3 天）
1. AssistantHome 六硬伤修复（云同步/真引用/模型选择器/结构化命令/文案去黑话）
2. Dashboard 瘦身：Mission 并入助手，看板归纯数据
3. 验收：双首页消失；换设备会话不丢；@ 引用后回答能引用资源内容

### P2 · 统一创作 Studio（3~4 天）
8 生成页 → /studio 单页多 tab；每 tab 底部会话产物墙；Music 接通音频生成闭环；
Video tab 在 hub 配好前显示"引擎未接入"引导而非裸表单
- 验收：一次创作会话内完成 派活→预览→再生成→入作品库，零跳转

### P3 · 资产闭环 + 视觉统一（2~3 天）
Works 三合一聚合页；角色域归一；主题品牌色统一（方向 A/B 待拍板）；
AssistantHomePage 巨石拆分（组件化 + hooks 抽取）
- 验收：见 §六

### 每期通用约束
- `npx tsc --noEmit` + 生产 build 通过后才部署；docker compose build frontend 后连带重启清 nginx 缓存
- E2E 回归：`--workers=1` 跑默认套件防登录态互踩

## 六、验收标准
- [ ] 任何功能 ≤2 次点击可达（含移动端）；38 条路由无一"孤儿页"
- [ ] 新用户 30 秒内完成一次"派活→看到产出"，产出自动出现在作品流
- [ ] 所有产出在同一处可见、可再加工、可分享
- [ ] 深浅主题切换不产生"换 App"感（同一品牌色贯穿）
- [ ] 零假交互：@引用真进上下文、画布运行真执行、选项后端真实支持
- [ ] AI 助手会话跨设备可用；媒体历史不过期裂图

## 七、技术实施注意
- Module Federation 远程模式（hostContext.compactMode）需保持兼容
- PWA：sw.js 缓存策略在新路由下要回归测试
- 部署链路：docker compose build frontend（镜像内构建），改动后连带重启 frontend 容器清 nginx 解析缓存
- ⚠️ **Python 版本坑（08-24 审计实测）**：api 容器跑 Python 3.14，PEP 758 已合法化无括号多异常捕获
  （`except A, B:`）；但本地/CI 老解释器会 SyntaxError。已全仓统一为 `except (A, B):`（17 处）——
  以后写代码别再用裸逗号形式；审计工具报"全站起不来"前先确认目标运行时版本
- 前端 E2E 登录态轮换：GUI 测试必须 --workers=1
