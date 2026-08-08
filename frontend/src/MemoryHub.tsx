import { FormEvent, useMemo, useState } from "react";
import { api } from "./api";
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
} from "./types";

export type MemoryHubTab = "summary" | "delta" | "world" | "timeline" | "ledger" | "retrieval" | "diagnostics";

interface MemoryHubProps {
  chatId: string | null;
  activeTab: MemoryHubTab;
  onTab: (tab: MemoryHubTab) => void;
  memories: Memory[];
  memoryGraph: NarrativeNode[];
  deltas: NarrativeDelta[];
  coverage: MemoryCoverage | null;
  scenes: SceneNode[];
  npcs: Npc[];
  retrieved: RetrievedMemory[];
  timeline: TimelineAnchor[];
  stateEntries: StateEntry[];
  proposals: StateProposal[];
  audits: AuditIssue[];
  traces: AgentTrace[];
  onRefresh: () => Promise<void> | void;
  onError: (reason: unknown) => void;
  onClose: () => void;
}

export function MemoryHub(props: MemoryHubProps) {
  const tabs: { id: MemoryHubTab; label: string; count?: number }[] = [
    { id: "summary", label: "剧情摘要", count: props.memoryGraph.length },
    { id: "delta", label: "本轮变化", count: props.deltas.filter((item) => item.valid).length },
    { id: "world", label: "世界", count: props.scenes.length + props.npcs.length },
    { id: "timeline", label: "时间线", count: props.timeline.length },
    { id: "ledger", label: "记录", count: props.proposals.filter((item) => item.status === "pending").length },
    { id: "retrieval", label: "相关回忆", count: props.retrieved.length },
    { id: "diagnostics", label: "检查", count: props.audits.filter((item) => item.status === "open").length },
  ];
  return (
    <aside className="inspector memory-hub">
      <div className="inspector-title"><span>故事资料</span><button className="icon-button" onClick={props.onClose} aria-label="收起故事资料">×</button></div>
      <div className="tabs memory-tabs">
        {tabs.map((tab) => <button key={tab.id} className={props.activeTab === tab.id ? "active" : ""} onClick={() => props.onTab(tab.id)}>{tab.label}{Boolean(tab.count) && <em>{tab.count}</em>}</button>)}
      </div>
      <div className="inspector-content">
        {!props.chatId ? <Empty text="选择故事后，这里会显示整理好的剧情资料。" />
          : props.activeTab === "summary" ? <SummaryPanel {...props} chatId={props.chatId} />
          : props.activeTab === "delta" ? <DeltaPanel deltas={props.deltas} />
          : props.activeTab === "world" ? <WorldGraphPanel {...props} chatId={props.chatId} />
          : props.activeTab === "timeline" ? <TimelinePanel {...props} chatId={props.chatId} />
          : props.activeTab === "ledger" ? <LedgerPanel {...props} chatId={props.chatId} />
          : props.activeTab === "retrieval" ? <RetrievalPanel {...props} chatId={props.chatId} />
          : <DiagnosticsPanel {...props} chatId={props.chatId} />}
      </div>
    </aside>
  );
}

function DeltaPanel({ deltas }: { deltas: NarrativeDelta[] }) {
  if (!deltas.length) return <Empty text="暂无记录" />;
  return <div className="panel-stack delta-list">{[...deltas].reverse().map((delta) => <article key={delta.id} className={delta.valid ? "" : "invalid"}><header><strong>{delta.payload.summary || "这一轮发生的事"}</strong><span>{delta.valid ? "当前版本" : "对应内容已改写"}</span></header>{delta.payload.time_change && <p>时间：{delta.payload.time_change}</p>}{Boolean(delta.payload.facts?.length) && <ul>{delta.payload.facts?.map((fact) => <li key={fact}>{fact}</li>)}</ul>}{Boolean(delta.payload.numbers?.length) && <p>数值：{delta.payload.numbers?.map((item) => `${item.name} ${item.value}${item.unit}`).join("；")}</p>}<small>{new Date(delta.created_at).toLocaleString()}</small></article>)}</div>;
}

function WorldGraphPanel(props: MemoryHubProps & { chatId: string }) {
  const [mode, setMode] = useState<"scenes" | "npcs">("scenes");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [parentId, setParentId] = useState("");
  const [current, setCurrent] = useState(false);
  const [relation, setRelation] = useState("");
  const [importance, setImportance] = useState<Npc["importance"]>("supporting");
  const [presence, setPresence] = useState<Npc["presence"]>("away");
  const [locationId, setLocationId] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      if (mode === "scenes") {
        await api.createScene(props.chatId, { name, description, parent_id: parentId || null, is_current: current });
      } else {
        await api.createNpc(props.chatId, { name, description, relation_to_user: relation, relations: [], importance, presence, location_scene_id: locationId || null, outfit: "", condition: "" });
      }
      setName(""); setDescription(""); setRelation(""); setCurrent(false);
      await props.onRefresh();
    } catch (reason) { props.onError(reason); }
  }
  async function remove(kind: "scene" | "npc", id: string) {
    try { if (kind === "scene") await api.deleteScene(props.chatId, id); else await api.deleteNpc(props.chatId, id); await props.onRefresh(); }
    catch (reason) { props.onError(reason); }
  }
  const sceneById = new Map(props.scenes.map((item) => [item.id, item]));
  return <div className="panel-stack world-graph">
    <div className="ledger-tabs">
      <button className={mode === "scenes" ? "active" : ""} onClick={() => setMode("scenes")}>场景<small>{props.scenes.length}</small></button>
      <button className={mode === "npcs" ? "active" : ""} onClick={() => setMode("npcs")}>人物<small>{props.npcs.length}</small></button>
    </div>
    {mode === "scenes" ? <div className="scene-tree">
      {props.scenes.length === 0 ? <Empty text="暂无场景" /> : [...props.scenes].sort((a, b) => a.path.join("/").localeCompare(b.path.join("/"))).map((scene) => <article className={scene.is_current ? "current" : ""} style={{ marginLeft: `${Math.max(scene.path.length - 1, 0) * 12}px` }} key={scene.id}><header><strong>{scene.name}</strong>{scene.is_current && <span>当前位置</span>}</header><small>{scene.path.join(" › ")}</small>{scene.description && <p>{scene.description}</p>}<button onClick={() => void remove("scene", scene.id)}>删除</button></article>)}
    </div> : <div className="npc-graph">
      {props.npcs.length === 0 ? <Empty text="暂无人物" /> : props.npcs.map((npc) => <article key={npc.id}><header><strong>{npc.name}</strong><span>{importanceLabel(npc.importance)} · {presenceLabel(npc.presence)}</span></header>{npc.description && <p>{npc.description}</p>}<dl><dt>与玩家</dt><dd>{npc.relation_to_user || "未记录"}</dd><dt>位置</dt><dd>{sceneById.get(npc.location_scene_id ?? "")?.path.join(" › ") ?? "未知"}</dd>{npc.relations.map((item) => <><dt key={`${npc.id}-${item.target}-k`}>与 {item.target}</dt><dd key={`${npc.id}-${item.target}-v`}>{item.relation}</dd></>)}</dl><button onClick={() => void remove("npc", npc.id)}>删除</button></article>)}
    </div>}
    <form className="mini-form" onSubmit={submit}>
      <h3>添加{mode === "scenes" ? "场景" : "人物"}</h3>
      <input value={name} onChange={(event) => setName(event.target.value)} placeholder={mode === "scenes" ? "地点名称" : "人物名称"} required />
      <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="描述" rows={2} />
      {mode === "scenes" ? <><select value={parentId} onChange={(event) => setParentId(event.target.value)}><option value="">顶层地点</option>{props.scenes.map((scene) => <option value={scene.id} key={scene.id}>{scene.path.join(" › ")}</option>)}</select><label className="check-row"><input type="checkbox" checked={current} onChange={(event) => setCurrent(event.target.checked)} /><span>当前位置</span></label></> : <><input value={relation} onChange={(event) => setRelation(event.target.value)} placeholder="与玩家的关系" /><div className="two-columns"><select value={importance} onChange={(event) => setImportance(event.target.value as Npc["importance"])}><option value="core">核心角色</option><option value="supporting">重要配角</option><option value="minor">次要角色</option></select><select value={presence} onChange={(event) => setPresence(event.target.value as Npc["presence"])}><option value="present">在场</option><option value="nearby">附近</option><option value="away">离场</option><option value="unknown">未知</option></select></div><select value={locationId} onChange={(event) => setLocationId(event.target.value)}><option value="">位置未知</option>{props.scenes.map((scene) => <option value={scene.id} key={scene.id}>{scene.path.join(" › ")}</option>)}</select></>}
      <button>添加</button>
    </form>
  </div>;
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
  async function create(event: FormEvent) {
    event.preventDefault();
    let parsed: unknown = value; try { parsed = JSON.parse(value); } catch { /* 普通文字可以直接保存 */ }
    try { await api.createProposal(props.chatId, { entity: `${ledgerPrefix(category)}${entity}`, key, new_value: parsed, reason: "用户手动修改" }); setEntity(""); setValue(""); await props.onRefresh(); } catch (reason) { props.onError(reason); }
  }
  return <div className="panel-stack">
    <div className="ledger-tabs">{categories.map((item) => <button className={category === item.id ? "active" : ""} onClick={() => setCategory(item.id)} key={item.id}>{item.label}<small>{grouped[item.id].length}</small></button>)}</div>
    {grouped[category].length === 0 ? <Empty text={`还没有${categories.find((item) => item.id === category)?.label}记录。`} /> : grouped[category].map((entry) => <article className="ledger-card" key={entry.id}><header><strong>{stripLedgerPrefix(entry.entity)}</strong><span>第 {entry.version} 版</span></header><div><small>{entry.key}</small><code>{displayValue(entry.value)}</code></div></article>)}
    <section className="pending-ledger"><h3>等待确认 <small>{pending.length}</small></h3>{pending.length === 0 ? <p className="muted">目前没有需要确认的变化。</p> : pending.map((item) => <article className="proposal-card" key={item.id}><header><strong>{stripLedgerPrefix(item.entity)} · {item.key}</strong><span>待确认</span></header><div className="value-change"><code>{displayValue(item.old_value)}</code><b>→</b><code>{displayValue(item.new_value)}</code></div><p>{item.reason}</p><footer><button onClick={() => void resolve(item.id, "reject")}>不采用</button><button className="approve" onClick={() => void resolve(item.id, "approve")}>确认</button></footer></article>)}</section>
    {history.length > 0 && <details className="ledger-history"><summary>最近修改（{history.length}）</summary>{history.map((item) => <div key={item.id}><span>{item.status === "approved" ? "已采用" : "未采用"}</span><strong>{stripLedgerPrefix(item.entity)} · {item.key}</strong><code>{displayValue(item.new_value)}</code></div>)}</details>}
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
  return <div className="panel-stack"><details open><summary>冲突（{props.audits.length}）</summary>{props.audits.length === 0 ? <Empty text="暂无冲突" /> : props.audits.map((issue) => <article className={`audit-card ${issue.status}`} key={issue.id}><header><strong>{issue.category === "numeric_state_conflict" ? "数值冲突" : issue.category}</strong><span>{issue.status}</span></header><p>{issue.description}</p>{issue.status === "open" && <footer><button onClick={() => void resolve(issue.id, "dismiss")}>忽略</button><button className="approve" onClick={() => void resolve(issue.id, "resolve")}>已修复</button></footer>}</article>)}</details><details><summary>运行记录（{props.traces.length}）</summary>{props.traces.map((trace) => <details className="trace-card" key={trace.id}><summary><span>步骤 {trace.step}</span><strong>{trace.event_type}</strong><time>{formatDateTime(trace.created_at)}</time></summary><pre>{JSON.stringify(trace.payload, null, 2)}</pre></details>)}</details></div>;
}

type LedgerCategory = "item" | "npc" | "scene" | "thread" | "other";
function groupLedger(entries: StateEntry[]): Record<LedgerCategory, StateEntry[]> { const result: Record<LedgerCategory, StateEntry[]> = { item: [], npc: [], scene: [], thread: [], other: [] }; entries.forEach((entry) => result[ledgerCategory(entry.entity, entry.key)].push(entry)); return result; }
function ledgerCategory(entity: string, key: string): LedgerCategory { const text = `${entity} ${key}`.toLowerCase(); if (/^(物品|item):|物品|背包|库存|持有|数量/.test(text)) return "item"; if (/^(npc|人物):|npc|人物|角色|外貌|穿着/.test(text)) return "npc"; if (/^(场景|scene):|场景|地点|位置|区域/.test(text)) return "scene"; if (/^(悬念|thread):|悬念|计划|任务|约定|谜题|伏笔/.test(text)) return "thread"; return "other"; }
function ledgerPrefix(category: LedgerCategory) { return { item: "物品:", npc: "NPC:", scene: "场景:", thread: "悬念:", other: "" }[category]; }
function stripLedgerPrefix(value: string) { return value.replace(/^(物品|NPC|场景|悬念):/i, ""); }
function displayValue(value: unknown) { if (value === null || value === undefined) return "未设置"; return typeof value === "string" ? value : JSON.stringify(value); }
function memoryKindLabel(kind: Memory["kind"]) { return { episodic: "楼层", semantic: "事实", summary: "总结", implicit: "隐性" }[kind]; }
function importanceLabel(value: Npc["importance"]) { return { core: "核心", supporting: "配角", minor: "龙套" }[value]; }
function presenceLabel(value: Npc["presence"]) { return { present: "在场", nearby: "附近", away: "离场", unknown: "未知" }[value]; }
function formatDateTime(value: string) { return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
function Empty({ text }: { text: string }) { return <p className="muted hub-empty">{text}</p>; }
