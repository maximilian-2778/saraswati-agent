import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { AgentTrace } from "../types";

export interface TokenSlice {
  key: string;
  label: string;
  tokens: number;
  color: string;
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  inputBudget: number;
  durationMs: number;
  estimatedCostUsd: number;
  pricingConfigured: boolean;
  tokenizer: string;
  usageSource: "provider" | "tokenizer" | "heuristic" | "mixed";
  categorySource: "tokenizer" | "heuristic";
  cachedTokens: number;
  inputDifference: number;
  slices: TokenSlice[];
}

export interface TokenUsageIndex {
  byVariant: Record<string, TokenUsage>;
  byMessage: Record<string, TokenUsage>;
}

const CATEGORY_META: Record<string, { label: string; color: string }> = {
  preset: { label: "写作预设", color: "var(--token-preset)" },
  character: { label: "角色设定", color: "var(--token-character)" },
  persona: { label: "主控人物", color: "var(--token-persona)" },
  world: { label: "世界书", color: "var(--token-world)" },
  memory: { label: "记忆与 RAG", color: "var(--token-memory)" },
  history: { label: "对话上下文", color: "var(--token-history)" },
  state: { label: "剧情状态", color: "var(--token-state)" },
  system: { label: "系统规则", color: "var(--token-system)" },
  tool: { label: "工具与附加上下文", color: "var(--token-tool)" },
  protocol: { label: "消息格式与协议开销", color: "var(--token-tool)" },
  provider_other: { label: "服务商其他计量", color: "var(--token-tool)" },
  output: { label: "模型输出", color: "var(--token-output)" },
};

export function buildTokenUsageIndex(traces: AgentTrace[]): TokenUsageIndex {
  const turns = new Map<string, AgentTrace[]>();
  for (const trace of traces) turns.set(trace.turn_id, [...(turns.get(trace.turn_id) ?? []), trace]);
  const index: TokenUsageIndex = { byVariant: {}, byMessage: {} };
  for (const items of turns.values()) {
    const persisted = items.find((item) => item.event_type === "response_persisted");
    const context = items.find((item) => item.event_type === "context_built");
    if (!persisted || !context) continue;
    const persistedPayload = asRecord(persisted.payload);
    const messageId = stringValue(persistedPayload.assistant_message_id);
    if (!messageId) continue;
    const metrics = items
      .filter((item) => ["model_response", "forced_model_response", "model_error"].includes(item.event_type))
      .map((item) => asRecord(item.payload));
    const budget = asRecord(asRecord(context.payload).token_budget);
    const sections = Array.isArray(budget.sections) ? budget.sections.map(asRecord) : [];
    const grouped = new Map<string, number>();
    for (const section of sections) {
      if (section.enabled === false) continue;
      const tokens = numberValue(section.estimated_tokens);
      if (tokens <= 0) continue;
      const category = sectionCategory(stringValue(section.key));
      grouped.set(category, (grouped.get(category) ?? 0) + tokens);
    }
    const inputTokens = metrics.reduce((total, item) => total + numberValue(item.input_tokens), 0)
      || numberValue(budget.estimated_input_tokens);
    const outputTokens = metrics.reduce((total, item) => total + numberValue(item.output_tokens), 0);
    const totalTokens = metrics.reduce((total, item) => total + (
      numberValue(item.total_tokens) || numberValue(item.input_tokens) + numberValue(item.output_tokens)
    ), 0) || inputTokens + outputTokens;
    const knownInput = [...grouped.values()].reduce((sum, value) => sum + value, 0);
    const inputDifference = inputTokens - knownInput;
    if (inputDifference > 0) grouped.set("protocol", inputDifference);
    const slices = [...grouped.entries()].map(([key, tokens]) => ({ key, tokens, ...CATEGORY_META[key] }));
    if (outputTokens > 0) slices.push({ key: "output", tokens: outputTokens, ...CATEGORY_META.output });
    const providerOther = totalTokens - inputTokens - outputTokens;
    if (providerOther > 0) slices.push({ key: "provider_other", tokens: providerOther, ...CATEGORY_META.provider_other });
    const tokenizer = stringValue(budget.tokenizer) || "本地估算器";
    const declaredSources = metrics.map((item) => stringValue(item.usage_source));
    const usageSource = declaredSources.some(Boolean)
      ? resolveUsageSource(declaredSources)
      : tokenizer.startsWith("tiktoken:") ? "tokenizer" : "heuristic";
    const usage: TokenUsage = {
      inputTokens,
      outputTokens,
      totalTokens,
      inputBudget: numberValue(budget.input_budget),
      durationMs: metrics.reduce((total, item) => total + numberValue(item.duration_ms), 0),
      estimatedCostUsd: metrics.reduce((total, item) => total + numberValue(item.estimated_cost_usd), 0),
      pricingConfigured: metrics.some((item) => item.pricing_configured === true),
      tokenizer,
      usageSource,
      categorySource: tokenizer.toLowerCase().includes("heuristic") || tokenizer === "本地估算器" ? "heuristic" : "tokenizer",
      cachedTokens: metrics.reduce((total, item) => total + numberValue(item.cached_tokens), 0),
      inputDifference,
      slices,
    };
    index.byMessage[messageId] = usage;
    const variantId = stringValue(persistedPayload.variant_id);
    if (variantId) index.byVariant[variantId] = usage;
  }
  return index;
}

export function MessageTokenUsage({ usage }: { usage: TokenUsage }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    window.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", close); window.removeEventListener("keydown", escape); };
  }, [open]);
  return <span className="message-token-usage" ref={rootRef}>
    <button type="button" className="message-token-trigger" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
      {usageSourceLabel(usage.usageSource)} {compactTokens(usage.totalTokens)} Token
    </button>
    {open && <div className="token-usage-popover">
      <header><div><small>本条回答 · {usageSourceDescription(usage.usageSource)}</small><strong>Token 构成</strong></div></header>
      <TokenDonut slices={usage.slices} center={<><strong>{compactTokens(usage.totalTokens)}</strong><small>总 Token</small></>} />
      <div className="token-usage-metrics">
        <span><small>输入</small><strong>{usage.inputTokens.toLocaleString()}</strong></span>
        <span><small>输出</small><strong>{usage.outputTokens.toLocaleString()}</strong></span>
        <span><small>耗时</small><strong>{formatDuration(usage.durationMs)}</strong></span>
        <span><small>费用</small><strong>{usage.pricingConfigured ? `$${usage.estimatedCostUsd.toFixed(5)}` : "未设置"}</strong></span>
      </div>
      <footer>
        分类：{usage.categorySource === "tokenizer" ? `Tokenizer（${usage.tokenizer}）` : "估算（heuristic）"}
        {usage.cachedTokens > 0 ? ` · 缓存 ${usage.cachedTokens.toLocaleString()} Token` : ""}
        {usage.inputDifference < 0 ? ` · 分类本地计数比服务商输入高 ${Math.abs(usage.inputDifference).toLocaleString()}` : ""}
        {usage.inputBudget ? ` · 输入预算占用 ${(usage.inputTokens / usage.inputBudget * 100).toFixed(1)}%` : ""}
      </footer>
    </div>}
  </span>;
}

export function TokenDonut({ slices, center, className = "" }: { slices: TokenSlice[]; center: ReactNode; className?: string }) {
  const total = Math.max(1, slices.reduce((sum, item) => sum + item.tokens, 0));
  const [active, setActive] = useState<string | null>(null);
  const activeSlice = slices.find((item) => item.key === active);
  const segments = useMemo(() => {
    let offset = 0;
    return slices.map((item) => {
      const percent = item.tokens / total * 100;
      const segment = { ...item, percent, offset: -offset };
      offset += percent;
      return segment;
    });
  }, [slices, total]);
  return <div className={`token-donut-layout ${className}`}>
    <div className="token-donut-figure">
      <svg viewBox="0 0 120 120" role="img" aria-label="Token 占比环形图">
        <circle className="token-ring-track" cx="60" cy="60" r="46" pathLength="100" />
        {segments.map((item) => <circle
          key={item.key}
          className={`token-ring-segment${active === item.key ? " active" : ""}`}
          cx="60" cy="60" r="46" pathLength="100"
          stroke={item.color}
          strokeDasharray={`${item.percent} ${100 - item.percent}`}
          strokeDashoffset={item.offset}
          style={{ "--token-delay": `${segments.indexOf(item) * 45}ms` } as CSSProperties}
          onMouseEnter={() => setActive(item.key)} onMouseLeave={() => setActive(null)}
        />)}
      </svg>
      <div className="token-donut-center">{activeSlice ? <><strong>{activeSlice.tokens.toLocaleString()}</strong><small>{activeSlice.label} · {(activeSlice.tokens / total * 100).toFixed(1)}%</small></> : center}</div>
    </div>
    <div className="token-donut-legend">
      {slices.map((item) => <button type="button" key={item.key} onMouseEnter={() => setActive(item.key)} onMouseLeave={() => setActive(null)}>
        <i style={{ background: item.color }} /><span>{item.label}</span><strong>{item.tokens.toLocaleString()}</strong>
      </button>)}
    </div>
  </div>;
}

function sectionCategory(key: string) {
  if (key.startsWith("preset:")) return "preset";
  if (key === "characters") return "character";
  if (key === "persona") return "persona";
  if (key === "world_book") return "world";
  if (["summary", "rag"].includes(key)) return "memory";
  if (["recent", "latest_user"].includes(key)) return "history";
  if (["scene", "timeline", "evolving_world", "state"].includes(key)) return "state";
  return "system";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function resolveUsageSource(sources: string[]): TokenUsage["usageSource"] {
  const valid = sources.filter((source) => ["provider", "tokenizer", "heuristic"].includes(source));
  if (!valid.length) return "heuristic";
  return valid.every((source) => source === valid[0]) ? valid[0] as TokenUsage["usageSource"] : "mixed";
}
function usageSourceLabel(source: TokenUsage["usageSource"]) {
  return source === "provider" ? "实际" : source === "tokenizer" ? "Tokenizer" : source === "mixed" ? "混合" : "估算";
}
function usageSourceDescription(source: TokenUsage["usageSource"]) {
  return source === "provider" ? "服务商实际值" : source === "tokenizer" ? "Tokenizer 本地计算" : source === "mixed" ? "实际值与本地计算混合" : "heuristic 估算";
}
function numberValue(value: unknown) { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : 0; }
function stringValue(value: unknown) { return typeof value === "string" ? value : ""; }
function compactTokens(value: number) { return value >= 1000 ? `${(value / 1000).toFixed(value >= 10000 ? 1 : 2)}k` : value.toLocaleString(); }
function formatDuration(value: number) { return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${Math.round(value)}ms`; }
