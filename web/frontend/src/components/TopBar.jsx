import { Plus } from "lucide-react";

const titles = {
  board: ["任务看板", "拖动卡片改变状态"],
  tasks: ["任务管理", "搜索、筛选与编辑全部任务"],
  project: ["项目战略", "连接工作区，分析需求并运行 Runtime 任务"],
  approvals: ["审批中心", "处理 Runtime 与工具执行的人工授权"],
  tokens: ["Token 管理", "查看模型调用与 Token 消耗"],
  storage: ["存储", "查看 SQLite、Redis、Milvus 与 Neo4j 状态"],
  logs: ["日志", "查看 Web 请求日志"],
  chat: ["聊天", "与 Sprout Runtime 对话"],
  settings: ["配置设置", "查看运行时配置并调整控制台偏好"]
};

export default function TopBar({ activeView, onNewTask }) {
  const [title, subtitle] = titles[activeView];
  const showNewTask = activeView === "board" || activeView === "tasks";

  return (
    <header className="topbar">
      <div>
        <h1>{title}</h1>
        <p className="subtitle">{subtitle}</p>
      </div>
      <div className="topbar-actions">
        {showNewTask && (
          <button className="btn primary" onClick={onNewTask}>
            <Plus size={16} />
            新建任务
          </button>
        )}
      </div>
    </header>
  );
}
