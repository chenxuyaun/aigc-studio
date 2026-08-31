# ruff: noqa: F403
# P3-1 薄 facade：模型实体已迁 app.data.models（表结构/字段名零变更）。
# 旧 import 路径（app.models / from app.models.X import Y）保持兼容；
# alembic env.py 的 import app.models 注册链继续生效。
from app.data.models import *
