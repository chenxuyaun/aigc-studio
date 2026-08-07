# 测试说明

- 默认跑在**独立内存 SQLite**（`tests/conftest.py`），与真实开发库完全隔离
- 限流与 SQL echo 已关闭；seed 数据走测试会话
- **MySQL 兼容性**：`pytest -m mysql` 标记的用例需要 `MYSQL_TEST_URL`（如
  `sqlite+aiosqlite://` 之外的 MySQL DSN）才能执行；当前套件全部为 SQLite 用例，
  生产切 MySQL 前建议在 CI 里加一个 MySQL 模式的 job 跑全套验证
