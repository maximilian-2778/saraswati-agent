"""精确状态、审核建议、一致性检查和运行记录。"""

from backend.routers._select import routes_with_tags

router = routes_with_tags({"state", "audit", "trace"})
