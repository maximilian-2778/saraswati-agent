"""从环境变量读取应用配置。"""

import os
import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True, slots=True)
class Settings:
    """运行时配置；未提供环境变量时使用安全的本地默认值。"""

    database_url: str
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str | None
    embedding_model: str | None
    max_agent_steps: int
    recent_message_limit: int
    rag_limit: int
    temperature: float = 0.8
    top_p: float = 1.0
    max_output_tokens: int = 2048
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    request_timeout: float = 90.0
    vector_weight: float = 0.55
    keyword_weight: float = 0.25
    importance_weight: float = 0.15
    recency_weight: float = 0.05
    auto_summary_enabled: bool = True
    summary_detail_mode: str = "brief"
    chapter_summary_size: int = 8
    arc_summary_size: int = 4
    rerank_base_url: str | None = None
    rerank_api_key: str | None = None
    rerank_model: str | None = None
    rerank_candidates: int = 20
    context_window_tokens: int = 32768
    settings_file: str | None = None
    langgraph_checkpoint_path: str | None = None

    @property
    def provider_mode(self) -> str:
        """返回当前启用的模型提供方式。"""
        if self.llm_base_url and self.llm_api_key and self.llm_model:
            return "openai-compatible"
        return "demo"

    @classmethod
    def from_env(cls) -> "Settings":
        """从系统环境变量和 `.env` 文件加载配置。"""
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(exist_ok=True)
        default_db = f"sqlite:///{(data_dir / 'saraswati_v1.db').as_posix()}"

        settings_file = data_dir / "settings.json"
        checkpoint_path = data_dir / "langgraph_checkpoints.db"
        settings = cls(
            database_url=os.getenv("SARASWATI_DATABASE_URL", default_db),
            llm_base_url=_optional_env("SARASWATI_LLM_BASE_URL"),
            llm_api_key=_optional_env("SARASWATI_LLM_API_KEY"),
            llm_model=_optional_env("SARASWATI_LLM_MODEL"),
            embedding_model=_optional_env("SARASWATI_EMBEDDING_MODEL"),
            max_agent_steps=int(os.getenv("SARASWATI_MAX_AGENT_STEPS", "4")),
            recent_message_limit=int(
                os.getenv("SARASWATI_RECENT_MESSAGE_LIMIT", "16")
            ),
            rag_limit=int(os.getenv("SARASWATI_RAG_LIMIT", "5")),
            temperature=float(os.getenv("SARASWATI_TEMPERATURE", "0.8")),
            top_p=float(os.getenv("SARASWATI_TOP_P", "1.0")),
            max_output_tokens=int(os.getenv("SARASWATI_MAX_OUTPUT_TOKENS", "2048")),
            presence_penalty=float(os.getenv("SARASWATI_PRESENCE_PENALTY", "0")),
            frequency_penalty=float(os.getenv("SARASWATI_FREQUENCY_PENALTY", "0")),
            request_timeout=float(os.getenv("SARASWATI_REQUEST_TIMEOUT", "90")),
            vector_weight=float(os.getenv("SARASWATI_VECTOR_WEIGHT", "0.55")),
            keyword_weight=float(os.getenv("SARASWATI_KEYWORD_WEIGHT", "0.25")),
            importance_weight=float(os.getenv("SARASWATI_IMPORTANCE_WEIGHT", "0.15")),
            recency_weight=float(os.getenv("SARASWATI_RECENCY_WEIGHT", "0.05")),
            auto_summary_enabled=os.getenv("SARASWATI_AUTO_SUMMARY", "true").lower() == "true",
            summary_detail_mode=os.getenv("SARASWATI_SUMMARY_DETAIL", "brief"),
            chapter_summary_size=int(os.getenv("SARASWATI_CHAPTER_SUMMARY_SIZE", "8")),
            arc_summary_size=int(os.getenv("SARASWATI_ARC_SUMMARY_SIZE", "4")),
            rerank_base_url=_optional_env("SARASWATI_RERANK_BASE_URL"),
            rerank_api_key=_optional_env("SARASWATI_RERANK_API_KEY"),
            rerank_model=_optional_env("SARASWATI_RERANK_MODEL"),
            rerank_candidates=int(os.getenv("SARASWATI_RERANK_CANDIDATES", "20")),
            context_window_tokens=int(os.getenv("SARASWATI_CONTEXT_WINDOW_TOKENS", "32768")),
            settings_file=str(settings_file),
            langgraph_checkpoint_path=(
                _optional_env("SARASWATI_LANGGRAPH_CHECKPOINT_PATH")
                or str(checkpoint_path)
            ),
        )
        return load_local_settings(settings)


EDITABLE_SETTING_NAMES = {
    "llm_base_url",
    "llm_api_key",
    "llm_model",
    "embedding_model",
    "max_agent_steps",
    "recent_message_limit",
    "rag_limit",
    "temperature",
    "top_p",
    "max_output_tokens",
    "presence_penalty",
    "frequency_penalty",
    "request_timeout",
    "vector_weight",
    "keyword_weight",
    "importance_weight",
    "recency_weight",
    "auto_summary_enabled",
    "summary_detail_mode",
    "chapter_summary_size",
    "arc_summary_size",
    "rerank_base_url",
    "rerank_api_key",
    "rerank_model",
    "rerank_candidates",
    "context_window_tokens",
}


def load_local_settings(settings: Settings) -> Settings:
    """用本机设置文件覆盖环境变量默认值；文件损坏时继续使用默认值。"""
    if not settings.settings_file:
        return settings
    path = Path(settings.settings_file)
    if not path.exists():
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return settings
    if not isinstance(raw, dict):
        return settings
    values = asdict(settings)
    values.update({key: value for key, value in raw.items() if key in EDITABLE_SETTING_NAMES})
    return Settings(**values)


def save_local_settings(settings: Settings) -> None:
    """把可编辑配置保存到仅供本机使用的 JSON 文件。"""
    if not settings.settings_file:
        return
    path = Path(settings.settings_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    values: dict[str, Any] = asdict(settings)
    public_values = {key: values[key] for key in EDITABLE_SETTING_NAMES}
    path.write_text(
        json.dumps(public_values, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None
