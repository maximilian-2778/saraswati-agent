"""后端各模块共享的小型序列化工具。"""

import json
from typing import Any


def json_dumps(value: Any) -> str:
    """将 Python 值稳定地序列化为可存入数据库的 JSON。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def json_loads(value: str | None) -> Any:
    """读取数据库中的 JSON；空值保持为 None。"""
    if value is None:
        return None
    return json.loads(value)
