# 真实环境 E2E（需 docker compose 全套运行）

这些脚本直连 localhost:5000（nginx → api），调用真实模型（cpa/GPT-OSS），
验证部署后的完整链路。**与 pytest 单元测试分离**（单元测试用内存 SQLite + mock）。

## 运行

```bash
# 角色扮演全链路（35 项：角色卡/会话/流式/世界书/正则/persona/快捷回复）
python tests/e2e/test_roleplay_e2e.py

# Grok 账号导入 + 验证（用户导出 cookie 后）
python tests/e2e/grok_import.py <cookie文件>
```

## 前置
- `docker compose up -d`（api/frontend/mysql/redis）
- cpa（:8317）可用；Grok 通道需账号导入（见 grok_import.py）
- 管理员 admin/admin123（种子账号）

## 注意
- 脚本会在真实库创建/删除测试数据（会话/角色卡/世界书/正则/persona），结束后自动清理
- 失败会留下部分数据（脚本已尽量清理），可手动从数据库删除
- 限流：全局 120 req/min，连续多轮跑会触发 429（等 60s 或重启 api 清桶）
