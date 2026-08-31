"""Core Runtime - Audit 抽象（调用日志 / 操作审计）。

P0-6 抽离：从 services/call_logger.py 搬过来。
- log_call: 写 Provider 调用日志（不阻塞主流程，失败仅记 structlog）

P0 边界：app.services.call_logger 保留 facade。
P 阶段可补 evidence / governance 审计逻辑。
"""
from app.core.runtime.audit.call_log import log_call  # noqa: F401  # 兼容

__all__ = ["log_call"]
