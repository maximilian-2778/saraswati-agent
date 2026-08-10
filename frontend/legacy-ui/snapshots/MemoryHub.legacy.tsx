/*
 * Archived snapshot before legacy panel extraction.
 * This file is outside frontend/src and is not part of the production build.
 */

import { FormEvent, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "./api";
import { useConsoleSeenState } from "./hooks/useConsoleSeenState";
import type {
  AgentTrace,
  AuditIssue,
  Memory,
  MemoryCoverage,
  NarrativeNode,
  NarrativeDelta,
  Npc,
  RetrievedMemory,
  SceneNode,
  StateEntry,
  StateProposal,
  TimelineAnchor,
  WorldEngineSnapshot,
} from "./types";

export type MemoryHubTab = "overview" | "world" | "events" | "memory" | "context" | "diagnostics";

interface MemoryHubProps {
  chatId: string | null;
  activeTab: MemoryHubTab;
  onTab: (tab: MemoryHubTab) => void;
  memories: Memory[];
  memoryGraph: NarrativeNode[];
  deltas: NarrativeDelta[];
  worldEngine: WorldEngineSnapshot | null;
  coverage: MemoryCoverage | null;
  scenes: SceneNode[];
  npcs: Npc[];
  retrieved: RetrievedMemory[];
  timeline: TimelineAnchor[];
  stateEntries: StateEntry[];
  proposals: StateProposal[];
  audits: AuditIssue[];
  traces: AgentTrace[];
  debugMode: boolean;
  onRefresh: () => Promise<void> | void;
  onError: (reason: unknown) => void;
  onClose: () => void;
}

export function MemoryHub(props: MemoryHubProps) {
  const noticeCounts = useConsoleSeenState(props.chatId, props.activeTab, {
    world: [
      ...props.scenes.map((item) => `${item.updated_at || item.created_at}|${item.id}`),
      ...props.npcs.map((item) => `${item.updated_at || item.created_at}|${item.id}`),
      ...(props.worldEngine?.updated_at ? [`${props.worldEngine.updated_at}|world-engine`] : []),
    ],
    events: [
      ...props.deltas.map((item) => `${item.created_at}|${item.id}`),
      ...props.timeline.map((item) => `${item.updated_at || item.created_at}|${item.id}`),
    ],
    memory: props.memoryGraph.map((item) => `${item.created_at}|${item.id}`),
    diagnostics: props.audits.map((item) => `${item.created_at}|${item.id}`),
  });
  const tabs: { id: MemoryHubTab; label: string; count?: number }[] = [
    { id: "overview", label: "概览" },
    { id: "world", label: "世界", count: noticeCounts.world },
    { id: "events", label: "事件", count: noticeCounts.events },
    { id: "memory", label: "记忆", count: noticeCounts.memory },
    ...(props.debugMode ? [{ id: "context" as const, label: "上下文" }] : []),
    { id: "diagnostics", label: "检查", count: noticeCounts.diagnostics },
  ];
  return (
    <aside className="inspector memory-hub">
      <div className="inspector-title"><span>控制台</span><button className="icon-button" onClick={props.onClose} aria-label="关闭控制台"><span className="close-glyph" aria-hidden="true"><i /><i /></span></button></div>
      <div className="tabs memory-tabs">
        {tabs.map((tab) => <button key={tab.id} className={props.activeTab === tab.id ? "active" : ""} onClick={() => props.onTab(tab.id)}>{tab.label}{Boolean(tab.count) && <em>{tab.count}</em>}</button>)}
      </div>
      <div className="inspector-content">
        {!props.chatId ? <Empty text="选择故事后，这里会显示整理好的剧情资料。" />
          : props.activeTab === "overview" ? <OverviewPanel {...props} chatId={props.chatId} />
          : props.activeTab === "world" ? <WorldGraphPanel {...props} chatId={props.chatId} />
          : props.activeTab === "events" ? <EventsPanel {...props} chatId={props.chatId} />
          : props.activeTab === "memory" ? <MemoryPanel {...props} chatId={props.chatId} />
          : props.activeTab === "context" ? <ContextDebugPanel traces={props.traces} />
          : <DiagnosticsPanel {...props} chatId={props.chatId} />}
      </div>
    </aside>
  );
}

function OverviewPanel(props: MemoryHubProps & { chatId: string }) {
  const currentScene = props.scenes.find((item) => item.is_current);
  const presentNpcs = props.npcs.filter((item) => item.presence === "present" || item.presence === "nearby");
  const latestDelta = [...props.deltas].reverse().find((item) => item.valid);
  const latestTime = props.timeline.at(-1);
  const pending = props.proposals.filter((item) => item.status === "pending");
  return <div className="console-overview">
    <section className="console-hero"><small>故事当前状态</small><h2>{currentScene?.name ?? "地点尚未记录"}</h2><p>{currentScene?.description || latestDelta?.payload.summary || "继续对话后，这里会整理当前剧情。"}</p></section>
    <div className="console-stat-grid">
      <article><small>故事时间</small><strong>{latestTime?.story_time || latestDelta?.payload.time_change || "未记录"}</strong></article>
      <article><small>在场人物</small><strong>{presentNpcs.length}</strong><span>{presentNpcs.map((item) => item.name).join("、") || "暂无"}</span></article>
      <article><small>物品</small><strong>{itemEntries(props.stateEntries).length}</strong></article>
      <article><small>待确认</small><strong>{pending.length}</strong></article>
    </div>
    <section className="console-section"><h3>最近发生</h3>{latestDelta ? <article className="event-card"><strong>{latestDelta.payload.summary || "本轮剧情"}</strong>{Boolean(latestDelta.payload.facts?.length) && <p>{latestDelta.payload.facts?.join("；")}</p>}<time>{formatDateTime(latestDelta.created_at)}</time></article> : <Empty text="还没有整理出的剧情事件。" />}</section>
    {props.worldEngine && props.worldEngine.state.round > 0 && <section className="console-section"><h3>世界动向</h3><article className="world-digest-brief"><small>第 {props.worldEngine.state.round} 轮</small><p>{props.worldEngine.state.digest}</p><span>{props.worldEngine.state.events.filter((item) => item.active).length} 条持续事件 · {props.worldEngine.state.factions.length} 个势力 · {props.worldEngine.state.rumors.filter((item) => item.active).length} 条传闻</span></article></section>}
    <section className="console-section"><h3>当前人物</h3><div className="compact-entity-list">{presentNpcs.length ? presentNpcs.map((npc) => <span key={npc.id}>{npc.name}<small>{presenceLabel(npc.presence)}</small></span>) : <p className="muted">当前没有记录在场人物。</p>}</div></section>
  </div>;
}

function EventsPanel(props: MemoryHubProps & { chatId: string }) {
  const [storyTime, setStoryTime] = useState("");
  const [description, setDescription] = useState("");
  const validDeltas = props.deltas.filter((item) => item.valid);
  const deltaSources = new Set(validDeltas.map((item) => item.assistant_message_id));
  const events = [
    ...validDeltas.map((item) => ({ id: `delta-${item.id}`, date: item.created_at, time: item.payload.time_change || "剧情", title: item.payload.summary || "本轮剧情", detail: item.payload.facts?.join("；") || "", kind: "剧情" })),
    ...props.timeline.filter((item) => !item.source_message_id || !deltaSources.has(item.source_message_id)).map((item) => ({ id: `time-${item.id}`, date: item.created_at, time: item.story_time, title: item.description, detail: "", kind: "时间" })),
  ].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
  async function add(event: FormEvent) { event.preventDefault(); try { await api.createTimelineAnchor(props.chatId, { story_time: storyTime, description }); setStoryTime(""); setDescription(""); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  return <div className="panel-stack event-console">
    <div className="event-stream">{events.length ? events.map((item) => <article className="event-card" key={item.id}><i /><header><span>{item.kind}</span><time>{item.time}</time></header><strong>{item.title}</strong>{item.detail && <p>{item.detail}</p>}<small>{formatDateTime(item.date)}</small></article>) : <Empty text="还没有故事事件。" />}</div>
    <form className="mini-form" onSubmit={add}><h3>补充事件</h3><input value={storyTime} onChange={(event) => setStoryTime(event.target.value)} placeholder="故事内时间" required /><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="发生了什么" rows={3} required /><button>添加</button></form>
  </div>;
}

function ItemsPanel(props: MemoryHubProps & { chatId: string }) {
  const [selected, setSelected] = useState<StateEntry | null>(null);
  const items = itemEntries(props.stateEntries);
  return <div className="panel-stack entity-browser">
    <div className="entity-grid">{items.length ? items.map((entry) => { const value = itemValue(entry.value); return <button className="entity-card" key={entry.id} onClick={() => setSelected(entry)}><span className="entity-glyph">◇</span><strong>{stripLedgerPrefix(entry.entity)}</strong><small>{value.status || entry.key}</small><p>{[value.quantity && `数量 ${value.quantity}`, value.location].filter(Boolean).join(" · ") || "查看详细资料"}</p></button>; }) : <Empty text="还没有物品记录。" />}</div>
    {selected && <div className="entity-detail"><header><div><small>物品档案</small><h2>{stripLedgerPrefix(selected.entity)}</h2></div><button onClick={() => setSelected(null)}>×</button></header><ItemDetails entry={selected} /><footer><span>第 {selected.version} 版</span><time>{formatDateTime(selected.updated_at)}</time></footer></div>}
  </div>;
}

function ItemDetails({ entry }: { entry: StateEntry }) {
  const value = itemValue(entry.value);
  return <dl className="entity-facts"><dt>介绍</dt><dd>{value.description || value.status || "暂无介绍"}</dd><dt>状态</dt><dd>{value.status || "未记录"}</dd><dt>数量</dt><dd>{value.quantity || "未记录"}</dd><dt>所有者</dt><dd>{value.owner || "未记录"}</dd><dt>位置</dt><dd>{value.location || "未记录"}</dd></dl>;
}

function MemoryPanel(props: MemoryHubProps & { chatId: string }) {
  return <div className="memory-console"><SummaryPanel {...props} chatId={props.chatId} /><section className="console-section"><h3>相关记忆</h3><RetrievalPanel {...props} chatId={props.chatId} /></section></div>;
}

function DeltaPanel({ deltas }: { deltas: NarrativeDelta[] }) {
  if (!deltas.length) return <Empty text="暂无记录" />;
  return <div className="panel-stack delta-list">{[...deltas].reverse().map((delta) => <article key={delta.id} className={delta.valid ? "" : "invalid"}><header><strong>{delta.payload.summary || "这一轮发生的事"}</strong><span>{delta.valid ? "当前版本" : "对应内容已改写"}</span></header>{delta.payload.time_change && <p>时间：{delta.payload.time_change}</p>}{Boolean(delta.payload.facts?.length) && <ul>{delta.payload.facts?.map((fact) => <li key={fact}>{fact}</li>)}</ul>}{Boolean(delta.payload.numbers?.length) && <p>数值：{delta.payload.numbers?.map((item) => `${item.name} ${item.value}${item.unit}`).join("；")}</p>}<small>{new Date(delta.created_at).toLocaleString()}</small></article>)}</div>;
}

function WorldGraphPanel(props: MemoryHubProps & { chatId: string }) {
  const [mode, setMode] = useState<"situation" | "scenes" | "npcs" | "factions">("situation");
  const [worldBusy, setWorldBusy] = useState(false);
  const [selectedScene, setSelectedScene] = useState<SceneNode | null>(null);
  const [selectedNpc, setSelectedNpc] = useState<Npc | null>(null);
  const [mergeTarget, setMergeTarget] = useState("");
  const sceneById = new Map(props.scenes.map((item) => [item.id, item]));
  const npcItems = (npc: Npc) => itemEntries(props.stateEntries).filter((entry) => itemValue(entry.value).owner === npc.name);
  async function merge() { if (!selectedScene || !mergeTarget) return; try { await api.mergeScene(props.chatId, selectedScene.id, mergeTarget); setSelectedScene(null); setMergeTarget(""); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  async function evolveWorld() { try { setWorldBusy(true); await api.evolveWorld(props.chatId); await props.onRefresh(); } catch (reason) { props.onError(reason); } finally { setWorldBusy(false); } }
  async function toggleAuto(enabled: boolean) { try { setWorldBusy(true); await api.configureWorldEngine(props.chatId, enabled); await props.onRefresh(); } catch (reason) { props.onError(reason); } finally { setWorldBusy(false); } }
  const world = props.worldEngine?.state;
  return <div className="panel-stack world-graph entity-browser">
    <div className="ledger-tabs world-ledger-tabs"><button className={mode === "situation" ? "active" : ""} onClick={() => setMode("situation")}>概况<small>{world?.round ?? 0}</small></button><button className={mode === "scenes" ? "active" : ""} onClick={() => setMode("scenes")}>地点<small>{props.scenes.length}</small></button><button className={mode === "npcs" ? "active" : ""} onClick={() => setMode("npcs")}>人物<small>{props.npcs.length}</small></button><button className={mode === "factions" ? "active" : ""} onClick={() => setMode("factions")}>势力<small>{world?.factions.length ?? 0}</small></button></div>
    {mode === "situation" ? <div className="world-situation">
      <section className="world-engine-hero"><div><small>WORLD CHRONICLE · 第 {world?.round ?? 0} 轮</small><h3>{world && world.round > 0 ? "世界正在自行运转" : "世界尚未开始推演"}</h3><p>{world?.digest || "推进一次后，这里会整理势力行动、持续事件与正在传播的消息。"}</p></div><div className="world-engine-actions"><button className="primary-button" disabled={worldBusy} onClick={() => void evolveWorld()}>{worldBusy ? "推演中…" : "推进世界"}</button><label className="extension-switch"><input type="checkbox" checked={props.worldEngine?.auto_evolve ?? false} disabled={worldBusy} onChange={(event) => void toggleAuto(event.target.checked)} /><span>随剧情自动推进</span></label></div></section>
      {Boolean(props.worldEngine?.stale_count) && <p className="world-chain-note">有 {props.worldEngine?.stale_count} 条旧推演因对应剧情被改写而停止生效。</p>}
      {world?.trends.length ? <section className="world-trend-strip">{world.trends.map((trend) => <article key={trend.id}><small>{trendDirectionLabel(trend.direction)}</small><strong>{trend.name}</strong><p>{trend.description}</p></article>)}</section> : null}
      <section className="world-chronicle-section"><header><h3>持续事件</h3><span>{world?.events.filter((item) => item.active).length ?? 0}</span></header><div className="world-event-list">{world?.events.some((item) => item.active) ? world.events.filter((item) => item.active).map((item) => <article key={item.id}><div className="world-card-heading"><strong>{item.name}</strong><span>Lv.{item.level} · {worldEventStageLabel(item.stage)}</span></div><p>{item.summary}</p>{item.next_pressure && <small>下一步压力：{item.next_pressure}</small>}<footer>{item.location || "地点未定"}{item.participants.length ? ` · ${item.participants.join("、")}` : ""}</footer></article>) : <Empty text="还没有持续发展的世界事件。" />}</div></section>
      <section className="world-chronicle-section"><header><h3>传闻</h3><span>{world?.rumors.filter((item) => item.active).length ?? 0}</span></header><div className="world-rumor-list">{world?.rumors.some((item) => item.active) ? world.rumors.filter((item) => item.active).map((item) => <article key={item.id}><div><strong>{item.topic}</strong><span>{worldRumorTypeLabel(item.type)} · Lv.{item.level}</span></div><p>{item.content}</p><small>{[item.scope, item.source && `来源：${item.source}`].filter(Boolean).join(" · ")}</small></article>) : <Empty text="还没有形成可传播的消息。" />}</div></section>
    </div>
      : mode === "scenes" ? <div className="scene-tree">{props.scenes.length ? [...props.scenes].sort((a, b) => a.path.join("/").localeCompare(b.path.join("/"))).map((scene) => <button className={`scene-node ${scene.is_current ? "current" : ""}`} style={{ marginLeft: `${Math.max(scene.path.length - 1, 0) * 14}px` }} key={scene.id} onClick={() => setSelectedScene(scene)}><span><strong>{scene.name}</strong><small>{scene.path.join(" › ")}</small></span>{scene.is_current && <em>当前位置</em>}</button>) : <Empty text="还没有地点。" />}</div>
      : mode === "npcs" ? <div className="entity-grid">{props.npcs.length ? props.npcs.map((npc) => <button className="entity-card" key={npc.id} onClick={() => setSelectedNpc(npc)}><span className="entity-glyph">{npc.name.slice(0, 1)}</span><strong>{npc.name}</strong><small>{importanceLabel(npc.importance)} · {presenceLabel(npc.presence)}</small><p>{npc.description || npc.relation_to_user || "查看人物档案"}</p></button>) : <Empty text="还没有人物。" />}</div>
      : <div className="world-faction-list">{world?.factions.length ? world.factions.map((faction) => <article key={faction.id}><header><span className="faction-seal">{faction.name.slice(0, 1)}</span><div><strong>{faction.name}</strong><small>{factionStatusLabel(faction.status)} · {factionRelationLabel(faction.relation)} · 影响力 {faction.influence}</small></div></header><p>{faction.description || "暂无势力介绍"}</p>{faction.latest_action && <footer>最近行动：{faction.latest_action}</footer>}</article>) : <Empty text="还没有形成需要持续追踪的势力。" />}</div>}
    {selectedScene && <SceneWindow scene={selectedScene} scenes={props.scenes} npcs={props.npcs} items={itemEntries(props.stateEntries).filter((entry) => itemValue(entry.value).location === selectedScene.name)} chatId={props.chatId} mergeTarget={mergeTarget} onMergeTarget={setMergeTarget} onMerge={merge} onClose={() => setSelectedScene(null)} onRefresh={props.onRefresh} onError={props.onError} />}
    {selectedNpc && <NpcWindow npc={selectedNpc} scenes={props.scenes} items={npcItems(selectedNpc)} chatId={props.chatId} onClose={() => setSelectedNpc(null)} onRefresh={props.onRefresh} onError={props.onError} />}
  </div>;
}

function SceneWindow(props: { scene: SceneNode; scenes: SceneNode[]; npcs: Npc[]; items: StateEntry[]; chatId: string; mergeTarget: string; onMergeTarget: (id: string) => void; onMerge: () => Promise<void>; onClose: () => void; onRefresh: () => Promise<void> | void; onError: (reason: unknown) => void }) {
  const [tab, setTab] = useState<"intro" | "attributes" | "inventory">("intro");
  const [description, setDescription] = useState(props.scene.description);
  const [parentId, setParentId] = useState(props.scene.parent_id ?? "");
  const [current, setCurrent] = useState(props.scene.is_current);
  async function save(event: FormEvent) { event.preventDefault(); try { await api.updateScene(props.chatId, props.scene.id, { name: props.scene.name, description, parent_id: parentId || null, is_current: current }); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  return createPortal(
    <div className="rpg-window-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) props.onClose(); }}>
      <section className="rpg-window" role="dialog" aria-modal="true" aria-label={`${props.scene.name}地点档案`}>
        <header><div><small>地点档案</small><h2>{props.scene.name}</h2><p>{props.scene.path.join(" › ")}</p></div><button type="button" className="rpg-close" onClick={props.onClose} aria-label="关闭地点档案">×</button></header>
        <nav className="rpg-window-tabs" aria-label="地点档案页面">
          <button type="button" className={tab === "intro" ? "active" : ""} onClick={() => setTab("intro")}>介绍</button>
          <button type="button" className={tab === "attributes" ? "active" : ""} onClick={() => setTab("attributes")}>属性</button>
          <button type="button" className={tab === "inventory" ? "active" : ""} onClick={() => setTab("inventory")}>物品</button>
        </nav>
        <div className="rpg-window-page">
          {tab === "intro" ? <form className="rpg-profile-form" onSubmit={save}><section><h3>地点介绍</h3><textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={12} placeholder="地点介绍" /><p className="rpg-related">在场人物：{props.npcs.filter((npc) => npc.location_scene_id === props.scene.id).map((npc) => npc.name).join("、") || "暂无"}</p></section><footer><button>保存地点资料</button></footer></form>
            : tab === "attributes" ? <form className="rpg-profile-form" onSubmit={save}><section><h3>地点属性</h3><label>上级地点<select value={parentId} onChange={(event) => setParentId(event.target.value)}><option value="">顶层地点</option>{props.scenes.filter((item) => item.id !== props.scene.id).map((item) => <option value={item.id} key={item.id}>{item.path.join(" › ")}</option>)}</select></label><label className="rpg-check"><input type="checkbox" checked={current} onChange={(event) => setCurrent(event.target.checked)} /> 设为当前位置</label></section><footer><button>保存地点属性</button></footer><details className="merge-place"><summary>合并重复地点</summary><select value={props.mergeTarget} onChange={(event) => props.onMergeTarget(event.target.value)}><option value="">选择保留的地点</option>{props.scenes.filter((scene) => scene.id !== props.scene.id).map((scene) => <option value={scene.id} key={scene.id}>{scene.path.join(" › ")}</option>)}</select><button type="button" disabled={!props.mergeTarget} onClick={() => void props.onMerge()}>合并</button></details></form>
            : <InventoryEditor chatId={props.chatId} holderType="scene" holderName={props.scene.name} items={props.items} onRefresh={props.onRefresh} onError={props.onError} />}
        </div>
      </section>
    </div>,
    document.querySelector(".app-shell") ?? document.body,
  );
}

function NpcWindow(props: { npc: Npc; scenes: SceneNode[]; items: StateEntry[]; chatId: string; onClose: () => void; onRefresh: () => Promise<void> | void; onError: (reason: unknown) => void }) {
  const [tab, setTab] = useState<"intro" | "attributes" | "inventory">("intro");
  const [draft, setDraft] = useState(props.npc);
  async function save(event: FormEvent) { event.preventDefault(); try { await api.updateNpc(props.chatId, props.npc.id, draft); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  return createPortal(
    <div className="rpg-window-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) props.onClose(); }}>
      <section className="rpg-window" role="dialog" aria-modal="true" aria-label={`${props.npc.name}人物档案`}>
        <header><div><small>人物档案</small><h2>{props.npc.name}</h2><p>{importanceLabel(draft.importance)} · {presenceLabel(draft.presence)}</p></div><button type="button" className="rpg-close" onClick={props.onClose} aria-label="关闭人物档案">×</button></header>
        <nav className="rpg-window-tabs" aria-label="人物档案页面">
          <button type="button" className={tab === "intro" ? "active" : ""} onClick={() => setTab("intro")}>介绍</button>
          <button type="button" className={tab === "attributes" ? "active" : ""} onClick={() => setTab("attributes")}>属性</button>
          <button type="button" className={tab === "inventory" ? "active" : ""} onClick={() => setTab("inventory")}>物品</button>
        </nav>
        <div className="rpg-window-page">
          {tab === "intro" ? <form className="rpg-profile-form" onSubmit={save}><section><h3>人物介绍</h3><textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} rows={8} placeholder="身份、经历与人物介绍" /><label>外观与穿着<textarea value={draft.outfit} onChange={(event) => setDraft({ ...draft, outfit: event.target.value })} rows={5} /></label></section><footer><button>保存人物资料</button></footer></form>
            : tab === "attributes" ? <form className="rpg-profile-form" onSubmit={save}><section><h3>人物属性</h3><label>当前状态<input value={draft.condition} onChange={(event) => setDraft({ ...draft, condition: event.target.value })} /></label><label>与主控人物的关系<input value={draft.relation_to_user} onChange={(event) => setDraft({ ...draft, relation_to_user: event.target.value })} /></label><label>重要程度<select value={draft.importance} onChange={(event) => setDraft({ ...draft, importance: event.target.value as Npc["importance"] })}><option value="core">核心人物</option><option value="supporting">重要配角</option><option value="minor">次要人物</option></select></label><label>出场状态<select value={draft.presence} onChange={(event) => setDraft({ ...draft, presence: event.target.value as Npc["presence"] })}><option value="present">在场</option><option value="nearby">附近</option><option value="away">离场</option><option value="unknown">未知</option></select></label><label>所在地点<select value={draft.location_scene_id ?? ""} onChange={(event) => setDraft({ ...draft, location_scene_id: event.target.value || null })}><option value="">未知</option>{props.scenes.map((scene) => <option value={scene.id} key={scene.id}>{scene.path.join(" › ")}</option>)}</select></label></section><footer><button>保存人物属性</button></footer></form>
            : <InventoryEditor chatId={props.chatId} holderType="npc" holderName={props.npc.name} items={props.items} onRefresh={props.onRefresh} onError={props.onError} />}
        </div>
      </section>
    </div>,
    document.querySelector(".app-shell") ?? document.body,
  );
}

function InventoryEditor(props: { chatId: string; holderType: "npc" | "scene"; holderName: string; items: StateEntry[]; onRefresh: () => Promise<void> | void; onError: (reason: unknown) => void }) {
  const blank = { name: "", description: "", quantity: "1", status: "完好" };
  const [draft, setDraft] = useState(blank);
  const [editingId, setEditingId] = useState<string | null>(null);
  function edit(entry: StateEntry) { const value = itemValue(entry.value); setEditingId(entry.id); setDraft({ name: stripLedgerPrefix(entry.entity), description: value.description, quantity: value.quantity || "1", status: value.status }); }
  async function save(event: FormEvent) { event.preventDefault(); try { const proposal = await api.createProposal(props.chatId, { entity: `物品:${draft.name.trim()}`, key: "状态", new_value: { owner: props.holderType === "npc" ? props.holderName : "", quantity: draft.quantity, status: draft.status, location: props.holderType === "scene" ? props.holderName : "", description: draft.description }, reason: editingId ? "用户编辑物品" : "用户添加物品" }); await api.resolveProposal(props.chatId, proposal.id, "approve"); if (editingId) { const old = props.items.find((item) => item.id === editingId); if (old && stripLedgerPrefix(old.entity) !== draft.name.trim()) await api.deleteStateEntry(props.chatId, old.id); } setDraft(blank); setEditingId(null); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  async function remove(id: string) { try { await api.deleteStateEntry(props.chatId, id); if (editingId === id) { setEditingId(null); setDraft(blank); } await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  return <section className="rpg-inventory"><h3>物品栏</h3><div className="inventory-list">{props.items.length ? props.items.map((entry) => { const value = itemValue(entry.value); return <article key={entry.id}><button type="button" onClick={() => edit(entry)}><strong>{stripLedgerPrefix(entry.entity)}</strong><small>{value.quantity || "1"} · {value.status || "未记录"}</small></button><button type="button" className="inventory-delete" onClick={() => void remove(entry.id)}>×</button></article>; }) : <p className="muted">物品栏为空。</p>}</div><form className="inventory-editor" onSubmit={save}><input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="物品名称" required /><textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} placeholder="物品介绍" rows={3} /><div className="field-row"><input value={draft.quantity} onChange={(event) => setDraft({ ...draft, quantity: event.target.value })} placeholder="数量" /><input value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })} placeholder="状态" /></div><button>{editingId ? "保存物品" : "添加物品"}</button>{editingId && <button type="button" onClick={() => { setEditingId(null); setDraft(blank); }}>取消编辑</button>}</form></section>;
}

function SummaryPanel(props: MemoryHubProps & { chatId: string }) {
  const [detail, setDetail] = useState<"brief" | "detailed">("brief");
  const [selected, setSelected] = useState<string[]>([]);
  const [editing, setEditing] = useState<Memory | null>(null);
  const [busy, setBusy] = useState(false);
  const summaries = props.memories.filter((item) => item.kind === "summary");
  const levels = useMemo(() => ({
    arc: summaries.filter((item) => item.content.startsWith("[篇章概览")),
    chapter: summaries.filter((item) => item.content.startsWith("[章节总结]")),
    manual: summaries.filter((item) => !item.content.startsWith("[篇章概览") && !item.content.startsWith("[章节总结]")),
  }), [summaries]);
  const graphLevels = useMemo(() => {
    const grouped = new Map<number, NarrativeNode[]>();
    props.memoryGraph.forEach((node) => grouped.set(node.level, [...(grouped.get(node.level) ?? []), node]));
    return [...grouped.entries()].sort((left, right) => right[0] - left[0]);
  }, [props.memoryGraph]);

  async function run(action: () => Promise<unknown>) {
    try { setBusy(true); await action(); await props.onRefresh(); setSelected([]); }
    catch (reason) { props.onError(reason); }
    finally { setBusy(false); }
  }
  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    await run(() => api.updateMemory(props.chatId, editing.id, editing.content, editing.importance));
    setEditing(null);
  }
  async function backfill() {
    await run(() => api.backfillMemory(props.chatId));
  }
  const toggle = (id: string) => setSelected((items) => items.includes(id) ? items.filter((item) => item !== id) : [...items, id]);
  return <div className="panel-stack summary-panel">
    {props.coverage && <section className={`coverage-card ${props.coverage.coverage_ratio < 1 ? "warning" : "healthy"}`}><header><strong>整理进度</strong><b>{Math.round(props.coverage.coverage_ratio * 100)}%</b></header><div className="coverage-track"><i style={{ width: `${props.coverage.coverage_ratio * 100}%` }} /></div>{props.coverage.missing_message_ids.length > 0 && <button disabled={busy} onClick={() => void backfill()}>整理旧消息</button>}</section>}
    {graphLevels.map(([level, nodes]) => <section className="summary-section forest-level" key={level}><h3>{level === 0 ? "逐轮摘要" : level === 1 ? "章节回顾" : "长篇回顾"}<small>{nodes.length}</small></h3>{nodes.map((node) => <article className={`summary-card forest-node ${node.active ? "active" : ""} ${node.valid ? "" : "invalid"}`} key={node.id}><header><span>{node.active ? "本轮会参考" : node.valid ? "已保存" : "等待重整"}</span>{node.child_ids.length > 0 && <small>整理自 {node.child_ids.length} 段摘要</small>}</header><p>{node.content}</p>{(node.time_start || node.time_end) && <time>{node.time_start ?? "?"}{node.time_end && node.time_end !== node.time_start ? ` → ${node.time_end}` : ""}</time>}</article>)}</section>)}
    <div className="summary-toolbar"><select value={detail} onChange={(e) => setDetail(e.target.value as "brief" | "detailed")}><option value="brief">精简摘要</option><option value="detailed">详细摘要</option></select><button disabled={busy} onClick={() => void run(() => api.summarizeWithDetail(props.chatId, detail))}>总结近期</button><button disabled={busy || selected.length < 2} onClick={() => void run(() => api.mergeMemories(props.chatId, selected, detail))}>合并所选 {selected.length || ""}</button></div>
    {editing && <form className="inline-memory-editor" onSubmit={saveEdit}><textarea value={editing.content} onChange={(e) => setEditing({ ...editing, content: e.target.value })} rows={6} /><label>重要度 <input type="number" min={0} max={1} step={0.1} value={editing.importance} onChange={(e) => setEditing({ ...editing, importance: Number(e.target.value) })} /></label><footer><button type="button" onClick={() => setEditing(null)}>取消</button><button>保存</button></footer></form>}
    <SummarySection title="手动总结" items={levels.manual} selected={selected} onToggle={toggle} onEdit={setEditing} onDelete={(id) => void run(() => api.deleteMemory(props.chatId, id))} />
  </div>;
}

function SummarySection(props: { title: string; items: Memory[]; selected: string[]; onToggle: (id: string) => void; onEdit: (item: Memory) => void; onDelete: (id: string) => void }) {
  if (!props.items.length) return null;
  return <section className="summary-section"><h3>{props.title}<small>{props.items.length}</small></h3>{props.items.map((item) => <article className="summary-card" key={item.id}><label><input type="checkbox" checked={props.selected.includes(item.id)} onChange={() => props.onToggle(item.id)} /><span>{item.content.replace(/^\[[^\]]+\]\s*/, "")}</span></label><footer><time>{formatDateTime(item.created_at)}</time><div><button onClick={() => props.onEdit(item)}>编辑</button><button onClick={() => props.onDelete(item.id)}>删除</button></div></footer></article>)}</section>;
}

function TimelinePanel(props: MemoryHubProps & { chatId: string }) {
  const [storyTime, setStoryTime] = useState("");
  const [description, setDescription] = useState("");
  async function add(event: FormEvent) {
    event.preventDefault();
    try { await api.createTimelineAnchor(props.chatId, { story_time: storyTime, description }); setStoryTime(""); setDescription(""); await props.onRefresh(); }
    catch (reason) { props.onError(reason); }
  }
  async function remove(id: string) { try { await api.deleteTimelineAnchor(props.chatId, id); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  return <div className="panel-stack">{props.timeline.length === 0 ? <Empty text="暂无时间记录" /> : <div className="timeline-list">{props.timeline.map((item) => <article key={item.id}><i /><div><strong>{item.story_time}</strong><p>{item.description}</p><small>{formatDateTime(item.created_at)}</small></div><button onClick={() => void remove(item.id)}>×</button></article>)}</div>}<form className="mini-form" onSubmit={add}><h3>添加时间</h3><input value={storyTime} onChange={(e) => setStoryTime(e.target.value)} placeholder="第三天傍晚" required /><textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="发生了什么" rows={3} required /><button>添加</button></form></div>;
}

function LedgerPanel(props: MemoryHubProps & { chatId: string }) {
  const [category, setCategory] = useState<LedgerCategory>("item");
  const [entity, setEntity] = useState("");
  const [key, setKey] = useState("状态");
  const [value, setValue] = useState("");
  const grouped = useMemo(() => groupLedger(props.stateEntries), [props.stateEntries]);
  const pending = props.proposals.filter((item) => item.status === "pending");
  const history = props.proposals.filter((item) => item.status !== "pending").slice(0, 20);
  const categories: { id: LedgerCategory; label: string }[] = [{ id: "item", label: "物品" }, { id: "npc", label: "人物" }, { id: "scene", label: "场景" }, { id: "thread", label: "悬念" }, { id: "other", label: "其他" }];
  async function resolve(id: string, action: "approve" | "reject") { try { await api.resolveProposal(props.chatId, id, action); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  async function undo(id: string) { try { await api.undoStateChange(props.chatId, id); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  async function create(event: FormEvent) {
    event.preventDefault();
    let parsed: unknown = value; try { parsed = JSON.parse(value); } catch { /* 普通文字可以直接保存 */ }
    try { await api.createProposal(props.chatId, { entity: `${ledgerPrefix(category)}${entity}`, key, new_value: parsed, reason: "用户手动修改" }); setEntity(""); setValue(""); await props.onRefresh(); } catch (reason) { props.onError(reason); }
  }
  return <div className="panel-stack">
    <div className="ledger-tabs">{categories.map((item) => <button className={category === item.id ? "active" : ""} onClick={() => setCategory(item.id)} key={item.id}>{item.label}<small>{grouped[item.id].length}</small></button>)}</div>
    {grouped[category].length === 0 ? <Empty text={`还没有${categories.find((item) => item.id === category)?.label}记录。`} /> : grouped[category].map((entry) => <article className="ledger-card" key={entry.id}><header><strong>{stripLedgerPrefix(entry.entity)}</strong><span>第 {entry.version} 版</span></header><div><small>{entry.key}</small><code>{displayLedgerValue(entry.value)}</code></div></article>)}
    <section className="pending-ledger"><h3>等待确认 <small>{pending.length}</small></h3>{pending.length === 0 ? <p className="muted">目前没有需要确认的变化。</p> : pending.map((item) => <article className="proposal-card" key={item.id}><header><strong>{stripLedgerPrefix(item.entity)} · {item.key}</strong><span>待确认</span></header><div className="value-change"><code>{displayValue(item.old_value)}</code><b>→</b><code>{displayValue(item.new_value)}</code></div><p>{item.reason}</p><footer><button onClick={() => void resolve(item.id, "reject")}>不采用</button><button className="approve" onClick={() => void resolve(item.id, "approve")}>确认</button></footer></article>)}</section>
    {history.length > 0 && <details className="ledger-history"><summary>修改记录（{history.length}）</summary>{history.map((item) => <div key={item.id}><span>{item.status === "approved" ? "已自动采用" : item.status === "reverted" ? "已撤销" : "未采用"}</span><strong>{stripLedgerPrefix(item.entity)} · {item.key}</strong><code>{displayValue(item.new_value)}</code>{item.status === "approved" && <button onClick={() => void undo(item.id)}>撤销</button>}</div>)}</details>}
    <form className="mini-form" onSubmit={create}><h3>手动添加记录</h3><select value={category} onChange={(e) => setCategory(e.target.value as LedgerCategory)}>{categories.filter((item) => item.id !== "other").map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select><div className="two-columns"><input value={entity} onChange={(e) => setEntity(e.target.value)} placeholder="名称" required /><input value={key} onChange={(e) => setKey(e.target.value)} placeholder="项目" required /></div><input value={value} onChange={(e) => setValue(e.target.value)} placeholder="内容" required /><button>等待确认</button></form>
  </div>;
}

function RetrievalPanel(props: MemoryHubProps & { chatId: string }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RetrievedMemory[]>(props.retrieved);
  async function search(event: FormEvent) { event.preventDefault(); try { setResults(await api.searchMemories(props.chatId, query)); } catch (reason) { props.onError(reason); } }
  const shown = results.length ? results : props.retrieved;
  return <div className="panel-stack"><form className="retrieval-search" onSubmit={search}><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索事件、人物或物品" required /><button>搜索</button></form>{shown.length === 0 ? <Empty text="暂无相关回忆" /> : shown.map((item) => <article className="retrieval-card" key={item.memory.id}><header><span>{memoryKindLabel(item.memory.kind)}</span><strong>{item.score.toFixed(3)}</strong></header><p>{item.memory.content}</p><small>{item.retrieval_reason}</small></article>)}</div>;
}

function DiagnosticsPanel(props: MemoryHubProps & { chatId: string }) {
  async function resolve(id: string, action: "resolve" | "dismiss") { try { await api.resolveAudit(props.chatId, id, action); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  async function resolveState(id: string, action: "approve" | "reject") { try { await api.resolveProposal(props.chatId, id, action); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  async function undo(id: string) { try { await api.undoStateChange(props.chatId, id); await props.onRefresh(); } catch (reason) { props.onError(reason); } }
  const pending = props.proposals.filter((item) => item.status === "pending");
  const history = props.proposals.filter((item) => item.status !== "pending").slice(0, 30);
  return <div className="panel-stack">
    <details open><summary>待确认变化（{pending.length}）</summary>{pending.length === 0 ? <Empty text="目前没有需要确认的变化。" /> : pending.map((item) => <article className="proposal-card" key={item.id}><header><strong>{stripLedgerPrefix(item.entity)} · {item.key}</strong><span>待确认</span></header><div className="value-change"><code>{displayValue(item.old_value)}</code><b>→</b><code>{displayValue(item.new_value)}</code></div><p>{item.reason}</p><footer><button onClick={() => void resolveState(item.id, "reject")}>不采用</button><button className="approve" onClick={() => void resolveState(item.id, "approve")}>确认</button></footer></article>)}</details>
    <details open><summary>冲突（{props.audits.length}）</summary>{props.audits.length === 0 ? <Empty text="暂无冲突" /> : props.audits.map((issue) => <article className={`audit-card ${issue.status}`} key={issue.id}><header><strong>{issue.category === "numeric_state_conflict" ? "数值冲突" : issue.category}</strong><span>{issue.status}</span></header><p>{issue.description}</p>{issue.status === "open" && <footer><button onClick={() => void resolve(issue.id, "dismiss")}>忽略</button><button className="approve" onClick={() => void resolve(issue.id, "resolve")}>已修复</button></footer>}</article>)}</details>
    {history.length > 0 && <details><summary>修改记录（{history.length}）</summary><div className="ledger-history">{history.map((item) => <div key={item.id}><span>{item.status === "approved" ? "已采用" : item.status === "reverted" ? "已撤销" : "未采用"}</span><strong>{stripLedgerPrefix(item.entity)} · {item.key}</strong><code>{displayValue(item.new_value)}</code>{item.status === "approved" && <button onClick={() => void undo(item.id)}>撤销</button>}</div>)}</div></details>}
    {props.debugMode && <details><summary>运行记录（{props.traces.length}）</summary>{props.traces.map((trace) => <details className="trace-card" key={trace.id}><summary><span>步骤 {trace.step}</span><strong>{trace.event_type}</strong><time>{formatDateTime(trace.created_at)}</time></summary><pre>{JSON.stringify(trace.payload, null, 2)}</pre></details>)}</details>}
  </div>;
}

interface ContextSectionDebug {
  key: string;
  label: string;
  enabled: boolean;
  reason: string;
  content: string;
  estimated_tokens: number;
  characters: number;
}

interface ContextTracePayload {
  token_budget?: {
    input_budget: number;
    estimated_input_tokens: number;
    original_estimated_tokens: number;
    remaining_tokens: number;
    dropped_old_messages: number;
    dropped_messages?: { role: string; estimated_tokens: number; preview: string }[];
    system_prompt_truncated: boolean;
    tokenizer?: string;
    model?: string | null;
    sections?: ContextSectionDebug[];
    world_book_triggers?: { id: string; title: string; included: boolean; priority: number; reason: string }[];
    rag_retrieval?: { memory_id: string; score: number; reason: string; preview: string }[];
    final_prompt?: { role: string; content: string | null }[];
  };
}

interface ModelMetricPayload {
  duration_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  estimated_cost_usd?: number;
  pricing_configured?: boolean;
}

function ContextDebugPanel({ traces }: { traces: AgentTrace[] }) {
  const [visible, setVisible] = useState({ sections: true, triggers: false, rag: true, prompt: false, metrics: true });
  const contextTrace = traces.find((trace) => trace.event_type === "context_built");
  if (!contextTrace) return <Empty text="发送一条消息后，这里会显示实际发送的上下文。" />;
  const payload = contextTrace.payload as ContextTracePayload;
  const budget = payload.token_budget;
  if (!budget) return <Empty text="这轮运行没有上下文诊断数据。" />;
  const modelMetrics = traces
    .filter((trace) => trace.turn_id === contextTrace.turn_id && ["model_response", "forced_model_response", "model_error"].includes(trace.event_type))
    .map((trace) => trace.payload as ModelMetricPayload);
  const duration = modelMetrics.reduce((sum, item) => sum + (item.duration_ms ?? 0), 0);
  const inputTokens = modelMetrics.reduce((sum, item) => sum + (item.input_tokens ?? 0), 0);
  const outputTokens = modelMetrics.reduce((sum, item) => sum + (item.output_tokens ?? 0), 0);
  const cost = modelMetrics.reduce((sum, item) => sum + (item.estimated_cost_usd ?? 0), 0);
  const pricingConfigured = modelMetrics.some((item) => item.pricing_configured);
  const completed = traces.find((trace) => trace.turn_id === contextTrace.turn_id && trace.event_type === "turn_completed");
  const turnDuration = Number((completed?.payload as { duration_ms?: number } | undefined)?.duration_ms ?? 0);
  const usagePercent = Math.min(100, budget.estimated_input_tokens / Math.max(1, budget.input_budget) * 100);

  return <div className="panel-stack context-debug">
    <div className="context-overview">
      <div><small>本轮输入</small><strong>{budget.estimated_input_tokens.toLocaleString()} Token</strong><span>预算 {budget.input_budget.toLocaleString()}</span></div>
      <div><small>剩余</small><strong>{budget.remaining_tokens.toLocaleString()}</strong><span>{budget.tokenizer ?? "估算器"}</span></div>
      <div><small>本轮耗时</small><strong>{turnDuration ? `${turnDuration.toFixed(0)} ms` : "—"}</strong><span>模型调用 {duration.toFixed(0)} ms</span></div>
      <div><small>费用估算</small><strong>{pricingConfigured ? `$${cost.toFixed(6)}` : "未设置单价"}</strong><span>{budget.model ?? "当前模型"}</span></div>
    </div>
    <div className="context-budget-bar"><i style={{ width: `${usagePercent}%` }} /><span>{usagePercent.toFixed(1)}%</span></div>
    <div className="debug-switches">
      {(["sections", "triggers", "rag", "prompt", "metrics"] as const).map((key) => <label key={key}><input type="checkbox" checked={visible[key]} onChange={(event) => setVisible((before) => ({ ...before, [key]: event.target.checked }))} />{{ sections: "上下文块", triggers: "世界书触发", rag: "RAG 分数", prompt: "最终 Prompt", metrics: "裁剪记录" }[key]}</label>)}
    </div>

    {visible.sections && <section className="context-section-list"><h3>发送顺序</h3>{(budget.sections ?? []).map((section, index) => <details key={section.key} className={section.enabled ? "context-section enabled" : "context-section disabled"}><summary><b>{index + 1}</b><span><strong>{section.label}</strong><small>{section.reason}</small></span><em>{section.enabled ? `${section.estimated_tokens} Token` : "未加入"}</em></summary>{section.enabled && <pre>{section.content}</pre>}</details>)}</section>}

    {visible.metrics && <section className="context-debug-group"><h3>预算与裁剪</h3><p>组装前约 {budget.original_estimated_tokens.toLocaleString()} Token；裁掉 {budget.dropped_old_messages} 条旧消息{budget.system_prompt_truncated ? "，系统 Prompt 也进行了截断" : ""}。</p>{Boolean(budget.dropped_messages?.length) && <details><summary>查看被裁剪的消息</summary>{budget.dropped_messages?.map((item, index) => <article key={index}><strong>{item.role} · {item.estimated_tokens} Token</strong><p>{item.preview}</p></article>)}</details>}</section>}

    {visible.triggers && <section className="context-debug-group"><h3>世界书触发记录</h3>{(budget.world_book_triggers ?? []).map((item) => <article key={item.id} className={item.included ? "included" : "excluded"}><header><strong>{item.title}</strong><span>{item.included ? "已加入" : "未加入"} · 优先级 {item.priority}</span></header><p>{item.reason}</p></article>)}</section>}

    {visible.rag && <section className="context-debug-group"><h3>RAG 召回</h3>{(budget.rag_retrieval ?? []).length === 0 ? <p className="muted">本轮没有召回长期记忆。</p> : budget.rag_retrieval?.map((item) => <article key={item.memory_id}><header><strong>{item.score.toFixed(3)}</strong><span>{item.reason}</span></header><p>{item.preview}</p></article>)}</section>}

    {visible.prompt && <section className="context-debug-group final-prompt"><h3>最终 Prompt</h3>{budget.final_prompt?.map((message, index) => <details key={index}><summary>{index + 1}. {message.role}</summary><pre>{message.content ?? ""}</pre></details>)}</section>}
  </div>;
}

type LedgerCategory = "item" | "npc" | "scene" | "thread" | "other";
type ItemRecord = { owner: string; quantity: string; status: string; location: string; description: string };
function itemEntries(entries: StateEntry[]) { return entries.filter((entry) => /^(物品|item)\s*[:：]/i.test(entry.entity)); }
function itemValue(value: unknown): ItemRecord {
  if (typeof value === "string") return { owner: "", quantity: "", status: value, location: "", description: "" };
  const record = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  return {
    owner: String(record.owner ?? ""), quantity: String(record.quantity ?? ""),
    status: String(record.status ?? ""), location: String(record.location ?? ""),
    description: String(record.description ?? record.detail ?? ""),
  };
}
function groupLedger(entries: StateEntry[]): Record<LedgerCategory, StateEntry[]> { const result: Record<LedgerCategory, StateEntry[]> = { item: [], npc: [], scene: [], thread: [], other: [] }; entries.forEach((entry) => result[ledgerCategory(entry.entity, entry.key)].push(entry)); return result; }
function ledgerCategory(entity: string, key: string): LedgerCategory { const text = `${entity} ${key}`.toLowerCase(); if (/^(物品|item):|物品|背包|库存|持有|数量/.test(text)) return "item"; if (/^(npc|人物):|npc|人物|角色|外貌|穿着/.test(text)) return "npc"; if (/^(场景|scene):|场景|地点|位置|区域/.test(text)) return "scene"; if (/^(悬念|thread):|悬念|计划|任务|约定|谜题|伏笔/.test(text)) return "thread"; return "other"; }
function ledgerPrefix(category: LedgerCategory) { return { item: "物品:", npc: "NPC:", scene: "场景:", thread: "悬念:", other: "" }[category]; }
function stripLedgerPrefix(value: string) { return value.replace(/^(物品|NPC|场景|悬念):/i, ""); }
function displayValue(value: unknown) { if (value === null || value === undefined) return "未设置"; return typeof value === "string" ? value : JSON.stringify(value); }
function displayLedgerValue(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return displayValue(value);
  const item = value as Record<string, unknown>;
  const labels: [string, unknown][] = [
    ["归属", item.owner],
    ["数量", item.quantity],
    ["状态", item.status],
    ["位置", item.location],
  ];
  const details = labels
    .filter(([, field]) => field !== null && field !== undefined && String(field).trim() !== "")
    .map(([label, field]) => `${label}：${String(field)}`);
  return details.length ? details.join(" · ") : displayValue(value);
}
function memoryKindLabel(kind: Memory["kind"]) { return { episodic: "楼层", semantic: "事实", summary: "总结", implicit: "隐性" }[kind]; }
function importanceLabel(value: Npc["importance"]) { return { core: "核心", supporting: "配角", minor: "龙套" }[value]; }
function presenceLabel(value: Npc["presence"]) { return { present: "在场", nearby: "附近", away: "离场", unknown: "未知" }[value]; }
function factionStatusLabel(value: "rising" | "stable" | "strained" | "declining" | "dissolved") { return { rising: "上升", stable: "稳固", strained: "承压", declining: "衰落", dissolved: "瓦解" }[value]; }
function factionRelationLabel(value: "allied" | "friendly" | "neutral" | "cold" | "hostile") { return { allied: "盟友", friendly: "友好", neutral: "中立", cold: "冷淡", hostile: "敌对" }[value]; }
function worldEventStageLabel(value: "seed" | "developing" | "approaching" | "resolved" | "failed" | "dissipated") { return { seed: "萌芽", developing: "发展", approaching: "逼近", resolved: "完成", failed: "失败", dissipated: "消散" }[value]; }
function worldRumorTypeLabel(value: "announcement" | "report" | "rumor" | "sentiment") { return { announcement: "公告", report: "消息", rumor: "传闻", sentiment: "舆情" }[value]; }
function trendDirectionLabel(value: "rising" | "stable" | "falling") { return { rising: "上升", stable: "持平", falling: "回落" }[value]; }
function formatDateTime(value: string) { return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
function Empty({ text }: { text: string }) { return <p className="muted hub-empty">{text}</p>; }
