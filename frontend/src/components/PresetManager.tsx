import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { HelpTip } from "./HelpTip";
import type { PromptPreset, PresetPrompt } from "../types";

export function PresetManager({ onActivated, onNotice }: {
  onActivated: () => Promise<void>;
  onNotice: (kind: "ok" | "error", text: string) => void;
}) {
  const [presets, setPresets] = useState<PromptPreset[]>([]);
  const [draft, setDraft] = useState<PromptPreset | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function reload(selectId?: string) {
    const items = await api.presets();
    setPresets(items);
    const selected = items.find((item) => item.id === selectId) ?? items.find((item) => item.id === draft?.id) ?? items[0] ?? null;
    setDraft(selected ? structuredClone(selected) : null);
  }

  useEffect(() => { void reload().catch((reason) => onNotice("error", errorText(reason))); }, []);

  async function create() {
    await run(async () => {
      const item = await api.createPreset({
        name: `新预设 ${presets.length + 1}`,
        prompts: defaultWritingPrompts(),
      });
      await reload(item.id);
      onNotice("ok", "已创建预设。");
    });
  }

  async function save() {
    if (!draft) return;
    await run(async () => {
      const saved = await api.updatePreset(draft.id, presetPayload(draft));
      if (saved.active) {
        await api.activatePreset(saved.id);
        await onActivated();
      }
      await reload(saved.id);
      onNotice("ok", "预设已保存。" );
    });
  }

  async function activate() {
    if (!draft) return;
    await run(async () => {
      await api.activatePreset(draft.id);
      await onActivated();
      await reload(draft.id);
      onNotice("ok", `已启用“${draft.name}”。`);
    });
  }

  async function duplicate() {
    if (!draft) return;
    await run(async () => { const item = await api.duplicatePreset(draft.id); await reload(item.id); });
  }

  async function remove() {
    if (!draft || draft.active) return;
    await run(async () => { await api.deletePreset(draft.id); await reload(); });
  }

  async function exportJson() {
    if (!draft) return;
    await run(async () => {
      const data = await api.exportPreset(draft.id);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = `${safeName(draft.name)}.json`; link.click(); URL.revokeObjectURL(url);
    });
  }

  async function importFile(file: File) {
    await run(async () => {
      const data = JSON.parse(await file.text()) as Record<string, unknown>;
      const item = await api.importPreset(data, file.name.replace(/\.json$/i, ""));
      await reload(item.id);
      onNotice("ok", "预设已导入。酒馆文件中的兼容字段会保留，但不会改动模型生成参数。" );
    });
  }

  async function run(task: () => Promise<void>) {
    try { setBusy(true); await task(); } catch (reason) { onNotice("error", errorText(reason)); } finally { setBusy(false); }
  }

  function setField<K extends keyof PromptPreset>(key: K, value: PromptPreset[K]) {
    setDraft((before) => before ? { ...before, [key]: value } : before);
  }

  function updatePrompt(index: number, patch: Partial<PresetPrompt>) {
    if (!draft) return;
    const prompts = draft.prompts.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item);
    setDraft({ ...draft, prompts });
  }

  function move(index: number, direction: -1 | 1) {
    if (!draft) return;
    const target = index + direction;
    if (target < 0 || target >= draft.prompts.length) return;
    const prompts = [...draft.prompts];
    [prompts[index], prompts[target]] = [prompts[target], prompts[index]];
    setDraft({ ...draft, prompts });
  }

  return <div className="preset-manager">
    <aside className="preset-list">
      <div className="preset-list-actions"><button onClick={() => void create()} disabled={busy}>新建</button><button onClick={() => fileRef.current?.click()} disabled={busy}>导入 JSON</button></div>
      <input ref={fileRef} hidden type="file" accept="application/json,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) void importFile(file); event.target.value = ""; }} />
      {presets.length === 0 ? <p>还没有预设。</p> : presets.map((item) => <button key={item.id} className={`preset-list-item${draft?.id === item.id ? " selected" : ""}`} onClick={() => setDraft(structuredClone(item))}><strong>{item.name}</strong><small>{item.active ? "当前使用" : `${item.prompts.filter((prompt) => prompt.enabled).length} 个模块`}</small></button>)}
    </aside>
    <section className="preset-editor">
      {!draft ? <div className="preset-empty"><h3>写作预设</h3></div> : <>
        <header className="preset-editor-header"><div><input className="preset-name" value={draft.name} onChange={(event) => setField("name", event.target.value)} /><textarea value={draft.description} onChange={(event) => setField("description", event.target.value)} placeholder="备注" rows={2} /></div><span className={draft.active ? "active" : ""}>{draft.active ? "使用中" : "未启用"}</span></header>
        <div className="prompt-manager-heading"><h3>写作提示词 <HelpTip text="预设中的提示词会和当前故事资料一起发给模型。" /></h3><button onClick={() => setField("prompts", [...draft.prompts, customPrompt(draft.prompts.length)])}>添加提示词</button></div>
        <div className="prompt-block-list">{draft.prompts.map((prompt, index) => <article className={`prompt-block${prompt.enabled ? "" : " disabled"}`} key={`${prompt.identifier}-${index}`}>
          <div className="prompt-order-buttons"><button onClick={() => move(index, -1)} disabled={index === 0}>↑</button><button onClick={() => move(index, 1)} disabled={index === draft.prompts.length - 1}>↓</button></div>
          <label className="prompt-enabled"><input type="checkbox" checked={prompt.enabled} onChange={(event) => updatePrompt(index, { enabled: event.target.checked })} /><span /></label>
          <div className="prompt-block-body"><header><div className="prompt-header-field"><input value={prompt.name} onChange={(event) => updatePrompt(index, { name: event.target.value })} /><HelpTip text={promptDescription(prompt.identifier)} /></div><div className="prompt-header-field"><select value={prompt.role} onChange={(event) => updatePrompt(index, { role: event.target.value as PresetPrompt["role"] })}><option value="system">System</option><option value="user">User</option><option value="assistant">Assistant</option></select><HelpTip text="System 是规则；User 表示用户补充；Assistant 表示角色示例或预填内容。通常使用 System。" /></div></header><textarea value={prompt.content} onChange={(event) => updatePrompt(index, { content: event.target.value })} rows={4} /><details><summary>插入位置 <HelpTip text="选择提示词放在全部对话之前，或插入到最近的聊天消息之间。" /></summary><div className="prompt-position"><select value={prompt.position} onChange={(event) => updatePrompt(index, { position: event.target.value as PresetPrompt["position"] })}><option value="relative">对话记录之前</option><option value="in_chat">插入对话记录</option></select>{prompt.position === "in_chat" && <label className="prompt-depth"><span>深度 <HelpTip text="0 表示放在聊天记录末尾；1 表示放在最后一条消息之前，以此类推。" /></span><input type="number" min={0} max={100} value={prompt.depth} onChange={(event) => updatePrompt(index, { depth: Number(event.target.value) })} /></label>}</div></details></div>
          <button className="prompt-remove" onClick={() => setField("prompts", draft.prompts.filter((_, itemIndex) => itemIndex !== index))}>×</button>
        </article>)}</div>
        <footer className="preset-editor-actions"><button onClick={() => void exportJson()}>导出酒馆 JSON</button><button onClick={() => void duplicate()}>复制</button><button className="danger" onClick={() => void remove()} disabled={draft.active}>删除</button><span /><button onClick={() => void save()}>保存</button><button className="primary" onClick={() => void activate()}>{draft.active ? "重新应用" : "启用"}</button></footer>
      </>}
    </section>
  </div>;
}

function customPrompt(index: number): PresetPrompt { return { identifier: `custom-${Date.now()}-${index}`, name: "自定义 Prompt", role: "system", content: "", enabled: true, marker: false, position: "relative", depth: 0 }; }
function promptDescription(identifier: string) {
  const descriptions: Record<string, string> = {
    main: "整份预设的核心规则，通常说明模型应怎样继续角色扮演。",
    style: "控制叙述视角、句式、节奏和语言风格。",
    negative: "列出回复中需要避免的内容、措辞或写法。",
    jailbreak: "放在近期对话末尾的补充指令，常用于加强角色遵循和输出格式。",
  };
  return descriptions[identifier] ?? "自定义提示词。名称只用于管理，不会改变执行方式。";
}
function defaultWritingPrompts(): PresetPrompt[] {
  return [
    { identifier: "main", name: "主提示词", role: "system", content: "根据当前角色与故事继续进行角色扮演。", enabled: true, marker: false, position: "relative", depth: 0 },
    { identifier: "style", name: "文风", role: "system", content: "", enabled: true, marker: false, position: "relative", depth: 0 },
    { identifier: "negative", name: "禁写项", role: "system", content: "", enabled: true, marker: false, position: "relative", depth: 0 },
    { identifier: "jailbreak", name: "历史后指令 / 破甲", role: "system", content: "", enabled: true, marker: false, position: "in_chat", depth: 0 },
  ];
}
function presetPayload(item: PromptPreset) { return { name: item.name, description: item.description, temperature: item.temperature, top_p: item.top_p, max_output_tokens: item.max_output_tokens, presence_penalty: item.presence_penalty, frequency_penalty: item.frequency_penalty, context_window_tokens: item.context_window_tokens, prompts: item.prompts, extra_settings: item.extra_settings }; }
function safeName(value: string) { return value.replace(/[<>:"/\\|?*]+/g, "_"); }
function errorText(reason: unknown) { return reason instanceof Error ? reason.message : "操作失败"; }
