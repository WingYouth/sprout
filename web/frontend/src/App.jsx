import { useEffect, useState } from "react";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";
import TaskModal from "./components/TaskModal";
import BoardView from "./views/BoardView";
import ChatView from "./views/ChatView";
import LogsView from "./views/LogsView";
import SettingsView from "./views/SettingsView";
import StorageView from "./views/StorageView";
import TaskManagerView from "./views/TaskManagerView";
import TokenView from "./views/TokenView";
import ProjectView from "./views/ProjectView";
import ApprovalsView from "./views/ApprovalsView";
import {
  createTask,
  deleteTask,
  getHealth,
  getSettings,
  getTasks,
  updateTask
} from "./api";

export default function App() {
  const [activeView, setActiveView] = useState("chat");
  const [health, setHealth] = useState(false);
  const [version, setVersion] = useState("");
  const [tasks, setTasks] = useState([]);
  const [settings, setSettings] = useState(null);
  const [preferences, setPreferences] = useState({});
  const [configPath, setConfigPath] = useState(null);
  const [chatSession, setChatSession] = useState(null);
  const [editingTask, setEditingTask] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    let mounted = true;
    Promise.allSettled([getHealth(), getTasks(), getSettings()]).then((results) => {
      if (!mounted) return;
      const [healthResult, taskResult, settingsResult] = results;
      if (healthResult.status === "fulfilled") {
        setHealth(true);
        setVersion(healthResult.value.version);
      }
      if (taskResult.status === "fulfilled") {
        setTasks(taskResult.value.tasks);
      }
      if (settingsResult.status === "fulfilled") {
        const data = settingsResult.value;
        setSettings(data.settings);
        setPreferences(data.preferences || {});
        setConfigPath(data.config_path);
        document.documentElement.dataset.theme =
          data.preferences?.theme === "dark" ? "dark" : "light";
        document.documentElement.lang =
          data.preferences?.language === "en" ? "en" : "zh-CN";
      }
    });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 2200);
    return () => clearTimeout(timer);
  }, [toast]);

  async function handleCreate(task) {
    try {
      const created = await createTask(task);
      setTasks((current) => [created, ...current]);
      setModalOpen(false);
      setEditingTask(null);
      setToast("任务已保存");
    } catch (error) {
      setToast(error.message);
    }
  }

  async function handleUpdate(task) {
    try {
      const updated = await updateTask(task.id, task);
      setTasks((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      );
      setModalOpen(false);
      setEditingTask(null);
      setToast("任务已保存");
    } catch (error) {
      setToast(error.message);
    }
  }

  async function handleMove(taskId, status) {
    const task = tasks.find((item) => item.id === taskId);
    if (!task || task.status === status) return;
    try {
      const updated = await updateTask(taskId, { status });
      setTasks((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      );
    } catch (error) {
      setToast(error.message);
    }
  }

  async function handleDelete(task) {
    if (!window.confirm(`删除任务“${task.title}”？`)) return;
    try {
      await deleteTask(task.id);
      setTasks((current) => current.filter((item) => item.id !== task.id));
      setToast("任务已删除");
    } catch (error) {
      setToast(error.message);
    }
  }

  function openNewTask() {
    setEditingTask(null);
    setModalOpen(true);
  }

  function openEditTask(task) {
    setEditingTask(task);
    setModalOpen(true);
  }

  function saveTask(task) {
    return editingTask ? handleUpdate(task) : handleCreate(task);
  }

  function handlePreferencesSaved(nextPreferences) {
    setPreferences(nextPreferences);
    document.documentElement.dataset.theme =
      nextPreferences.theme === "dark" ? "dark" : "light";
    setToast("偏好已保存");
  }

  return (
    <div className="app-shell">
      <Sidebar
        activeView={activeView}
        onViewChange={setActiveView}
        health={health}
        version={version}
      />
      <section className="workspace">
        <TopBar activeView={activeView} onNewTask={openNewTask} />
        {activeView === "board" && (
          <BoardView
            tasks={tasks}
            preferences={preferences}
            onMove={handleMove}
            onEdit={openEditTask}
            onDelete={handleDelete}
          />
        )}
        {activeView === "tasks" && (
          <TaskManagerView
            tasks={tasks}
            onEdit={openEditTask}
            onDelete={handleDelete}
          />
        )}
        {activeView === "tokens" && <TokenView />}
        {activeView === "project" && <ProjectView onToast={setToast} />}
        {activeView === "approvals" && <ApprovalsView onToast={setToast} />}
        {activeView === "storage" && <StorageView />}
        {activeView === "logs" && <LogsView />}
        {activeView === "chat" && (
          <ChatView
            sessionId={chatSession}
            userName={preferences.user_name}
            onSessionChange={setChatSession}
          />
        )}
        {activeView === "settings" && (
          <SettingsView
            settings={settings}
            preferences={preferences}
            configPath={configPath}
            onSaved={handlePreferencesSaved}
          />
        )}
      </section>
      {modalOpen && (
        <TaskModal
          task={editingTask}
          onClose={() => {
            setModalOpen(false);
            setEditingTask(null);
          }}
          onSubmit={saveTask}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
