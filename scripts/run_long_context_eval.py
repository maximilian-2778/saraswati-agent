"""模拟数百轮输入，验证预算器不会丢掉最新请求或突破上下文上限。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services.token_budget import TokenBudgetManager, estimate_tokens  # noqa: E402


def main() -> int:
    latest = "最新请求：回忆第一章的银铃约定，并继续当前场景。"
    messages = [{"role": "system", "content": "角色规则与结构化记忆\n" * 1200}]
    for index in range(300):
        messages.append({"role": "user", "content": f"第 {index} 轮玩家行动：调查线索与人物关系。" * 8})
        messages.append({"role": "assistant", "content": f"第 {index} 轮剧情反馈：场景推进但保留既有事实。" * 8})
    messages.append({"role": "user", "content": latest})
    fitted, diagnostics = TokenBudgetManager().fit(
        messages, 12_000, {"系统规则": messages[0]["content"]}
    )
    result = {
        **diagnostics,
        "latest_message_preserved": fitted[-1]["content"] == latest,
        "actual_estimated_tokens": sum(estimate_tokens(str(item["content"])) for item in fitted),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["latest_message_preserved"] and result["actual_estimated_tokens"] <= 12_000 else 1


if __name__ == "__main__":
    raise SystemExit(main())
