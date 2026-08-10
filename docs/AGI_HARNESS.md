# AGI Agent Harness 演进蓝图（2026-08-10）

> 方向：把 AIGC Studio 从「AI 创作工具集合」演进为「AGI Agent Harness」——
> 一个让 AI 从「聊天/生成模型」进化为「自主智能体」的运行时。
> 原则：编排层演进，不重写底层；每一步复用已有能力。

## 一、对照：Harness 概念 vs 平台现状

| Harness 模块 | 平台现状 | 差距 |
|---|---|---|
| **AGI Orchestrator**（任务总控） | AI 导演工作室（主题→选角→剧本→评审）仅限剧本域 | **缺：通用目标→自动拆解→执行→汇总** |
| **Planning Engine**（认知规划） | 创作罗盘（全书承诺）；剧本大纲生成 | 缺：多步任务的自动规划器 |
| **Agent Runtime** | Agent 库（工具调用 agent_chat.py）、角色卡、群聊多角色 | 缺：Agent Instance 显式状态（Goal/State/Reflection） |
| **Multi-Agent Society** | 创作圆桌（4 角色真讨论）、群聊共创、story_crew 流水线 | ✅ 较完整（创作域） |
| **Memory** | MemoryCore L0-L3 + 状态账本 + 知识库 + 创作范例回填 | 缺：Episodic（经验/教训）显式化 |
| **Tool Harness** | 知识库检索、联网搜索、Agent MCP 工具、媒体生成任务 | ✅ 较完整 |
| **Reflection Engine** | AI 腔检测、定稿自检、批评带替代、自动重写 | ✅ 隐式存在，可显式化（失败经验沉淀） |
| **Evolution Engine** | 好作品回填知识库、写法特征提取 | ✅ 雏形（成功经验）；缺失败经验 |
| **Workflow Engine** | 工作流画布（DAG + 节点，xyflow） | ✅ 已有 |
| **Environment Simulator** | 无（生成即产出） | 创作域不需要沙盒；代码域可后续 |

## 二、演进路线（分阶段）

### 阶段 1：Mission 任务总控（Orchestrator 内核）
用户给一个目标 → LLM 自动拆解为多步计划（复用现有能力：圆桌/文本/图片/视频/搜索）→
顺序执行 → 汇总成果。核心循环：perceive(目标) → plan(拆解) → execute(调度) → observe(结果)。

### 阶段 2：Reflection 显式化（经验库）
- 每次创作记录 (目标, 产出, 自检警告, 教训)
- 失败/警告经验沉淀为「创作教训」资产，后续创作注入（与创作范例并列：成功样本 + 失败教训）

### 阶段 3：Agent Runtime 状态化
- Agent 库升级：每个 Agent = Identity + Goal + Memory + Tools + State + Reflection（可运行、可被 Orchestrator 调度）

### 阶段 4：Multi-Agent Orchestration
- Mission 计划支持「并行子任务 + 依赖图」；多 Agent 协作完成目标（研究→创作→评审→交付）

## 三、阶段 1 详细设计（Mission）

### API：POST /api/v1/mission
```json
{ "goal": "写一首关于矿工的歌，并配一张矿井清晨的图" }
```
→ LLM 拆解：
```json
{ "plan": [
    { "step": 1, "kind": "roundtable_music", "prompt": "矿工清晨的叙事民谣", "depends_on": [] },
    { "step": 2, "kind": "image", "prompt": "矿井清晨，逆光剪影，cinematic", "depends_on": [] }
]}
```
→ 逐步骤执行（kind → 现有能力）→ 汇总：
```json
{ "results": [{ "step": 1, "kind": "...", "summary": "...", "work_id": "..." }, ...], "summary": "..." }
```

支持 kind：`roundtable_music`（音乐圆桌 quick）/ `text`（文本生成）/ `image`（图片任务）/ `video` /
`search`（联网检索）/ `kb_ask`（知识库问答）。最多 4 步，串行。

### 前端
工作台快速创作框升级：输入目标 →「🎯 交给任务总控」→ Mission 页展示计划/逐步执行/成果。
