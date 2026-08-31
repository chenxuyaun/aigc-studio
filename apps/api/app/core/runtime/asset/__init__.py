"""Core Runtime - Asset 子包。

- access: URL 签名 / 访问控制（sign_content_url / verify_content_signature / issue_media_access）— 来自 P0-7

注意: write_main_asset_and_finalize 在 core.runtime.asset_writer (sibling 单文件, 不是子包),
       不在本 __init__.py 导入 (否则触发 asset_writer 部分初始化的循环依赖)。
       用户请直接 from app.core.runtime.asset_writer import write_main_asset_and_finalize。
"""
from app.core.runtime.asset.access import (  # noqa: F401
    MediaAccess,
    issue_media_access,
    sign_content_url,
    verify_content_signature,
)

__all__ = [
    "MediaAccess",
    "issue_media_access",
    "sign_content_url",
    "verify_content_signature",
]
