import { useState } from "react";
import { X } from "lucide-react";

export default function TaskModal({ task, onClose, onSubmit }) {
  const [form, setForm] = useState(() => ({
    title: task?.title || "",
    description: task?.description || "",
    status: task?.status || "todo",
    priority: task?.priority || "medium",
    assignee: task?.assignee || "",
    due_at: task?.due_at || "",
    tags: (task?.tags || []).join(", ")
  }));

  function update(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event) {
    event.preventDefault();
    onSubmit({
      ...form,
      title: form.title.trim(),
      description: form.description.trim(),
      assignee: form.assignee.trim() || null,
      due_at: form.due_at || null,
      tags: form.tags.split(",").map((tag) => tag.trim()).filter(Boolean)
    });
  }

  return (
    <div className="modal-backdrop" onClick={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div className="modal">
        <div className="modal-head">
          <h2>{task ? "编辑任务" : "新建任务"}</h2>
          <button className="icon-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <form className="form-grid" onSubmit={handleSubmit}>
          <div className="field full">
            <label>标题</label>
            <input
              autoFocus
              required
              maxLength="140"
              value={form.title}
              onChange={(event) => update("title", event.target.value)}
            />
          </div>
          <div className="field full">
            <label>描述</label>
            <textarea
              rows="3"
              value={form.description}
              onChange={(event) => update("description", event.target.value)}
            />
          </div>
          <div className="field">
            <label>状态</label>
            <select value={form.status} onChange={(event) => update("status", event.target.value)}>
              <option value="todo">待开始</option>
              <option value="doing">进行中</option>
              <option value="done">已完成</option>
            </select>
          </div>
          <div className="field">
            <label>优先级</label>
            <select value={form.priority} onChange={(event) => update("priority", event.target.value)}>
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
          </div>
          <div className="field">
            <label>负责人</label>
            <input
              value={form.assignee}
              placeholder="可选"
              onChange={(event) => update("assignee", event.target.value)}
            />
          </div>
          <div className="field">
            <label>截止日期</label>
            <input
              type="date"
              value={form.due_at}
              onChange={(event) => update("due_at", event.target.value)}
            />
          </div>
          <div className="field">
            <label>标签</label>
            <input
              value={form.tags}
              placeholder="逗号分隔"
              onChange={(event) => update("tags", event.target.value)}
            />
          </div>
          <div className="modal-actions full">
            <button className="btn" type="button" onClick={onClose}>取消</button>
            <button className="btn primary" type="submit">保存</button>
          </div>
        </form>
      </div>
    </div>
  );
}
