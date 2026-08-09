import { useEffect, useState } from "react";
import { api } from "../api";
import { AvatarPicker } from "./Avatar";
import { HelpTip } from "./HelpTip";
import { DEFAULT_UI_PREFERENCES } from "../hooks/useUiPreferences";
import type { ThemeName, UiPreferences } from "../hooks/useUiPreferences";
import type { AppSettings, RuntimeInfo, SettingsUpdate } from "../types";

type SettingsTab = "model" | "generation" | "agent" | "appearance";

export function SettingsModal({
  preferences,
  onPreferences,
  onRuntime,
  onClose,
}: {
  preferences: UiPreferences;
  onPreferences: (value: UiPreferences) => void;
  onRuntime: (value: RuntimeInfo) => void;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("model");
  const [current, setCurrent] = useState<AppSettings | null>(null);
  const [form, setForm] = useState<SettingsUpdate | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [rerankApiKey, setRerankApiKey] = useState("");
  const [draftPreferences, setDraftPreferences] = useState(preferences);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    void refreshRuntimeSettings()
      .catch((reason) => setNotice({ kind: "error", text: errorMessage(reason) }));
  }, []);

  async function refreshRuntimeSettings() {
    const settings = await api.settings();
    setCurrent(settings);
    setForm(settingsToUpdate(settings));
    onRuntime(await api.runtime());
  }

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  function updateField<K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) {
    setForm((valueBefore) => valueBefore ? { ...valueBefore, [key]: value } : valueBefore);
  }

  async function saveSettings(showSavedMessage = true): Promise<boolean> {
    if (!form) return false;
    try {
      setBusy(true);
      setNotice(null);
      const saved = await api.updateSettings({
        ...form,
        api_key: apiKey.trim() || null,
        rerank_api_key: rerankApiKey.trim() || null,
      });
      const runtimeInfo = await api.runtime();
      setCurrent(saved);
      setForm(settingsToUpdate(saved));
      setApiKey("");
      setRerankApiKey("");
      onPreferences(draftPreferences);
      onRuntime(runtimeInfo);
      if (showSavedMessage) setNotice({ kind: "ok", text: "设置已保存并立即生效。" });
      return true;
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function testConnection() {
    const saved = await saveSettings(false);
    if (!saved) return;
    try {
      setBusy(true);
      const result = await api.testSettings();
      setNotice({ kind: "ok", text: result.message });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy(false);
    }
  }

  function restoreDefaults() {
    if (!form) return;
    setForm({
      ...form,
      temperature: 0.8,
      top_p: 1,
      max_output_tokens: 2048,
      presence_penalty: 0,
      frequency_penalty: 0,
      request_timeout: 90,
      max_agent_steps: 4,
      recent_message_limit: 16,
      rag_limit: 5,
      vector_weight: 0.55,
      keyword_weight: 0.25,
      importance_weight: 0.15,
      recency_weight: 0.05,
      rerank_candidates: 20,
      context_window_tokens: 32768,
      input_price_per_million: 0,
      output_price_per_million: 0,
    });
    setDraftPreferences(DEFAULT_UI_PREFERENCES);
    setNotice({ kind: "ok", text: "已恢复推荐值，点击“保存并应用”后生效。" });
  }

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "model", label: "模型 API" },
    { id: "generation", label: "生成参数" },
    { id: "agent", label: "对话与记忆" },
    { id: "appearance", label: "界面与隐私" },
  ];
  const weightTotal = form
    ? form.vector_weight + form.keyword_weight + form.importance_weight + form.recency_weight
    : 0;

  return (
    <div className="settings-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header className="settings-header">
          <div><p className="eyebrow">SARASWATI CONTROL</p><h2 id="settings-title">设置中心</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="关闭设置">×</button>
        </header>
        <div className="settings-layout">
          <nav className="settings-nav">
            {tabs.map((tab) => (
              <button key={tab.id} className={activeTab === tab.id ? "active" : ""} onClick={() => setActiveTab(tab.id)}>
                {tab.label}
              </button>
            ))}
            <button className="restore-button" onClick={restoreDefaults} disabled={!form || busy}>恢复推荐值</button>
          </nav>
          <div className="settings-content">
            {!form || !current ? (
              <p className="settings-loading">正在读取本机设置…</p>
            ) : activeTab === "model" ? (
              <div className="settings-section">
                <SettingsHeading title="模型 API" />
                <label className="settings-field"><span>API 地址 <HelpTip text="模型服务的接口根地址。OpenAI 兼容服务通常以 /v1 结尾；不要填写具体的 /chat/completions 路径。" /></span><input value={form.llm_base_url ?? ""} onChange={(e) => updateField("llm_base_url", e.target.value || null)} placeholder="https://api.example.com/v1" /></label>
                <label className="settings-field"><span>API Key <HelpTip text="模型服务用于验证身份的密钥。保存后只存放在本机设置文件，页面不会再次读取明文。" /></span><small>{current.api_key_configured ? `已保存：${current.api_key_hint}；留空表示保持不变` : "尚未配置"}</small><input type="password" autoComplete="off" value={apiKey} onChange={(e) => { setApiKey(e.target.value); if (e.target.value) updateField("clear_api_key", false); }} placeholder={current.api_key_configured ? "••••••••（保持不变）" : "sk-..."} /></label>
                {current.api_key_configured && <label className="check-row danger-check"><input type="checkbox" checked={form.clear_api_key} onChange={(e) => updateField("clear_api_key", e.target.checked)} /><span>保存时删除已存储的 API Key</span></label>}
                <div className="settings-grid">
                  <label className="settings-field"><span>对话模型 <HelpTip text="负责角色回复、工具选择和结构化剧情整理。这里必须填写服务商实际提供的模型 ID。" /></span><input value={form.llm_model ?? ""} onChange={(e) => updateField("llm_model", e.target.value || null)} placeholder="模型名称" /></label>
                  <label className="settings-field"><span>Embedding 模型 <HelpTip text="把长期记忆转换为向量，用于按语义寻找旧剧情。留空时使用本地哈希向量，效果较弱但无需额外接口。" /></span><input value={form.embedding_model ?? ""} onChange={(e) => updateField("embedding_model", e.target.value || null)} placeholder="可选" /></label>
                </div>
                <NumberSetting label="请求超时" note="单次模型请求最多等待多少秒。大型模型或网络较慢时可以提高；超时后本轮会报错，不会无限等待。" value={form.request_timeout} min={5} max={600} step={5} onChange={(value) => updateField("request_timeout", value)} />
                <div className="settings-grid">
                  <NumberSetting label="输入单价" note="服务商对输入内容的价格，单位为美元/百万 Token。只用于本地费用估算，填 0 表示不计算。" value={form.input_price_per_million} min={0} max={10000} step={0.01} onChange={(value) => updateField("input_price_per_million", value)} compact />
                  <NumberSetting label="输出单价" note="服务商对模型回复的价格，单位为美元/百万 Token。只用于本地费用估算，填 0 表示不计算。" value={form.output_price_per_million} min={0} max={10000} step={0.01} onChange={(value) => updateField("output_price_per_million", value)} compact />
                </div>
                <div className={`connection-state ${current.provider_mode === "unconfigured" ? "unconfigured" : "configured"}`}><span className="status-dot" /><div><strong>{current.provider_mode === "unconfigured" ? "尚未连接模型 API" : "模型 API 已配置"}</strong><small>{current.provider_mode === "unconfigured" ? "填写地址、Key 和模型名后保存并测试" : current.llm_model}</small></div></div>
              </div>
            ) : activeTab === "generation" ? (
              <div className="settings-section">
                <SettingsHeading title="生成参数" />
                <NumberSetting label="温度 Temperature" note="控制随机性。数值越高，表达越活跃但越容易偏离设定；数值越低，回复更稳定但可能单调。角色扮演通常从 0.7～1.0 开始。" value={form.temperature} min={0} max={2} step={0.05} onChange={(value) => updateField("temperature", value)} />
                <NumberSetting label="Top-P" note="控制模型可选择的候选词范围。越低越保守，通常保持 1；一般只重点调整温度或 Top-P 中的一项。" value={form.top_p} min={0.05} max={1} step={0.05} onChange={(value) => updateField("top_p", value)} />
                <NumberSetting label="最大输出 Token" note="单次回复允许生成的最大长度。它是上限而不是固定消耗；设得过低可能截断回复，过高会增加最坏情况下的费用。" value={form.max_output_tokens} min={64} max={32768} step={64} onChange={(value) => updateField("max_output_tokens", Math.round(value))} />
                <NumberSetting label="Presence Penalty" note="根据某个词是否已经出现来施加惩罚。正值鼓励引入新内容，过高可能让剧情频繁跳题；0 表示不额外干预。" value={form.presence_penalty} min={-2} max={2} step={0.1} onChange={(value) => updateField("presence_penalty", value)} />
                <NumberSetting label="Frequency Penalty" note="根据词语已经出现的次数施加惩罚。正值可减少重复措辞，过高会破坏自然表达；0 表示不额外干预。" value={form.frequency_penalty} min={-2} max={2} step={0.1} onChange={(value) => updateField("frequency_penalty", value)} />
              </div>
            ) : activeTab === "agent" ? (
              <div className="settings-section">
                <SettingsHeading title="对话与记忆" detail="" />
                <NumberSetting label="最大处理步数" note="一轮对话中模型和工具最多往返多少次。步数越高，复杂任务更容易完成，但可能增加延迟和费用；普通对话通常 4 步足够。" value={form.max_agent_steps} min={1} max={12} step={1} onChange={(value) => updateField("max_agent_steps", Math.round(value))} />
                <NumberSetting label="近期原文条数" note="每轮直接发送给模型的最近消息数量。增加后短期连贯性更好，但会占用更多上下文；更早内容由摘要和 RAG 补充。" value={form.recent_message_limit} min={2} max={100} step={2} onChange={(value) => updateField("recent_message_limit", Math.round(value))} />
                <NumberSetting label="相关回忆数量" note="RAG 每轮最多召回多少条旧记忆。太少可能漏掉前情，太多会混入无关细节并增加 Token 消耗。" value={form.rag_limit} min={1} max={30} step={1} onChange={(value) => updateField("rag_limit", Math.round(value))} />
                <div className="subsection-title"><strong>自动记忆整理 <HelpTip text="把每轮剧情压缩成楼层摘要，再按数量合并为章节和篇章总结，用于超长故事的长期记忆。" /></strong></div>
                <label className="check-row"><input type="checkbox" checked={form.auto_summary_enabled} onChange={(e) => updateField("auto_summary_enabled", e.target.checked)} /><span><strong>启用自动摘要 <HelpTip text="角色回复完成后额外调用模型整理本轮变化。关闭后不会自动产生新的剧情摘要，但已有记忆仍会保留。" /></strong></span></label>
                <label className="settings-field"><span>默认摘要模式 <HelpTip text="精简模式保留主要事件，消耗较低；详细模式会记录更多人物、物品和情节细节，也会使用更多 Token。" /></span><select value={form.summary_detail_mode} onChange={(e) => updateField("summary_detail_mode", e.target.value as "brief" | "detailed")}><option value="brief">精简</option><option value="detailed">详细</option></select></label>
                <div className="settings-grid"><NumberSetting label="每章楼层数" note="累计多少条楼层摘要后自动生成一次章节总结。数值小会更频繁整理，数值大则保留更多细节后再合并。" value={form.chapter_summary_size} min={2} max={50} step={1} onChange={(value) => updateField("chapter_summary_size", Math.round(value))} compact /><NumberSetting label="每篇章节数" note="累计多少个章节总结后生成更高层的篇章概览，用于几百轮以上的长期剧情。" value={form.arc_summary_size} min={2} max={20} step={1} onChange={(value) => updateField("arc_summary_size", Math.round(value))} compact /></div>
                <div className="subsection-title"><strong>混合 RAG 权重 <HelpTip text="控制检索旧记忆时各类分数所占比例。系统会自动归一化，不要求四项相加等于 1。" /></strong><small>当前总和 {weightTotal.toFixed(2)}</small></div>
                <div className="settings-grid">
                  <NumberSetting label="向量语义" note="比较当前消息和记忆在含义上是否相近，适合找用词不同但意思相关的旧剧情。" value={form.vector_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("vector_weight", value)} compact />
                  <NumberSetting label="关键词" note="比较人物名、地点、物品和其他字面线索是否重合，适合召回专有名词明确的记忆。" value={form.keyword_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("keyword_weight", value)} compact />
                  <NumberSetting label="记忆重要度" note="提高被标记为重要的记忆排名，使关键约定和核心设定更容易被召回。" value={form.importance_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("importance_weight", value)} compact />
                  <NumberSetting label="时间新鲜度" note="让较新的记忆获得额外分数。设得过高会让早期重要剧情难以召回。" value={form.recency_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("recency_weight", value)} compact />
                </div>
                {weightTotal <= 0 && <p className="field-error">至少有一项 RAG 权重必须大于 0。</p>}
                <div className="subsection-title"><strong>独立 Reranker <HelpTip text="对 RAG 初步找出的候选记忆重新排序。它通常能提高召回准确度，但会增加一次接口请求；不配置时自动使用本地混合分数。" /></strong></div>
                <label className="settings-field"><span>Rerank API 地址 <HelpTip text="Reranker 服务地址，可填写服务根地址或完整的 /rerank 路径。它可以与对话模型使用不同供应商。" /></span><input value={form.rerank_base_url ?? ""} onChange={(e) => updateField("rerank_base_url", e.target.value || null)} placeholder="https://api.example.com/v1" /></label>
                <div className="settings-grid"><label className="settings-field"><span>Rerank 模型 <HelpTip text="服务商提供的重排序模型 ID。只有地址、模型和密钥都配置完整时才会启用。" /></span><input value={form.rerank_model ?? ""} onChange={(e) => updateField("rerank_model", e.target.value || null)} placeholder="reranker-model" /></label><label className="settings-field"><span>Rerank API Key <HelpTip text="访问 Reranker 服务的密钥，可以和对话模型的 API Key 不同。" /></span><small>{current.rerank_api_key_configured ? `已保存：${current.rerank_api_key_hint}；留空保持不变` : "尚未配置"}</small><input type="password" value={rerankApiKey} onChange={(e) => { setRerankApiKey(e.target.value); if (e.target.value) updateField("clear_rerank_api_key", false); }} placeholder="可与对话模型使用不同密钥" /></label></div>
                {current.rerank_api_key_configured && <label className="check-row danger-check"><input type="checkbox" checked={form.clear_rerank_api_key} onChange={(e) => updateField("clear_rerank_api_key", e.target.checked)} /><span>保存时删除 Rerank API Key</span></label>}
                <NumberSetting label="精排候选数" note="本地初筛后送给 Reranker 的记忆数量。提高可能改善漏召回，但会增加请求体和精排费用。" value={form.rerank_candidates} min={2} max={100} step={1} onChange={(value) => updateField("rerank_candidates", Math.round(value))} />
                <NumberSetting label="上下文窗口" note="所用模型支持的总 Token 上限，必须与服务商规格一致。系统会先预留最大输出 Token，再用剩余空间装入角色、世界书、记忆和对话。" value={form.context_window_tokens} min={4096} max={2000000} step={1024} onChange={(value) => updateField("context_window_tokens", Math.round(value))} />
              </div>
            ) : (
              <div className="settings-section">
                <SettingsHeading title="界面" />
                <div className="settings-field"><span>用户头像 <HelpTip text="未设置故事主控人物头像时，对话中的用户消息使用这里的图片。只保存在当前浏览器。" /></span><AvatarPicker value={draftPreferences.userAvatar} fallback="你" onChange={(value) => setDraftPreferences((before) => ({ ...before, userAvatar: value }))} /></div>
                <label className="settings-field"><span>配色主题 <HelpTip text="只改变客户端显示效果，不会写入故事，也不会发送给模型。" /></span><select value={draftPreferences.theme} onChange={(e) => setDraftPreferences((value) => ({ ...value, theme: e.target.value as ThemeName }))}><option value="ink">夜墨</option><option value="paper">纸页</option></select></label>
                <NumberSetting label="文字缩放" note="调整对话正文的显示大小，只影响本机界面，不改变模型接收的内容。" value={draftPreferences.fontScale} min={0.85} max={1.25} step={0.05} onChange={(value) => setDraftPreferences((before) => ({ ...before, fontScale: value }))} />
                <label className="check-row"><input type="checkbox" checked={draftPreferences.compactMessages} onChange={(e) => setDraftPreferences((value) => ({ ...value, compactMessages: e.target.checked }))} /><span><strong>紧凑消息间距 <HelpTip text="缩小消息之间的留白，在同一屏显示更多对话内容。" /></strong></span></label>
                <label className="check-row"><input type="checkbox" checked={draftPreferences.reduceMotion} onChange={(e) => setDraftPreferences((value) => ({ ...value, reduceMotion: e.target.checked }))} /><span><strong>减少动画 <HelpTip text="关闭或缩短界面过渡动画，适合对动态效果敏感或设备性能较低时使用。" /></strong></span></label>
                <label className="check-row"><input type="checkbox" checked={draftPreferences.debugMode} onChange={(e) => setDraftPreferences((value) => ({ ...value, debugMode: e.target.checked }))} /><span><strong>上下文调试模式 <HelpTip text="在故事资料中显示本轮实际 Prompt、分区 Token、裁剪结果、世界书触发记录、RAG 分数、耗时和费用估算。" /></strong></span></label>
                <details className="privacy-note"><summary>数据与隐私</summary><p>聊天数据：<code>data/saraswati_v1.db</code></p><p>模型设置：<code>data/settings.json</code></p><p>API Key 保存在本机，请勿分享设置文件。</p></details>
              </div>
            )}
          </div>
        </div>
        {notice && <div className={`settings-notice ${notice.kind}`}>{notice.text}</div>}
        <footer className="settings-footer">
          <button className="secondary-button" onClick={testConnection} disabled={!form || busy || weightTotal <= 0}>{busy ? "处理中…" : "保存并测试连接"}</button>
          <div><button className="ghost-button" onClick={onClose}>取消</button><button className="primary-button" onClick={() => void saveSettings()} disabled={!form || busy || weightTotal <= 0}>{busy ? "保存中…" : "保存并应用"}</button></div>
        </footer>
      </section>
    </div>
  );
}

function SettingsHeading({ title, detail }: { title: string; detail?: string }) {
  return <div className="settings-heading"><h3>{title}</h3>{detail && <p>{detail}</p>}</div>;
}

function NumberSetting({ label, note, value, min, max, step, onChange, compact = false }: {
  label: string;
  note?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  compact?: boolean;
}) {
  return (
    <label className={`number-setting${compact ? " compact" : ""}`}>
      <span><strong>{label} {note && <HelpTip text={note} />}</strong></span>
      <input type="range" value={value} min={min} max={max} step={step} onChange={(e) => onChange(Number(e.target.value))} />
      <input type="number" value={value} min={min} max={max} step={step} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function settingsToUpdate(settings: AppSettings): SettingsUpdate {
  return {
    llm_base_url: settings.llm_base_url,
    api_key: null,
    clear_api_key: false,
    llm_model: settings.llm_model,
    embedding_model: settings.embedding_model,
    temperature: settings.temperature,
    top_p: settings.top_p,
    max_output_tokens: settings.max_output_tokens,
    presence_penalty: settings.presence_penalty,
    frequency_penalty: settings.frequency_penalty,
    request_timeout: settings.request_timeout,
    max_agent_steps: settings.max_agent_steps,
    recent_message_limit: settings.recent_message_limit,
    rag_limit: settings.rag_limit,
    vector_weight: settings.vector_weight,
    keyword_weight: settings.keyword_weight,
    importance_weight: settings.importance_weight,
    recency_weight: settings.recency_weight,
    auto_summary_enabled: settings.auto_summary_enabled,
    summary_detail_mode: settings.summary_detail_mode,
    chapter_summary_size: settings.chapter_summary_size,
    arc_summary_size: settings.arc_summary_size,
    rerank_base_url: settings.rerank_base_url,
    rerank_api_key: null,
    clear_rerank_api_key: false,
    rerank_model: settings.rerank_model,
    rerank_candidates: settings.rerank_candidates,
    context_window_tokens: settings.context_window_tokens,
    input_price_per_million: settings.input_price_per_million,
    output_price_per_million: settings.output_price_per_million,
  };
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "发生了未知错误";
}
