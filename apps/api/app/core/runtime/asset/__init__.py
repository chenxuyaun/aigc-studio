"""Core Runtime - Asset 子包（资产 / 存储 / 访问控制 / 签名）。

- writer: 落库 + 终态 (write_main_asset_and_finalize) — 来自 P0-2, 文件在 core.runtime.asset_writer (不是子包)
- access: URL 签名 / 访问控制（sign_content_url / verify_content_signature / issue_media_access）— 来自 P0-7

P0 边界：app.services.media_access 保留 facade。
"""
from app.core.runtime.asset.access import (  # noqa: F401
    MediaAccess,
    issue_media_access,
    sign_content_url,
    verify_content_signature,
)
# writer 在 core.runtime.asset_writer (P0-2 的单文件), 不在子包
from app.core.runtime.asset_writer import write_main_asset_and_finalize  # noqa: F401  # 兼容

__all__ = [
    "MediaAccess",
    "issue_media_access",
    "sign_content_url",
    "verify_content_signature",
    "write_main_asset_and_finalize",
]
