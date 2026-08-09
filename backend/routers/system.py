"""健康检查、运行状态和本机设置。"""

from dataclasses import replace

from fastapi import APIRouter, HTTPException, Request, status

from backend.config import Settings, save_local_settings
from backend.llm import ModelProviderError, build_model_client
from backend.schemas import HealthRead, RuntimeInfo, SettingsRead, SettingsTestResult, SettingsUpdate
from backend.services.agent import AgentRuntime


router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthRead)
def health_check() -> HealthRead:
    return HealthRead()


@router.get("/runtime", response_model=RuntimeInfo)
def runtime_info(request: Request) -> RuntimeInfo:
    settings = request.app.state.settings
    model = request.app.state.model
    return RuntimeInfo(
        provider_mode=model.mode,
        model=model.model_name,
        embedding_model=settings.embedding_model,
        max_agent_steps=settings.max_agent_steps,
    )


@router.get("/settings", response_model=SettingsRead)
def read_settings(request: Request) -> SettingsRead:
    return _settings_read(request.app.state.settings)


@router.put("/settings", response_model=SettingsRead)
async def update_settings(payload: SettingsUpdate, request: Request) -> SettingsRead:
    current: Settings = request.app.state.settings
    api_key = _updated_secret(current.llm_api_key, payload.api_key, payload.clear_api_key)
    rerank_api_key = _updated_secret(
        current.rerank_api_key,
        payload.rerank_api_key,
        payload.clear_rerank_api_key,
    )
    if payload.vector_weight + payload.keyword_weight + payload.importance_weight + payload.recency_weight <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="RAG 权重之和必须大于 0。",
        )

    updated = replace(
        current,
        llm_base_url=_clean_optional(payload.llm_base_url),
        llm_api_key=api_key,
        llm_model=_clean_optional(payload.llm_model),
        embedding_model=_clean_optional(payload.embedding_model),
        temperature=payload.temperature,
        top_p=payload.top_p,
        max_output_tokens=payload.max_output_tokens,
        presence_penalty=payload.presence_penalty,
        frequency_penalty=payload.frequency_penalty,
        request_timeout=payload.request_timeout,
        max_agent_steps=payload.max_agent_steps,
        recent_message_limit=payload.recent_message_limit,
        rag_limit=payload.rag_limit,
        vector_weight=payload.vector_weight,
        keyword_weight=payload.keyword_weight,
        importance_weight=payload.importance_weight,
        recency_weight=payload.recency_weight,
        auto_summary_enabled=payload.auto_summary_enabled,
        summary_detail_mode=payload.summary_detail_mode,
        chapter_summary_size=payload.chapter_summary_size,
        arc_summary_size=payload.arc_summary_size,
        rerank_base_url=_clean_optional(payload.rerank_base_url),
        rerank_api_key=rerank_api_key,
        rerank_model=_clean_optional(payload.rerank_model),
        rerank_candidates=payload.rerank_candidates,
        context_window_tokens=payload.context_window_tokens,
        input_price_per_million=payload.input_price_per_million,
        output_price_per_million=payload.output_price_per_million,
    )
    model = build_model_client(updated)
    runtime = AgentRuntime(updated, model)
    await runtime.startup()
    save_local_settings(updated)
    previous_runtime: AgentRuntime = request.app.state.runtime
    request.app.state.settings = updated
    request.app.state.model = model
    request.app.state.runtime = runtime
    await previous_runtime.shutdown()
    return _settings_read(updated)


@router.post("/settings/test", response_model=SettingsTestResult)
async def test_settings(request: Request) -> SettingsTestResult:
    model = request.app.state.model
    if model.mode == "unconfigured":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="尚未连接模型 API，请填写地址、密钥和模型名。",
        )
    try:
        await model.check_connection()
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型连接失败：{exc}",
        ) from exc
    return SettingsTestResult(
        ok=True,
        provider_mode=model.mode,
        model=model.model_name,
        message=f"连接成功：{model.model_name}",
    )


def _updated_secret(current: str | None, incoming: str | None, clear: bool) -> str | None:
    if clear:
        return None
    return incoming.strip() if incoming and incoming.strip() else current


def _settings_read(settings: Settings) -> SettingsRead:
    key = settings.llm_api_key or ""
    rerank_key = settings.rerank_api_key or ""
    return SettingsRead(
        provider_mode=settings.provider_mode,
        llm_base_url=settings.llm_base_url,
        api_key_configured=bool(key),
        api_key_hint=f"••••{key[-4:]}" if key else None,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        temperature=settings.temperature,
        top_p=settings.top_p,
        max_output_tokens=settings.max_output_tokens,
        presence_penalty=settings.presence_penalty,
        frequency_penalty=settings.frequency_penalty,
        request_timeout=settings.request_timeout,
        max_agent_steps=settings.max_agent_steps,
        recent_message_limit=settings.recent_message_limit,
        rag_limit=settings.rag_limit,
        vector_weight=settings.vector_weight,
        keyword_weight=settings.keyword_weight,
        importance_weight=settings.importance_weight,
        recency_weight=settings.recency_weight,
        auto_summary_enabled=settings.auto_summary_enabled,
        summary_detail_mode=settings.summary_detail_mode,
        chapter_summary_size=settings.chapter_summary_size,
        arc_summary_size=settings.arc_summary_size,
        rerank_base_url=settings.rerank_base_url,
        rerank_api_key_configured=bool(rerank_key),
        rerank_api_key_hint=f"••••{rerank_key[-4:]}" if rerank_key else None,
        rerank_model=settings.rerank_model,
        rerank_candidates=settings.rerank_candidates,
        context_window_tokens=settings.context_window_tokens,
        input_price_per_million=settings.input_price_per_million,
        output_price_per_million=settings.output_price_per_million,
        active_preset_id=settings.active_preset_id,
    )


def _clean_optional(value: str | None) -> str | None:
    text = value.strip() if value else ""
    return text or None
