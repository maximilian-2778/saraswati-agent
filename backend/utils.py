"""后端各模块共享的小型序列化工具。"""

import json
import re
from typing import Any


def json_dumps(value: Any) -> str:
    """将 Python 值稳定地序列化为可存入数据库的 JSON。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def json_loads(value: str | None) -> Any:
    """读取数据库中的 JSON；空值保持为 None。"""
    if value is None:
        return None
    return json.loads(value)


def clean_story_text(value: str) -> str:
    """删除思维链、插件状态块和注释，只保留适合进入记忆的剧情正文。"""
    text = str(value or "")
    text = re.sub(
        r"<(?:think|thinking|thinging)\b[^>]*>[\s\S]*?</(?:think|thinking|thinging)\s*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"<(?:think|thinking|thinging)\b[^>]*>[\s\S]*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<!--[\s\S]*?-->", "", text)
    text = re.sub(r"<horae[^>]*>[\s\S]*?</horae[^>]*>", "", text, flags=re.IGNORECASE)

    starts = list(re.finditer(r"<bbs_start\b", text, flags=re.IGNORECASE))
    if starts:
        text = text[starts[-1].start():]
    end = re.search(r"</bbs_end>", text, flags=re.IGNORECASE)
    if end:
        text = text[:end.end()]
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
