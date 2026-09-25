import { useEffect, useState } from "react";
import { FolderOpen, Play, Plus, RefreshCw, Search, ShieldCheck } from "lucide-react";
import {
  analyzeProjectWorkspace,
  createProjectTask,
  decideProposal,
  getProjectTasks,
  getProjectWorkspaces,
  getTaskChanges,
  openProjectWorkspace,
  runProjectTask
} from "../api";

const statusLabels = {
  created: "已创建",
  planning: "规划中",
  ready: "待执行",
  running: "执行中",
  waiting_approval: "等待审批",
  ready_to_apply: "待应用",
  completed: "已完成",
  failed: "失败"
};

export default function ProjectView({ onToast }) {
  const [workspaces, setWorkspaces] = useState([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [tasks, setTasks] = useState([]);
  const [path, setPath] = useState("");
  const [instruction, setInstruction] = useState("");
  const [selected, setSelected] = useState(null);
  const [changes, setChanges] = useState([]);
  const [loading, setLoading] = useState(false);

  async function loadWorkspaces() {
    const data = await getProjectWorkspaces();
    setWorkspaces(data);
    if (!workspaceId && data[0]) setWorkspaceId(data[0].id);
  }

  async function loadTasks(id = workspaceId) {
    const data = await getProjectTasks(id);
    setTasks(data.tasks || []);
  }

  useEffect(() => {
    loadWorkspaces().catch((error) => onToast(error.message));
  }, []);

  useEffect(() => {
    if (workspaceId) loadTasks().catch((error) => onToast(error.message));
  }, [workspaceId]);

  async function openWorkspace(event) {
    event.preventDefault();
    if (!path.trim()) return;
    try {
      const workspace = await openProjectWorkspace(path.trim());
      setWorkspaces((current) => [
        ...current.filter((item) => item.id !== workspace.id),
        workspace
      ]);
      setWorkspaceId(workspace.id);
      setPath("");
      onToast("工作区已连接");
    } catch (error) {
      onToast(error.message);
    }
  }

  async function analyze() {
    if (!workspaceId) return;
    setLoading(true);
    try {
      const result = await analyzeProjectWorkspace(workspaceId);
      onToast(`扫描完成：${result.nodes} 个节点，${result.edges} 条关系`);
    } catch (error) {
      onToast(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function createTask(event) {
    event.preventDefault();
    if (!workspaceId || !instruction.trim()) return;
    try {
      await createProjectTask(workspaceId, instruction.trim());
      setInstruction("");
      await loadTasks();
      onToast("战略任务已创建");
    } catch (error) {
      onToast(error.message);
    }
  }

  async function runTask(task) {
    try {
      await runProjectTask(task.id);
      await loadTasks();
      onToast("任务已提交执行");
    } catch (error) {
      onToast(error.message);
    }
  }

  async function inspectTask(task) {
    setSelected(task);
    try {
      setChanges(await getTaskChanges(task.id));
    } catch (error) {
      onToast(error.message);
    }
  }

  async function proposalAction(proposalId, action) {
    try {
      await decideProposal(proposalId, action);
      await inspectTask(selected);
      await loadTasks();
      onToast(action === "approve" ? "提案已批准" : action === "apply" ? "提案已应用" : "提案已拒绝");
    } catch (error) {
      onToast(error.message);
    }
  }

  return (
    <div className="view">
      <div className="project-toolbar">
        <form className="inline-form" onSubmit={openWorkspace}>
          <FolderOpen size={16} />
          <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="项目路径，例如 /Users/jason/SEAM_Sprout" />
          <button className="btn" type="submit">连接工作区</button>
        </form>
        <button className="btn" onClick={() => loadWorkspaces()}><RefreshCw size={15} />刷新</button>
      </div>

      <div className="project-grid">
        <section className="settings-card">
          <div className="section-heading"><h2>项目工作区</h2><Search size={17} /></div>
          <select className="project-select" value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)}>
            <option value="">选择工作区</option>
            {workspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.root}</option>)}
          </select>
          <button className="btn primary" disabled={!workspaceId || loading} onClick={analyze}><Search size={15} />扫描并分析</button>
          <div className="project-list">
            {workspaces.map((workspace) => <button key={workspace.id} className={`project-row ${workspace.id === workspaceId ? "selected" : ""}`} onClick={() => setWorkspaceId(workspace.id)}>{workspace.root}</button>)}
          </div>
        </section>

        <section className="settings-card settings-card--wide">
          <div className="section-heading"><h2>需求战略任务</h2><span className="muted-label">Runtime metadata</span></div>
          <form className="project-task-form" onSubmit={createTask}>
            <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="输入自然语言需求，例如：增加代码撰写能力" rows="3" />
            <button className="btn primary" disabled={!workspaceId || !instruction.trim()}><Plus size={15} />制定战略</button>
          </form>
          <div className="project-task-list">
            {tasks.length === 0 && <div className="empty-state">暂无 Runtime 任务</div>}
            {tasks.map((task) => (
              <div className={`project-task ${selected?.id === task.id ? "selected" : ""}`} key={task.id}>
                <button className="project-task-main" onClick={() => inspectTask(task)}>
                  <strong>{task.instruction}</strong>
                  <span>{statusLabels[task.status] || task.status} · {new Date(task.created_at).toLocaleString()}</span>
                </button>
                <button className="icon-btn" title="执行任务" onClick={() => runTask(task)}><Play size={15} /></button>
              </div>
            ))}
          </div>
        </section>
      </div>

      {selected && <section className="settings-card proposal-panel">
        <div className="section-heading"><h2>任务变更提案</h2><ShieldCheck size={17} /></div>
        {changes.length === 0 ? <div className="empty-state">暂无变更提案，任务可能仍在分析或执行中。</div> : changes.map((change) => (
          <div className="proposal-row" key={change.id}>
            <span><strong>{change.id.slice(0, 8)}</strong> · {change.status} · {change.risk}</span>
            <span className="proposal-actions">
              {(change.files_changed || []).join(", ") || "尚未记录文件"}
              {change.status === "pending" && <button className="btn" onClick={() => proposalAction(change.id, "approve")}>批准</button>}
              {change.status === "approved" && <button className="btn primary" onClick={() => proposalAction(change.id, "apply")}>应用</button>}
            </span>
          </div>
        ))}
      </section>}
    </div>
  );
}
