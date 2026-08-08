"""运行固定 RAG 数据集并输出 Recall@K 与 MRR。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.evaluation import retrieval_metrics  # noqa: E402


def main() -> int:
    cases = json.loads((ROOT / "evals" / "rag_cases.json").read_text(encoding="utf-8"))
    metrics = retrieval_metrics(cases, k=1)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0 if metrics["recall@1"] >= 0.8 and metrics["mrr"] >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
