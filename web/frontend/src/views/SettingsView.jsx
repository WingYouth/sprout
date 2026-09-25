import { useEffect, useState } from "react";
import { getApiToken, savePreferences, setApiToken } from "../api";

const labels = {
  runtime: "运行时",
  model: "模型",
  storage: "存储",
  security: "安全",
  mcp: "MCP",
  evolution: "成长平面",
  web: "Web",
  skills_dir: "技能目录"
};

function formatConfigValue(value) {
  return Object.entries(value)
    .map(([key, val]) => {
      const display = val === null ? "null" : typeof val === "object" ? JSON.stringify(val) : val;
      return `${key}: ${display}`;
    })
    .join(" · ");
}

function Field({ label, children, className = "" }) {
  return (
    <div className={`field ${className}`}>
      <label>{label}</label>
      {children}
    </div>
  );
}

function SwitchField({ label, checked, onChange }) {
  return (
    <div className="switch-row">
      <span>{label}</span>
      <span className="switch">
        <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
        <span className="track" />
        <span className="thumb" />
      </span>
    </div>
  );
}

export default function SettingsView({ settings, preferences, configPath, onSaved }) {
  const [preferenceForm, setPreferenceForm] = useState({
    user_name: preferences.user_name || "web-user",
    theme: preferences.theme || "light",
    language: preferences.language || "zh",
    fun_effects: preferences.fun_effects !== false
  });
  const [modelForm, setModelForm] = useState(() => ({
    gateway: settings?.model?.provider || preferences.model_config?.gateway || "aiyallm",
    model: settings?.model?.model || preferences.model_config?.model || "",
    base_url:
      settings?.model?.base_url ||
      preferences.model_config?.base_url ||
      "",
    api_key_env:
      settings?.model?.api_key_env ||
      preferences.model_config?.api_key_env ||
      "DEEPSEEK_API_KEY",
    timeout_seconds:
      settings?.model?.timeout_seconds ?? preferences.model_config?.timeout_seconds ?? 60,
    temperature:
      settings?.model?.temperature ?? preferences.model_config?.temperature ?? ""
  }));
  const [runtimeForm, setRuntimeForm] = useState(() => ({
    default_agent: settings?.runtime?.default_agent || preferences.runtime_config?.default_agent || "assistant",
    max_tool_steps: settings?.runtime?.max_tool_steps ?? preferences.runtime_config?.max_tool_steps ?? 8,
    session_turn_limit: settings?.runtime?.session_turn_limit ?? preferences.runtime_config?.session_turn_limit ?? 20
  }));
  const [securityForm, setSecurityForm] = useState(() => ({
    allow_medium_risk: settings?.security?.allow_medium_risk ?? preferences.security_config?.allow_medium_risk ?? true,
    require_approval: settings?.security?.require_approval ?? preferences.security_config?.require_approval ?? true,
    organization_deny_prefixes: (settings?.security?.organization_deny_prefixes || preferences.security_config?.organization_deny_prefixes || []).join(", "),
    workspace_deny_prefixes: (settings?.security?.workspace_deny_prefixes || preferences.security_config?.workspace_deny_prefixes || []).join(", ")
  }));
  const [webForm, setWebForm] = useState(() => ({
    host: settings?.web?.host || preferences.web_config?.host || "127.0.0.1",
    port: settings?.web?.port ?? preferences.web_config?.port ?? 8000
  }));
  const [evolutionForm, setEvolutionForm] = useState(() => ({
    enabled: settings?.evolution?.enabled ?? preferences.evolution_config?.enabled ?? true,
    approval_required: settings?.evolution?.approval_required ?? preferences.evolution_config?.approval_required ?? true,
    level: settings?.evolution?.level ?? preferences.evolution_config?.level ?? 1,
    growth_dsn: settings?.evolution?.growth_dsn || preferences.evolution_config?.growth_dsn || "~/.sprout/data/growth.db"
  }));
  const [storageForm, setStorageForm] = useState(() => ({
    core: settings?.storage?.core || preferences.storage_config?.core || "~/.sprout/data/sprout_core.db",
    conversation: settings?.storage?.conversation || preferences.storage_config?.conversation || "~/.sprout/data/sprout_conversation.db",
    knowledge: settings?.storage?.knowledge || preferences.storage_config?.knowledge || "~/.sprout/data/sprout_knowledge.db",
    audit: settings?.storage?.audit || preferences.storage_config?.audit || "~/.sprout/data/sprout_audit.db",
    usage: settings?.storage?.usage || preferences.storage_config?.usage || "~/.sprout/data/sprout_usage.db",
    cache: settings?.storage?.cache || preferences.storage_config?.cache || "memory",
    blobs_dir: settings?.storage?.blobs_dir || preferences.storage_config?.blobs_dir || "~/.sprout/data/sprout_blobs",
    trajectory_dir: settings?.storage?.trajectory_dir || preferences.storage_config?.trajectory_dir || "~/.sprout/data/sprout_trajectory",
    project_root: settings?.storage?.project_root || preferences.storage_config?.project_root || "~/.sprout/data/projects",
    observations_enabled: settings?.storage?.observations?.enabled ?? preferences.storage_config?.observations_enabled ?? true,
    observations_dsn: settings?.storage?.observations?.dsn || preferences.storage_config?.observations_dsn || "~/.sprout/data/sprout_audit.db"
  }));
  const [mcpForm, setMcpForm] = useState(() => ({
    enabled: settings?.mcp?.server?.enabled ?? preferences.mcp_config?.enabled ?? true,
    transport: settings?.mcp?.server?.transport || preferences.mcp_config?.transport || "stdio"
  }));
  const [savingKey, setSavingKey] = useState("");
  const [tokenForm, setTokenForm] = useState(() => getApiToken());

  useEffect(() => {
    document.documentElement.dataset.theme = preferenceForm.theme;
    document.documentElement.lang = preferenceForm.language === "en" ? "en" : "zh-CN";
  }, [preferenceForm.theme, preferenceForm.language]);

  function updatePreference(key, value) {
    setPreferenceForm((current) => ({ ...current, [key]: value }));
  }

  function updateForm(setter, key, value) {
    setter((current) => ({ ...current, [key]: value }));
  }

  async function saveSection(key, payload) {
    setSavingKey(key);
    try {
      const data = await savePreferences({ [key]: payload });
      onSaved(data.preferences || { [key]: payload });
    } finally {
      setSavingKey("");
    }
  }

  function splitList(value) {
    return value.split(",").map((item) => item.trim()).filter(Boolean);
  }

  async function handlePreferencesSubmit(event) {
    event.preventDefault();
    await saveSection("preferences", {
      ...preferenceForm
    });
  }

  function handleTokenSubmit(event) {
    event.preventDefault();
    setApiToken(tokenForm.trim());
    // Every request already in flight was unauthenticated; reload to re-fetch.
    window.location.reload();
  }

  async function handleModelSubmit(event) {
    event.preventDefault();
    await saveSection("model_config", {
      ...modelForm,
      timeout_seconds: Number(modelForm.timeout_seconds || 60),
      temperature: modelForm.temperature === "" ? null : Number(modelForm.temperature)
    });
  }

  return (
    <div className="view">
      <div className="settings-grid">
        <section className="settings-card settings-card--wide">
          <h2>模型配置</h2>
          <form className="settings-form-grid" onSubmit={handleModelSubmit}>
            <Field label="模型网关">
              <select value={modelForm.gateway} onChange={(event) => updateForm(setModelForm, "gateway", event.target.value)}>
                <option value="aiyallm">Aiyallm Gateway</option>
                <option value="openai_compatible">OpenAI Compatible Gateway</option>
                <option value="echo">Offline Echo</option>
              </select>
            </Field>
            <Field label="模型名称">
              <input value={modelForm.model} onChange={(event) => updateForm(setModelForm, "model", event.target.value)} />
            </Field>
            <Field label="Base URL">
              <input value={modelForm.base_url} onChange={(event) => updateForm(setModelForm, "base_url", event.target.value)} />
            </Field>
            <Field label="API Key 环境变量">
              <input value={modelForm.api_key_env} onChange={(event) => updateForm(setModelForm, "api_key_env", event.target.value)} />
            </Field>
            <Field label="超时时间（秒）">
              <input type="number" min="1" value={modelForm.timeout_seconds} onChange={(event) => updateForm(setModelForm, "timeout_seconds", event.target.value)} />
            </Field>
            <Field label="Temperature">
              <input type="number" min="0" max="2" step="0.1" value={modelForm.temperature} placeholder="默认" onChange={(event) => updateForm(setModelForm, "temperature", event.target.value)} />
            </Field>
            <div className="settings-actions">
              <button className="btn primary" disabled={savingKey === "model_config"}>保存模型配置</button>
              <span className="settings-hint">保存后重启服务生效</span>
            </div>
          </form>
        </section>

        <section className="settings-card">
          <h2>运行时</h2>
          <form className="settings-form-grid" onSubmit={(event) => {
            event.preventDefault();
            saveSection("runtime_config", {
              ...runtimeForm,
              max_tool_steps: Number(runtimeForm.max_tool_steps),
              session_turn_limit: Number(runtimeForm.session_turn_limit)
            });
          }}>
            <Field label="默认 Agent">
              <input value={runtimeForm.default_agent} onChange={(event) => updateForm(setRuntimeForm, "default_agent", event.target.value)} />
            </Field>
            <Field label="最大工具步数">
              <input type="number" min="1" value={runtimeForm.max_tool_steps} onChange={(event) => updateForm(setRuntimeForm, "max_tool_steps", event.target.value)} />
            </Field>
            <Field label="会话轮数上限">
              <input type="number" min="1" value={runtimeForm.session_turn_limit} onChange={(event) => updateForm(setRuntimeForm, "session_turn_limit", event.target.value)} />
            </Field>
            <div className="settings-actions">
              <button className="btn primary" disabled={savingKey === "runtime_config"}>保存运行时</button>
            </div>
          </form>
        </section>

        <section className="settings-card">
          <h2>安全</h2>
          <form className="settings-form-grid" onSubmit={(event) => {
            event.preventDefault();
            saveSection("security_config", {
              allow_medium_risk: securityForm.allow_medium_risk,
              require_approval: securityForm.require_approval,
              organization_deny_prefixes: splitList(securityForm.organization_deny_prefixes),
              workspace_deny_prefixes: splitList(securityForm.workspace_deny_prefixes)
            });
          }}>
            <SwitchField label="允许中风险操作" checked={securityForm.allow_medium_risk} onChange={(value) => updateForm(setSecurityForm, "allow_medium_risk", value)} />
            <SwitchField label="需要人工审批" checked={securityForm.require_approval} onChange={(value) => updateForm(setSecurityForm, "require_approval", value)} />
            <Field label="组织拒绝前缀" className="full">
              <input value={securityForm.organization_deny_prefixes} onChange={(event) => updateForm(setSecurityForm, "organization_deny_prefixes", event.target.value)} />
            </Field>
            <Field label="工作区拒绝前缀" className="full">
              <input value={securityForm.workspace_deny_prefixes} onChange={(event) => updateForm(setSecurityForm, "workspace_deny_prefixes", event.target.value)} />
            </Field>
            <div className="settings-actions">
              <button className="btn primary" disabled={savingKey === "security_config"}>保存安全配置</button>
            </div>
          </form>
        </section>

        <section className="settings-card">
          <h2>Web 服务</h2>
          <form className="settings-form-grid" onSubmit={(event) => {
            event.preventDefault();
            saveSection("web_config", {
              ...webForm,
              port: Number(webForm.port)
            });
          }}>
            <Field label="Host">
              <input value={webForm.host} onChange={(event) => updateForm(setWebForm, "host", event.target.value)} />
            </Field>
            <Field label="Port">
              <input type="number" min="1" max="65535" value={webForm.port} onChange={(event) => updateForm(setWebForm, "port", event.target.value)} />
            </Field>
            <div className="settings-actions">
              <button className="btn primary" disabled={savingKey === "web_config"}>保存 Web 配置</button>
            </div>
          </form>
        </section>

        <section className="settings-card">
          <h2>成长平面</h2>
          <form className="settings-form-grid" onSubmit={(event) => {
            event.preventDefault();
            saveSection("evolution_config", {
              ...evolutionForm,
              level: Number(evolutionForm.level)
            });
          }}>
            <SwitchField label="启用 Evolution" checked={evolutionForm.enabled} onChange={(value) => updateForm(setEvolutionForm, "enabled", value)} />
            <SwitchField label="提案需要审批" checked={evolutionForm.approval_required} onChange={(value) => updateForm(setEvolutionForm, "approval_required", value)} />
            <Field label="Level">
              <input type="number" min="0" value={evolutionForm.level} onChange={(event) => updateForm(setEvolutionForm, "level", event.target.value)} />
            </Field>
            <Field label="Growth DSN">
              <input value={evolutionForm.growth_dsn} onChange={(event) => updateForm(setEvolutionForm, "growth_dsn", event.target.value)} />
            </Field>
            <div className="settings-actions">
              <button className="btn primary" disabled={savingKey === "evolution_config"}>保存成长平面</button>
            </div>
          </form>
        </section>

        <section className="settings-card settings-card--wide">
          <h2>存储</h2>
          <form className="settings-form-grid" onSubmit={(event) => {
            event.preventDefault();
            saveSection("storage_config", storageForm);
          }}>
            <Field label="Core DSN"><input value={storageForm.core} onChange={(event) => updateForm(setStorageForm, "core", event.target.value)} /></Field>
            <Field label="Conversation DSN"><input value={storageForm.conversation} onChange={(event) => updateForm(setStorageForm, "conversation", event.target.value)} /></Field>
            <Field label="Knowledge DSN"><input value={storageForm.knowledge} onChange={(event) => updateForm(setStorageForm, "knowledge", event.target.value)} /></Field>
            <Field label="Audit DSN"><input value={storageForm.audit} onChange={(event) => updateForm(setStorageForm, "audit", event.target.value)} /></Field>
            <Field label="Usage DSN"><input value={storageForm.usage} onChange={(event) => updateForm(setStorageForm, "usage", event.target.value)} /></Field>
            <Field label="Cache"><input value={storageForm.cache} onChange={(event) => updateForm(setStorageForm, "cache", event.target.value)} /></Field>
            <Field label="Blobs 目录"><input value={storageForm.blobs_dir} onChange={(event) => updateForm(setStorageForm, "blobs_dir", event.target.value)} /></Field>
            <Field label="轨迹目录"><input value={storageForm.trajectory_dir} onChange={(event) => updateForm(setStorageForm, "trajectory_dir", event.target.value)} /></Field>
            <Field label="项目层根目录"><input value={storageForm.project_root} onChange={(event) => updateForm(setStorageForm, "project_root", event.target.value)} /></Field>
            <SwitchField label="启用 Observations" checked={storageForm.observations_enabled} onChange={(value) => updateForm(setStorageForm, "observations_enabled", value)} />
            <Field label="Audit Events DSN"><input value={storageForm.observations_dsn} onChange={(event) => updateForm(setStorageForm, "observations_dsn", event.target.value)} /></Field>
            <div className="settings-actions">
              <button className="btn primary" disabled={savingKey === "storage_config"}>保存存储配置</button>
            </div>
          </form>
        </section>

        <section className="settings-card">
          <h2>MCP 服务</h2>
          <form className="settings-form-grid" onSubmit={(event) => {
            event.preventDefault();
            saveSection("mcp_config", mcpForm);
          }}>
            <SwitchField label="启用 MCP Server" checked={mcpForm.enabled} onChange={(value) => updateForm(setMcpForm, "enabled", value)} />
            <Field label="传输方式">
              <select value={mcpForm.transport} onChange={(event) => updateForm(setMcpForm, "transport", event.target.value)}>
                <option value="stdio">stdio</option>
                <option value="sse">sse</option>
              </select>
            </Field>
            <div className="settings-actions">
              <button className="btn primary" disabled={savingKey === "mcp_config"}>保存 MCP 配置</button>
            </div>
          </form>
        </section>

        <section className="settings-card">
          <h2>接口鉴权</h2>
          <form className="pref-form" onSubmit={handleTokenSubmit}>
            <Field label="API Token">
              <input
                type="password"
                value={tokenForm}
                placeholder="未设置"
                onChange={(event) => setTokenForm(event.target.value)}
              />
            </Field>
            <span className="settings-hint">
              仅保存在本机浏览器。服务端开启 [security] web_auth_enabled 后必填，否则所有接口返回 401。
            </span>
            <button className="btn primary">保存 Token</button>
          </form>
        </section>

        <section className="settings-card">
          <h2>控制台偏好</h2>
          <form className="pref-form" onSubmit={handlePreferencesSubmit}>
            <Field label="用户名称"><input value={preferenceForm.user_name} onChange={(event) => updatePreference("user_name", event.target.value)} /></Field>
            <Field label="主题">
              <select value={preferenceForm.theme} onChange={(event) => updatePreference("theme", event.target.value)}>
                <option value="light">浅色</option>
                <option value="dark">深色</option>
              </select>
            </Field>
            <Field label="语言 / Language">
              <select
                value={preferenceForm.language}
                onChange={(event) => updatePreference("language", event.target.value)}
              >
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </Field>
            <SwitchField label="完成任务时播放庆祝效果" checked={preferenceForm.fun_effects} onChange={(value) => updatePreference("fun_effects", value)} />
            <button className="btn primary" disabled={savingKey === "preferences"}>保存偏好</button>
          </form>
        </section>

        <section className="settings-card settings-card--wide">
          <h2>运行时配置</h2>
          <div>
            {Object.entries(settings || {}).map(([key, val]) => (
              <div className="config-row" key={key}>
                <div className="config-key">{labels[key] || key}</div>
                <div className="config-value">
                  {val && typeof val === "object" && !Array.isArray(val)
                    ? formatConfigValue(val)
                    : String(val)}
                </div>
              </div>
            ))}
            {configPath && (
              <div className="config-row">
                <div className="config-key">配置文件</div>
                <div className="config-value">{configPath}</div>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
