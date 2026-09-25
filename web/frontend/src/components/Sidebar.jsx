import {
  Coins,
  Database,
  FileText,
  ListTodo,
  MessageCircle,
  FolderKanban,
  ShieldCheck,
  SlidersHorizontal,
  Trello
} from "lucide-react";

const items = [
  { id: "chat", label: "聊天", icon: MessageCircle },
  { id: "board", label: "任务看板", icon: Trello },
  { id: "tasks", label: "任务管理", icon: ListTodo },
  { id: "project", label: "项目战略", icon: FolderKanban },
  { id: "approvals", label: "审批中心", icon: ShieldCheck },
  { id: "tokens", label: "Token 管理", icon: Coins },
  { id: "storage", label: "存储", icon: Database },
  { id: "logs", label: "日志", icon: FileText },
  { id: "settings", label: "配置设置", icon: SlidersHorizontal }
];

export default function Sidebar({ activeView, onViewChange, health, version }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <img src="/seam_sprout.svg" alt="SEAM Sprout logo" />
        </div>
        <div>
          <div className="brand-name">SEAM Sprout</div>
          <div className="brand-sub">Runtime Console</div>
        </div>
      </div>
      <nav className="nav">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={`nav-item ${activeView === item.id ? "active" : ""}`}
              onClick={() => onViewChange(item.id)}
            >
              <Icon size={18} />
              <span className="nav-label">{item.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="sidebar-foot">
        <div>
          <span className={`health-dot ${health ? "online" : ""}`} />
          <span>{health ? "online" : "checking..."}</span>
        </div>
        <div>{version ? `v${version}` : "SEAM Sprout runtime"}</div>
      </div>
    </aside>
  );
}
