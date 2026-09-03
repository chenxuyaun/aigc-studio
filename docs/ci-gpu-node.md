# GPU 节点（160）自建 CI — 交接文档

> 2026-09-03 落地。方向 E（工程规模化）最小版：push 触发 tsc + pytest 双 Job。

## 架构

- **bare 仓库**：`root@172.168.10.160:/data/ci/aigc-studio.git`
- **post-receive 钩子**：`hooks/post-receive`（源文件 `.build-tmp/ci/post-receive`，改动后需 sftp 上传 + chmod +x）
- **工作树**：`/data/ci/aigc-studio-work`（钩子 checkout -f 覆盖）
- **日志**：`/data/ci/aigc-studio/logs/<ts>.log`，软链 `latest.log`
- **运行环境**：conda env `ciapi`（Python 3.14.7 + 全量 api 依赖 + pytest + node 22 via conda-forge）
  - 依赖已固化：重装环境跑 `.build-tmp/ci/setup_ci_160.sh`

## 用法

```bash
git push gpu-ci refactor/v1:main   # 本地 remote "gpu-ci" 已配置（SSH 免密 key）
# push 输出末尾直接回显 CI-PASS / CI-FAIL
ssh root@172.168.10.160 cat /data/ci/aigc-studio/logs/latest.log   # 详细日志
```

## 踩坑记录

1. **npx shebang 找不到 node**：钩子必须 `export PATH=/nwh/miniconda3/envs/ciapi/bin:$PATH`（npx 是 `#!/usr/bin/env node`）。
2. **SSH key passphrase 事故**：PowerShell `-N '""'` 把 passphrase 设成字面量两个双引号字符，BatchMode 签名失败且服务端日志只见 "Accepted key"（误导到服务端排查）。**教训**：生成密钥一律用 python subprocess 传参，绕开 PowerShell 引号层。
3. **icacls 剥继承后删不了文件**：`/inheritance:r /grant:r user:R` 之后需要 `/grant:user:F` 才能删除。
4. **pytest 候选 120 条 + top-k=12**：`build_memory_injection(db, user_id, user_query, k=12)`；空 query 退化为纯时间序（旧行为）。
5. **测试共享内存库污染**：conftest 用 StaticPool 共享 SQLite，测试写库必须清理或按 user_id 断言（test_growth 曾全表 select 被 test_memory_rank 的数据打爆）。

## 相关

- 方向 B（记忆 top-k）：`apps/api/app/applications/memory_rank.py` + `ngram_embed.py`，测试 `tests/test_memory_rank.py`
- 决策背景：`docs/project-summary-for-advisor.md` 第十节
