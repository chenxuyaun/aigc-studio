# AIGC Studio 深度分析汇总（2026-08-08）

> 来源：4 个并行子代理只读深挖（后端 / 前端 / 数据性能 / 安全可靠性），主 agent 复核关键 P0。
> 原始报告：`.cowork-temp/deep/{backend,frontend,data-perf,security}.md`
> 状态：全部发现附文件:行证据；未改动任何文件。

## 一、总体结论

**系统健康度：中上**。应用层（鉴权/错误结构/上传/任务可靠性）扎实，主要短板：
1. **暴露面**（安全 P0×4）：Redis/MySQL/SillyTavern/memory-core 全部 0.0.0.0 直出，Redis 实测无密码（主 agent 已复核：`redis-cli ping` → PONG）
2. **MCP 工具层越权**（安全 P0-1）：工具集无用户隔离/admin 校验，可读全库私密数据 + 触发注册批次
3. **热路径 N+1 与缺索引**（后端/数据性能交叉确认）
4. **前端巨型组件与重复**（WorkflowCanvasEditor 1559 行 / 流式聊天 4 份重复）

## 二、P0 优先修复清单（6 项）

| # | 问题 | 证据 | 工作量 |
|---|---|---|---|
| 1 | **MCP 工具层越权**：list_tasks/get_asset/search_prompts/trigger_register_batch 等无 user_id 过滤、无 admin 校验 | `mcp/server.py:101-196,403-409`、`services/agent_chat.py:64` | 半天 |
| 2 | **Redis 无密码 + 6379 暴露**（实测 PONG） | `compose.yaml` ports、实测 CONFIG GET requirepass 空 | 10 分钟 |
| 3 | **SillyTavern 零鉴权 8001 暴露**（实测 200） | `deploy/sillytavern/config.yaml` whitelist/basicAuth 全关 | 10 分钟 |
| 4 | **MySQL 3306 暴露 + changeme 默认口令兜底** | `compose.yaml` | 10 分钟 |
| 5 | **API 8002 宿主直出**（/mcp、/api/v1/* 不经 nginx） | `compose.yaml` ports | 10 分钟 |
| 6 | **memory-core 8420 暴露 + TDAI_MEMORY_API_KEY 空时无鉴权** | `compose.yaml`、`deploy/tdai-gateway.yaml` | 10 分钟 |

**说明**：P0 中 2-6 属于**同一类**（容器端口暴露面），一次 compose 收口全部解决；1 是代码越权需单独修。

## 三、P1 批次（交叉验证的高价值项）

### 后端 + 性能（合并）
- **N+1**：`roleplay._load_cards` 每角色 2 查询（聊天热路径）、`roleplay.py:216` 列表逐行 db.get → 批量 IN（`services/roleplay.py:164-173`）
- **knowledge/ask 每次全量拉 AgentList 2000+100+50 行**（`api/v1/knowledge.py:140-152`）
- **缺索引**：prompts `created_at/use_count`（12k 行 filesort，page=600 实测 113ms）、asmr `rate_average/dl_count/price`（56k 行 filesort）、generation_tasks `created_at`（dashboard 7 次 COUNT）
- **请求体无长度上限**：generation/distill/roleplay schemas 全裸 str（`schemas/generation.py`）
- **Celery 缺锁/重试**：`distill_character_task` 无重试无幂等、`serial_tick` 无 Redis 锁（双发重复建章）、`asmr_sync_task` 无跨进程锁
- **错误结构旁路 5 处**：`register_result` 200+not_found、`agentlist/sync` 200+ok:false、`knowledge/ask` success 包 error
- **inspection_tasks 空 try 块**（`tasks/inspection_tasks.py:146-151`）

### 前端
- **WorkflowCanvasEditor 1559 行 + "运行"是假模拟**（无后端调用，与列表页真实 /run 不一致）→ 拆分 + 接通真实接口
- **RoleplayPage 981 行** → useRoleplayChat/useRoleplayData 拆分
- **流式聊天 4 份重复 + 卸载不 abort**（AgentChat/SkillChat/TextGen/Roleplay）→ useStreamChat hook
- **a11y 集中修复**：icon-only 收藏/发送按钮无 aria-label（AgentsPage:313、WorkflowsPage:308、RoleplayPage:901）
- **admin 路由无客户端守卫**（`Routes.tsx:83-96`，直接输 URL 可进）
- **window.confirm 8 处** → ConfirmDialog 统一

### 安全
- **签名 URL 4h 不绑用户**（`services/media_access.py`，叠加 MCP 越权可放大）→ TTL≤600s + HMAC 纳入 user_id + 密钥分离
- **XFF 绕过限流**（`deploy/systemd/aigc-api.service` `--proxy-headers` + TRUST_PROXY 未设）
- **生成类无 per-user 限流**（仅 global 120/min）+ 提示词无 max_length
- **cover 代理 SSRF 面**（`asmr.py:156-190` 无 host 校验）
- **备份缺 tdai_data/sillytavern_data 卷 + 无加密**（`tasks/backup_tasks.py` 只备 mysql+storage）
- **upstream/status 任意用户可见账号池**（建议 admin）

## 四、P2 观察项（记录备查）

- 分页/可见性/收藏四件套跨 4 模块重复 → 抽 `repositories/catalog.py`
- 胖路由：workflows/photography/upstream/asmr-similar 下沉 services
- 深分页 OFFSET → keyset（数据量大后）
- 限流进程内实现（多进程可绕过）→ Redis 计数
- celery 结果键 ~6k/天（`ignore_result=True`）
- prompts 列表返回 content 大列（34.7KB/页）→ 投影瘦身
- bundle：MF 共享运行时首屏 ~460KB（standalone 减负）
- 好感度 affinity 只存 localStorage（跨端丢失）
- TextGenPage ensureSession 双写 localStorage 风险
- 08-05 备份 4 个同日冗余目录（~100MB）
- Redis 无 maxmemory（设 256MB + allkeys-lru）
- frontend/sillytavern 容器无 healthcheck
- JWT/APP_SECRET 守卫无长度校验（≥32 建议）

## 五、建议修复路线（3 批）

**批次 1（今天可完成，安全收口 + 零风险）**
1. compose 端口收口：redis/mysql/sillytavern/memory-core/api 去 0.0.0.0 宿主映射（或绑 127.0.0.1）+ Redis requirepass + 校验 TDAI_MEMORY_API_KEY 非空 + MySQL 非默认口令断言
2. MCP 工具层加 user_id 过滤 + trigger_register_batch/get_upstream_status 加 admin 校验
3. 签名 URL TTL 4h→600s + HMAC 纳入 user_id
4. schemas 补 max_length（generation/roleplay/distill/auth）
5. upstream/status 收 admin；inspection 空 try 清理

**批次 2（性能 + 可靠性）**
6. 三个缺索引批次（prompts/asmr/generation_tasks）+ dashboard 单次 GROUP BY
7. roleplay N+1 批量 IN；knowledge/ask 按需投影
8. distill 重试+幂等、serial_tick Redis 锁、asmr_sync 跨进程锁
9. 错误结构旁路 5 处统一；prompts 列表投影排除 content

**批次 3（体验/架构，可排期）**
10. WorkflowCanvasEditor 拆分 + 真实 /run；RoleplayPage 拆分
11. useStreamChat hook（4 页收敛 + 卸载 abort）；a11y aria-label 全量补齐
12. 前端 admin 路由守卫；window.confirm → ConfirmDialog
13. 备份扩展（tdai/sillytavern 卷 + 加密 + 告警）
14. 可见性/收藏/分页共享 helper；流式限流 per-user

## 六、亮点（保持）

- REST 对象级鉴权高度一致（owner/admin + 统一 404 防枚举）
- 上传三件套（分级限读 + 魔数 + 声明类型）+ 路径穿越防护
- 登录防枚举 + 刷新令牌 jti 轮换重放失效
- 错误结构统一 + 校验不回显原始输入 + request_id 透传
- 任务工程化：drain 原子抢占、redis_lock、挂起自动重启、启动恢复
- 降级文化：memory/cache 全链路静默降级
- apiClient 401 队列/重试、usePrivateMediaUrl 生命周期管理
- 全仓零 TODO/FIXME/HACK

## 七、实测数据快照（data-perf）

- MySQL 43 表 ~200MB；asmr_works 126.8MB(56k 行)/prompts 55.6MB(12k 行)
- API 常规路径 <30ms；冷缓存 LIKE 545ms；深分页 page=600 113ms
- 备份每日 02:00 UTC 正常（最新 64.8MB），14 天保留
- 前端 dist 2.32MB，PWA precache 2.3MB
