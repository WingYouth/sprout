import { Pencil, Trash2 } from "lucide-react";

const priorityLabels = { low: "低", medium: "中", high: "高" };

export default function TaskCard({ task, onEdit, onDelete, onDragStart, onDragEnd }) {
  return (
    <article
      className="task-card"
      draggable
      data-task-id={task.id}
      onDragStart={(event) => {
        event.dataTransfer.setData("text/plain", task.id);
        onDragStart(task.id);
      }}
      onDragEnd={onDragEnd}
    >
      <div className="task-title">{task.title}</div>
      {task.description && <div className="task-desc">{task.description}</div>}
      <div className="tag-row">
        <span className={`tag ${task.priority}`}>{priorityLabels[task.priority] || task.priority}</span>
        {(task.tags || []).slice(0, 3).map((tag) => (
          <span className="tag" key={tag}>{tag}</span>
        ))}
      </div>
      <div className="card-foot">
        {task.assignee && <span>{task.assignee}</span>}
        <span className="spacer" />
        <button className="icon-btn" onClick={() => onEdit(task)}>
          <Pencil size={15} />
        </button>
        <button className="icon-btn danger" onClick={() => onDelete(task)}>
          <Trash2 size={15} />
        </button>
      </div>
    </article>
  );
}
