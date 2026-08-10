import { useEffect, useState } from "react";
import { api } from "../api";
import { HelpTip } from "./HelpTip";
import { ThemedSelect } from "./ThemedSelect";
import type { Chat, ChatSkillSelection, ExtensionCatalog, PluginCreate } from "../types";

const EMPTY_PLUGIN: PluginCreate = {
  id: "",
  name: "",
  description: "",
  version: "",
  url: "",
  transport: "streamable_http",
  capabilities: ["tools"],
  allowed_tools: [],
  command: "",
  args: [],
  environment_variables: [],
  trusted: false,
  timeout_seconds: 30,
  auth_token: "",
};

export function ExtensionSettings({ selectedChatId }: { selectedChatId: string | null }) {
  const [catalog, setCatalog] = useState<ExtensionCatalog | null>(null);
  const [plugin, setPlugin] = useState<PluginCreate>(EMPTY_PLUGIN);
  const [stories, setStories] = useState<Chat[]>([]);
  const [storyId, setStoryId] = useState("");
  const [storySkills, setStorySkills] = useState<ChatSkillSelection | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [pendingArchive, setPendingArchive] = useState<{ kind: "skill" | "plugin"; id: string; name: string } | null>(null);

  useEffect(() => {
    void refresh(false);
    void api.chats().then((items) => {
      setStories(items);
      const initial = items.find((item) => item.id === selectedChatId) ?? items[0];
      if (initial) void selectStory(initial.id);
    }).catch((reason) => setNotice({ kind: "error", text: errorMessage(reason) }));
  }, []);

  async function selectStory(id: string) {
    setStoryId(id);
    if (!id) {
      setStorySkills(null);
      return;
    }
    try {
      setStorySkills(await api.chatSkills(id));
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    }
  }

  async function updateStorySkills(mode: "all" | "selected", skillIds: string[]) {
    if (!storyId) return;
    try {
      setBusy("story-skills");
      setStorySkills(await api.updateChatSkills(storyId, { mode, skill_ids: skillIds }));
      setNotice({ kind: "ok", text: mode === "all" ? "这个故事会使用所有已启用的技能。" : "这个故事的技能范围已保存。" });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function refresh(rescan: boolean) {
    try {
      setBusy("refresh");
      setNotice(null);
      setCatalog(rescan ? await api.reloadExtensions() : await api.extensions());
      if (rescan) setNotice({ kind: "ok", text: "已重新扫描本机扩展目录。" });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function toggle(kind: "skill" | "plugin", id: string, enabled: boolean) {
    try {
      setBusy(`${kind}:${id}`);
      if (kind === "skill") await api.toggleSkill(id, enabled);
      else await api.togglePlugin(id, enabled);
      setCatalog(await api.extensions());
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function registerPlugin() {
    try {
      setBusy("register");
      setNotice(null);
      await api.registerPlugin({ ...plugin, id: plugin.id.trim(), name: plugin.name.trim(), url: plugin.url.trim(), command: plugin.command.trim() });
      setPlugin(EMPTY_PLUGIN);
      setCatalog(await api.extensions());
      setNotice({ kind: "ok", text: "服务已添加。确认连接无误后即可启用。" });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function testPlugin(id: string) {
    try {
      setBusy(`test:${id}`);
      const result = await api.testPlugin(id);
      setCatalog(await api.extensions());
      setNotice({ kind: "ok", text: `连接成功，可用工具 ${result.tool_count} 项。` });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function archivePlugin(id: string, name: string) {
    try {
      setPendingArchive(null);
      setBusy(`archive-plugin:${id}`);
      await api.archivePlugin(id);
      setCatalog(await api.extensions());
      setNotice({ kind: "ok", text: "插件已归档，可从本机归档目录恢复。" });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function installPlugin(file: File | undefined) {
    if (!file) return;
    try {
      setBusy("install-plugin");
      setNotice(null);
      const installed = await api.installPlugin(file);
      setCatalog(await api.extensions());
      setNotice({ kind: "ok", text: `插件“${installed.name}”已安装，检查内容后再启用。` });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function trustPlugin(id: string, trusted: boolean) {
    try {
      setBusy(`trust:${id}`);
      await api.trustPlugin(id, trusted);
      setCatalog(await api.extensions());
      setNotice({ kind: "ok", text: trusted ? "已允许该插件启动本机程序。" : "已撤销信任并停用该插件。" });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function exportPlugin(id: string) {
    try {
      setBusy(`export-plugin:${id}`);
      downloadBlob(await api.exportPlugin(id), `${id}.zip`);
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function installSkill(file: File | undefined) {
    if (!file) return;
    try {
      setBusy("install-skill");
      setNotice(null);
      const installed = await api.installSkill(file);
      setCatalog(await api.extensions());
      setNotice({ kind: "ok", text: `技能「${installed.name}」已安装。` });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function archiveSkill(id: string, name: string) {
    try {
      setPendingArchive(null);
      setBusy(`archive:${id}`);
      await api.archiveSkill(id);
      setCatalog(await api.extensions());
      setNotice({ kind: "ok", text: "技能已归档，可从本机归档目录恢复。" });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  async function exportSkill(id: string) {
    try {
      setBusy(`export:${id}`);
      downloadBlob(await api.exportSkill(id), `${id}.zip`);
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="settings-section extension-settings">
      <div className="settings-heading extension-heading">
        <div><h3>扩展目录 <HelpTip text="这里列出保存在当前设备上的技能与服务。停用的项目会保留在本机，但不会在故事中使用。" /></h3><p>管理本机技能，以及与其他服务的连接。</p></div>
        <button className="secondary-button" onClick={() => void refresh(true)} disabled={!!busy}>重新扫描</button>
      </div>
      {notice && <p className={`extension-notice ${notice.kind}`}>{notice.text}</p>}

      <section className="extension-scope">
        <div><strong>适用故事 <HelpTip text="可以让一个故事使用全部已启用技能，也可以只为它挑选一部分。这里的选择不会影响其他故事。" /></strong><small>为每个故事保留合适的技能。</small></div>
        {stories.length ? <div className="extension-scope-controls"><ThemedSelect value={storyId} options={stories.map((story) => ({ value: story.id, label: story.title }))} onChange={(value) => void selectStory(value)} ariaLabel="选择故事" className="story-select" /><ThemedSelect value={storySkills?.mode ?? "all"} options={[{ value: "all", label: "使用全部技能" }, { value: "selected", label: "只用所选技能" }]} disabled={!storySkills || !!busy} onChange={(value) => void updateStorySkills(value, storySkills?.skill_ids ?? [])} ariaLabel="选择技能范围" className="scope-select" /></div> : <small>创建故事后，可以在这里设置它使用的技能。</small>}
      </section>

      <section className="extension-block">
        <header><div><strong>技能库 <HelpTip text="技能由说明和参考资料组成，可在不同故事之间复用。只有需要时才会读取具体内容。" /></strong><small>安装、启用和整理保存在本机的技能。</small></div><div className="extension-header-actions"><label className="file-button"><input type="file" accept=".zip,application/zip" disabled={!!busy} onChange={(event) => { void installSkill(event.target.files?.[0]); event.currentTarget.value = ""; }} />安装技能</label><span>{catalog?.skills.length ?? 0}</span></div></header>
        {!catalog ? <p className="settings-loading">正在读取扩展…</p> : catalog.skills.length === 0 ? (
          <div className="extension-empty"><p>还没有安装技能。</p><small>选择“安装技能”，或将技能放入本机扩展目录后重新扫描。</small></div>
        ) : <div className="extension-list">{catalog.skills.map((item) => (
          <article className="extension-card" key={item.id}>
            <div><div className="extension-card-title"><strong>{item.name}</strong><span className={`extension-readiness ${item.readiness}`}>{item.readiness === "ready" ? "可用" : item.readiness === "incompatible" ? "当前设备不可用" : "需要配置"}</span></div><small>{item.id}{item.version ? ` · ${item.version}` : ""} · {item.plugin_id ? `来自插件 ${item.plugin_id}` : item.source === "archive" ? "安装包" : "本机"} · 已使用 {item.use_count} 次</small><p>{item.description}</p>{item.missing_requirements.length > 0 && <em>尚需配置：{item.missing_requirements.join("、")}</em>}{item.warnings.map((warning) => <em key={warning}>{warning}</em>)}</div>
            <div className="extension-actions">{storySkills?.mode === "selected" && <label className="extension-switch story-skill-switch"><input type="checkbox" checked={storySkills.skill_ids.includes(item.id)} disabled={!!busy || !item.enabled} onChange={(event) => { const ids = event.target.checked ? [...storySkills.skill_ids, item.id] : storySkills.skill_ids.filter((id) => id !== item.id); void updateStorySkills("selected", ids); }} /><span>此故事</span></label>}<button className="ghost-button" disabled={!!busy} onClick={() => void exportSkill(item.id)}>导出</button>{!item.plugin_id && <button className="ghost-button danger" disabled={!!busy} onClick={() => setPendingArchive({ kind: "skill", id: item.id, name: item.name })}>归档</button>}<label className="extension-switch"><input type="checkbox" checked={item.enabled} disabled={!!busy || item.readiness !== "ready"} onChange={(event) => void toggle("skill", item.id, event.target.checked)} /><span>{item.enabled ? "全局启用" : "全局停用"}</span></label></div>
          </article>
        ))}</div>}
      </section>

      <section className="extension-block">
        <header><div><strong>插件 <HelpTip text="插件是一套可安装的扩展包，可以同时带来技能、工具服务与配套资源。支持 Saraswati 清单，也兼容 Codex 风格的插件目录。" /></strong><small>从本机安装、检查并启用完整的功能扩展。</small></div><div className="extension-header-actions"><label className="file-button"><input type="file" accept=".zip,application/zip" disabled={!!busy} onChange={(event) => { void installPlugin(event.target.files?.[0]); event.currentTarget.value = ""; }} />安装插件</label><span>{catalog?.plugins.length ?? 0}</span></div></header>
        {catalog && !catalog.mcp_sdk_available && <p className="extension-warning">工具连接组件尚未安装；只含技能的插件仍可使用。</p>}
        {catalog?.plugins.length ? <div className="extension-list">{catalog.plugins.map((item) => (
          <article className="extension-card" key={item.id}>
            <div><div className="extension-card-title"><strong>{item.name}</strong><span className="extension-readiness ready">{pluginTypeLabel(item.plugin_type)}</span></div><small>{item.id}{item.version ? ` · ${item.version}` : ""} · {item.manifest_format === "codex" ? "Codex 兼容" : item.manifest_format === "legacy" ? "旧版兼容" : "Saraswati"}</small><p>{item.description || "暂无说明"}</p><small>{item.skills.length} 项技能 · {item.mcp_servers.length} 项工具服务 · {item.resources.length} 个文件</small>{item.missing_requirements.length > 0 && <em>尚需配置：{item.missing_requirements.join("、")}</em>}{item.tools.length > 0 && <small>已发现工具：{item.tools.join("、")}</small>}{item.error && <em>{item.error}</em>}</div>
            <div className="extension-actions">{item.mcp_servers.length > 0 && <button className="ghost-button" disabled={!!busy} onClick={() => void testPlugin(item.id)}>测试</button>}{item.mcp_servers.some((server) => server.transport === "stdio") && !item.trusted && <button className="ghost-button" disabled={!!busy} onClick={() => void trustPlugin(item.id, true)}>信任</button>}<button className="ghost-button" disabled={!!busy} onClick={() => void exportPlugin(item.id)}>导出</button><button className="ghost-button danger" disabled={!!busy} onClick={() => setPendingArchive({ kind: "plugin", id: item.id, name: item.name })}>归档</button><label className="extension-switch"><input type="checkbox" checked={item.enabled} disabled={!!busy || item.missing_requirements.length > 0 || (item.mcp_servers.some((server) => server.transport === "stdio") && !item.trusted)} onChange={(event) => void toggle("plugin", item.id, event.target.checked)} /><span>{item.enabled ? "已启用" : "已停用"}</span></label></div>
          </article>
        ))}</div> : null}
        <div className="plugin-form">
          <div className="plugin-form-heading"><strong>快速创建工具插件</strong><small>没有现成安装包时，可以直接填写 MCP 连接信息。</small></div>
          <div className="settings-grid"><label className="settings-field"><span>服务标识</span><input value={plugin.id} onChange={(event) => setPlugin({ ...plugin, id: event.target.value })} placeholder="my-service" /></label><label className="settings-field"><span>服务名称</span><input value={plugin.name} onChange={(event) => setPlugin({ ...plugin, name: event.target.value })} placeholder="我的工具服务" /></label></div>
          <label className="settings-field"><span>连接方式</span><ThemedSelect value={plugin.transport} options={[{ value: "streamable_http", label: "HTTP" }, { value: "sse", label: "SSE（兼容模式）" }, { value: "stdio", label: "本机程序" }]} onChange={(value) => setPlugin({ ...plugin, transport: value as PluginCreate["transport"] })} ariaLabel="选择连接方式" /></label>
          {plugin.transport === "stdio" ? <><label className="settings-field"><span>启动命令</span><input value={plugin.command} onChange={(event) => setPlugin({ ...plugin, command: event.target.value })} placeholder="npx" /></label><label className="settings-field"><span>参数（每行一个）</span><textarea rows={3} value={plugin.args.join("\n")} onChange={(event) => setPlugin({ ...plugin, args: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })} placeholder={'-y\n@modelcontextprotocol/server-filesystem\nC:\\Stories'} /></label><label className="settings-field"><span>继承环境变量名（逗号分隔）</span><input value={plugin.environment_variables.join(", ")} onChange={(event) => setPlugin({ ...plugin, environment_variables: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} placeholder="MAP_API_KEY" /></label><label className="check-row plugin-trust"><input type="checkbox" checked={plugin.trusted} onChange={(event) => setPlugin({ ...plugin, trusted: event.target.checked })} /><span>我信任此命令并允许 Saraswati 启动该本机进程</span></label></> : <><label className="settings-field"><span>MCP 地址</span><input value={plugin.url} onChange={(event) => setPlugin({ ...plugin, url: event.target.value })} placeholder="http://127.0.0.1:9000/mcp" /></label><label className="settings-field"><span>Bearer Token（可选）</span><input type="password" value={plugin.auth_token} onChange={(event) => setPlugin({ ...plugin, auth_token: event.target.value })} autoComplete="new-password" placeholder="写入本机独立凭据文件，不会经 API 回传" /></label></>}
          <label className="settings-field"><span>允许使用的工具</span><input value={plugin.allowed_tools.join(", ")} onChange={(event) => setPlugin({ ...plugin, allowed_tools: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} placeholder="留空表示使用服务提供的全部工具" /></label>
          <label className="settings-field"><span>备注</span><input value={plugin.description} onChange={(event) => setPlugin({ ...plugin, description: event.target.value })} placeholder="简要说明这个服务的用途" /></label>
          <button className="primary-button" onClick={() => void registerPlugin()} disabled={!!busy || !plugin.id.trim() || !plugin.name.trim() || (plugin.transport === "stdio" ? !plugin.command.trim() || !plugin.trusted : !plugin.url.trim())}>创建插件</button>
        </div>
      </section>
      {pendingArchive && <div className="extension-confirm-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPendingArchive(null); }}><section className="extension-confirm" role="alertdialog" aria-modal="true" aria-labelledby="extension-confirm-title"><small>整理扩展</small><h3 id="extension-confirm-title">归档「{pendingArchive.name}」？</h3><p>{pendingArchive.kind === "plugin" ? "插件及其内置技能会停止使用，保存的连接凭据也会移除。" : "技能将停止使用，但文件仍会保留在本机归档目录。"}</p><div><button className="ghost-button" onClick={() => setPendingArchive(null)}>取消</button><button className="primary-button danger" onClick={() => pendingArchive.kind === "plugin" ? void archivePlugin(pendingArchive.id, pendingArchive.name) : void archiveSkill(pendingArchive.id, pendingArchive.name)}>确认归档</button></div></section></div>}
    </div>
  );
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "发生了未知错误";
}

function pluginTypeLabel(type: "skill" | "tool" | "hybrid" | "resource") {
  return type === "hybrid" ? "综合插件" : type === "skill" ? "技能插件" : type === "tool" ? "工具插件" : "资源插件";
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
