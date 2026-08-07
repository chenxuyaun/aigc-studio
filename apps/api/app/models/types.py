"""带时区语义的 DateTime：SQLite 存 naive UTC，读写时统一补/剥离时区。

SQLite 的 DateTime(timezone=True) 并不真正保存时区（迁移用 CURRENT_TIMESTAMP 存 naive），
导致序列化 isoformat() 无 Z 后缀、与 aware 比较崩溃。

注意：必须用 TypeDecorator 而非 DateTime 子类——SQLite 方言的 colspecs
会把 DateTime 子类替换为 sqlite.DATETIME，导致自定义 result_processor 失效。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.engine import Dialect


class TZDateTime(TypeDecorator[DateTime]):
    """读写时把 naive UTC 视为 aware；aware 值原样保留。"""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is not None and isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is not None and isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value
