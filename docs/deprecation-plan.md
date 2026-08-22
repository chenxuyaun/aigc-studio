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
- [x] P2 执行 ✅（2026-08-22，用户"继续"指示后提前部署）：
  - 证据面：当日 6 个失败全部发生在修复部署前；修复后 0 NoTextProviderError、
    0 media_failover_next、hub NRestarts=0、守卫+备份定时器在岗
  - 变更：resolver 只剩 hub 链+env 兜底；_media_candidates 去掉 DB 层；
    providers 写操作 410；ProvidersPage 只读；catalog 改由模型中心供给
    （实测 7 hub + 1 env）
  - 测试：pytest 全量绿；tsc 通过；提交锚点 `d849a3e`（回滚 = revert 此提交并重建）
  - 端到端：登录→catalog→410→text/generate 实测 **content="通"，source=hub**
  - 附带发现：hub 内有若干 "(副本)" 重复供应商行，待下轮清点链引用后清理
- [ ] P3 执行 —— 待观察期（建议至 2026-08-29）+ 用户最终确认（DROP TABLE 等不可逆动作）：
  comic_service/inspection_tasks/upstream 的 env 直读改走 hub 也挪到本阶段一并处理
