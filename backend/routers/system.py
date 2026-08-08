"""健康检查、运行信息和本机设置。"""

from backend.routers._select import routes_with_tags

router = routes_with_tags({"system"})
