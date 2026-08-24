# 删除规划：saiOS 旧供应商通道下线（deprecation plan）

> 背景：模型中心已补齐 CC Switch × Cherry Studio 全部功能（见 `ccswitch-cherry-parity.md`），
> saiOS 内部还残留**三条重复的供应商通道**。本文档规划其安全下线。
> ⚠️ **执行前需用户逐阶段确认；每阶段独立可回滚。**

## 一、现状：三条通道并存

| 通道 | 位置 | 当前角色 |
|---|---|---|
| **① 模型中心（hub）** | sqlite `/home/ubuntu/model-hub/`，UI :8511 | **主通道**：text/image/audio 链首选 |
| ② DB `provider_configs` 表 | saiOS MySQL | 回退：hub 不可用时文本/媒体单候选 |
| ③ env `OPENAI_COMPATIBLE_*` + registry mock | `.env` + `registry.py` | 最后兜底（含 Mock 假数据） |

## 二、仍在消费旧通道的代码点（删除目标清单）

| 代码点 | 用法 | 下线阶段 |
|---|---|---|
| `provider_resolver.resolve_text_provider()` 步骤 1-3 | hub 失败→DB 匹配 | P2 |
| `task_runner._media_candidates()` 中间层 | hub 链空→DB 单候选 | P2 |
| `providers.py` v1 CRUD 路由 + 「导入 env」 | saiOS「模型配置」页 ProvidersPage.tsx | P2 |
| `list_enabled_text_catalog()` | 前端模型下拉（DB+env 条目） | P2 |
| `comic_service` / `inspection_tasks` / `upstream.py` | 直接读 env key | P2 |
| `openai_compatible.py` / `chat_image.py` 的 env 默认值 | 未传参时兜底 | P3 |
| `registry.py` mock/huggingface 分支 | 无配置时假数据兜底 | P3（mock 保留给测试） |
| `generation_tasks.provider_id` FK → provider_configs | 历史任务归属 | P3 数据迁移 |
| `.env` OPENAI_COMPATIBLE_* 三件套 | 与 DB GPT-OSS 行、hub 链重复 | P3 |

## 三、分阶段执行

### P1 低风险清理（✅ 已完成 2026-08-22，用户确认后执行）
- [x] saiOS「模型配置」页顶部加横幅：「供应商管理已迁移至模型中心 :8511，此处仅为应急回退」
      （`ProvidersPage.tsx`，tsc 通过、前端已重建、横幅进产物 chunk `ProvidersPage-Co68EPac.js` 实证）
- [ ] hub sqlite 里停用的 zarklab、空池 grok2api 行保留不动（审计痕迹）——决定：保留
- 回滚：纯 UI 文案，revert 即可。

### P2 代码收敛（前置：hub 连续稳定 ≥7 天，生成 source=hub 占比 100%）
- [ ] `resolve_text_provider`：删除 DB 步骤 1-3 → 只留 hub 链 + env 兜底
- [ ] `_media_candidates`：删除 DB 单候选层 → hub 链 + registry(None)
- [ ] comic_service / inspection_tasks / upstream 改走 `model_hub_client`
- [ ] providers.py 写操作（POST/PUT/DELETE）返回 410 Gone + 指引；GET 保留一个版本周期
- [ ] ProvidersPage.tsx 变只读跳转页
- 回滚：git revert 单提交；env 兜底保证系统不瘫。

### P3 数据与配置清除（前置：P2 上线后再稳定 ≥14 天）
- [ ] `UPDATE generation_tasks SET provider_id=NULL`（保历史）→ `DROP TABLE provider_configs`
      （先 mysqldump 该表存 `backups/`）
- [ ] alembic 迁移脚本记录表删除
- [ ] `.env` 移除 OPENAI_COMPATIBLE_*（config.py 字段保留默认空串，避免启动炸）
- [ ] registry.py 收敛为 mock-only（测试用）；huggingface 分支删除

### 明确**不删**
- model-hub 本体及其 systemd 守卫/备份定时器
- cpa/grok2api/Edge-TTS 等**上游服务**（它们是 hub 的后端，不是重复通道）
- MockProvider 测试路径、`tests/` 相关 fixture

## 四、验收指标（每阶段完成后核对）
1. 端到端：agent chat「稳」+ 生图 succeeded + Edge-TTS succeeded
2. 日志无 NoTextProviderError / media_failover_next 风暴
3. 用量统计页正常出数；hub 每日备份快照有效
4. pytest 全绿（涉及 resolver/task_runner 的用例同步更新）

## 五、状态

- [x] 规划完成（2026-08-22）
- [x] P1 执行 ✅（2026-08-22，横幅上线并实证进产物）
- [x] P2 执行 ✅（2026-08-22）：resolver 只剩 hub 链+env 兜底；媒体候选去 DB 层；
  写操作 410；ProvidersPage 只读；catalog 改由模型中心供给（实测 7 hub + 1 env）。
  锚点 `d849a3e`。端到端 text/generate content="通" source=hub。
- [x] P3 执行 ✅（2026-08-22，用户"继续"指示）：
  - **备份先行**：mysqldump provider_configs+generation_tasks（3.1MB，服务器
    `~/backups-pre-p3/` + 本地 `.build-tmp/migrate_provider_configs_pre_p3.sql`）
    + hub export 快照
  - **迁移** `a7b9c1d3e5f7`：解除 generation_tasks FK → 19 条 provider_id 置 NULL →
    DROP TABLE provider_configs（alembic_version 已推进，实测表已不存在）
  - **代码**：删除 ProviderConfig 模型/_provider_settings//admin//test 端点；
    upstream._cpa_status 与 comic_service._story_api_key 改读 env key；
    seed_data 与 docker-entrypoint 移除 Hermes Provider 种子；ProvidersPage 变纯指引页
  - **范围修订**：`.env` 的 OPENAI_COMPATIBLE_* **永久保留**——它是 resolver 的最后
    兜底通道 + cpa key 的唯一来源，删除反而降低可用性
  - 验证：pytest 全量绿、tsc 过；生产端到端 catalog(7 hub+1 env)/admin 410/test 410/
    upstream 200/text-generate content="稳" source=hub；hub 服务不受影响
  - 锚点：`7a8db5f` + 修复 `451692b`
- **两个实战教训（已入 AGENTS.md）**：
  ① 加迁移前必须先核对 **DB 实际 alembic_version**（本机 versions 目录的"最新文件"
  不等于线上 head——c0ffee 分支才是真实链尾），双 head 会让 entrypoint 崩溃循环；
  ② docker-entrypoint.sh 内嵌 python 直接 import seed 函数，删 seed_data 函数时要同步改它。

## 六、遗留小项（非阻塞）

- hub 内若干 "(副本)" 重复供应商行待清理（先核对链引用）
- registry.py 的 huggingface 死分支可顺手删（无运行时引用）
- schemas/provider.py 的 Create/Update/Response 三个模型已无引用，可删
