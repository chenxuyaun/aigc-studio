"""Core Runtime - Roleplay 基础层包（P1-2 从 api/v1/roleplay.py 抽离）。

子模块：
- serializers.py  角色卡/世界书/会话 序列化（Model → dict，纯函数）
- cards.py        角色卡资产编排（列表/详情懒同步/更新/删除/导入导出）
- catalog.py      世界书/正则脚本/快捷回复/用户形象 CRUD（直连 DB 的薄查询）

P1 边界：app.api.v1.roleplay 保留薄路由（schema + handler 委托）。
P4 计划：本包随 applications/roleplay 归位。
"""
from app.core.runtime.roleplay import cards, catalog, serializers  # noqa: F401
from app.core.runtime.roleplay.serializers import (  # noqa: F401
    _character_dict,
    _chat_dict,
    _lore_dict,
)
