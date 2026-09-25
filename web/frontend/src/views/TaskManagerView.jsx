import { useMemo, useState } from "react";
import {
  CalendarDays,
  Pencil,
  Trash2,
  UserRound
} from "lucide-react";

const statusLabels = { todo: "待开始", doing: "进行中", done: "已完成" };
const priorityLabels = { low: "低", medium: "中", high: "高" };

function dueText(value) {
  if (!value) return "-";
  const date = new Date(`${value}T23:59:59`);
  if (Number.isNaN(date.getTime())) return value;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  const diff = Math.round((target - today) / 86400000);
  if (diff < 0) return `${value} · 已逾期`;
  if (diff === 0) return `${value} · 今天`;
  if (diff === 1) return `${value} · 明天`;
  return value;
}

function sortTasks(tasks, sort) {
  const items = [...tasks];
  if (sort === "due") {
    return items.sort((a, b) => String(a.due_at || "").localeCompare(String(b.due_at || "")));
  }
  if (sort === "priority") {
    const weight = { high: 0, medium: 1, low: 2 };
    return items.sort(
      (a, b) => (weight[a.priority] ?? 9) - (weight[b.priority] ?? 9)
    );
  }
  return items;
}

export default function TaskManagerView({ tasks, onEdit, onDelete }) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [assignee, setAssignee] = useState("");
  const [sort, setSort] = useState("newest");

  const assignees = useMemo(
    () => [...new Set(tasks.map((task) => task.assignee).filter(Boolean))],
    [tasks]
  );

  const visibleTasks = useMemo(() => {
    const query = search.trim().toLowerCase();
    return sortTasks(
      tasks.filter((task) => {
        if (status && task.status !== status) return false;
        if (priority && task.priority !== priority) return false;
        if (assignee && task.assignee !== assignee) return false;
        if (query) {
          const haystack = `${task.title} ${task.description} ${task.tags.join(" ")}`.toLowerCase();
          if (!haystack.includes(query)) return false;
        }
        return true;
      }),
      sort
    );
  }, [tasks, search, status, priority, assignee, sort]);

  const metrics = {
    todo: tasks.filter((task) => task.status === "todo").length,
    doing: tasks.filter((task) => task.status === "doing").length,
    done: tasks.filter((task) => task.status === "done").length
  };

  return (
    <div className="view">
      <div className="metric-row task-manager-summary">
        <div className="metric">
          <div className="metric-label">全部任务</div>
          <div className="metric-value purple">{tasks.length}</div>
        </div>
        <div className="metric">
          <div className="metric-label">进行中</div>
          <div className="metric-value amber">{metrics.doing}</div>
        </div>
        <div className="metric">
          <div className="metric-label">已完成</div>
          <div className="metric-value teal">{metrics.done}</div>
        </div>
      </div>

      <div className="task-manager-toolbar">
        <input
          type="search"
          placeholder="搜索标题、描述或标签"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">全部状态</option>
          <option value="todo">待开始</option>
          <option value="doing">进行中</option>
          <option value="done">已完成</option>
        </select>
        <select value={priority} onChange={(event) => setPriority(event.target.value)}>
          <option value="">全部优先级</option>
          <option value="high">高</option>
          <option value="medium">中</option>
          <option value="low">低</option>
        </select>
        <select value={assignee} onChange={(event) => setAssignee(event.target.value)}>
          <option value="">全部负责人</option>
          {assignees.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        <select value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="newest">默认排序</option>
          <option value="due">按截止日期</option>
          <option value="priority">按优先级</option>
        </select>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>任务</th>
              <th>状态</th>
              <th>优先级</th>
              <th>负责人</th>
              <th>截止</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {visibleTasks.length === 0 ? (
              <tr>
                <td colSpan="6">
                  <div className="empty-state">没有匹配的任务</div>
                </td>
              </tr>
            ) : (
              visibleTasks.map((task) => (
                <tr key={task.id}>
                  <td>
                    <div className="task-manager-title">
                      <strong>{task.title}</strong>
                      {(task.tags || []).slice(0, 3).map((tag) => (
                        <span className="tag" key={tag}>{tag}</span>
                      ))}
                    </div>
                    {task.description && <div className="task-desc">{task.description}</div>}
                  </td>
                  <td>
                    <span className={`status-pill ${task.status}`}>
                      {statusLabels[task.status]}
                    </span>
                  </td>
                  <td>
                    <span className={`tag ${task.priority}`}>
                      {priorityLabels[task.priority] || task.priority}
                    </span>
                  </td>
                  <td>
                    {task.assignee ? (
                      <span className="assignee-cell">
                        <UserRound size={14} />
                        {task.assignee}
                      </span>
                    ) : "-"}
                  </td>
                  <td>
                    <span className="due-cell">
                      <CalendarDays size={14} />
                      {dueText(task.due_at)}
                    </span>
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button className="icon-btn" onClick={() => onEdit(task)}>
                      <Pencil size={15} />
                    </button>
                    <button className="icon-btn danger" onClick={() => onDelete(task)}>
                      <Trash2 size={15} />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
