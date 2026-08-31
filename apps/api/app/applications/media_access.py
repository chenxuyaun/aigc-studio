"""媒体访问（P0-7 薄 facade）。

P0-7 后：实际实现已迁到 `app.core.runtime.asset.access`。
本模块**只**保留 wrapper 以兼容现有 import 路径（路由层 / 业务代码
`from app.applications.media_access import sign_content_url, ...`）。
"""
from app.core.runtime.asset.access import (  # 兼容
    MediaAccess,
    issue_media_access,
    sign_content_url,
    verify_content_signature,
)

__all__ = ["MediaAccess", "issue_media_access", "sign_content_url", "verify_content_signature"]
