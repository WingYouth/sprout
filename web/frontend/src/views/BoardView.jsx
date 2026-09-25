import { useState } from "react";
import TaskCard from "../components/TaskCard";
import Confetti from "../components/Confetti";

const statuses = [
  { id: "todo", label: "待开始" },
  { id: "doing", label: "进行中" },
  { id: "done", label: "已完成" }
];

export default function BoardView({ tasks, preferences, onMove, onEdit, onDelete }) {
  const [draggingId, setDraggingId] = useState(null);
  const [burstKey, setBurstKey] = useState(0);

  const counts = statuses.reduce((result, status) => {
    result[status.id] = tasks.filter((task) => task.status === status.id).length;
    return result;
  }, {});
  async function handleDrop(status, taskId) {
    if (!taskId) return;
    const task = tasks.find((item) => item.id === taskId);
    if (!task || task.status === status) return;
    await onMove(taskId, status);
    if (status === "done" && preferences.fun_effects !== false) {
      setBurstKey((key) => key + 1);
    }
  }

  return (
    <div className="view">
      <div className="metric-row">
        <div className="metric">
          <div className="metric-label">待开始</div>
          <div className="metric-value purple">{counts.todo}</div>
        </div>
        <div className="metric">
          <div className="metric-label">进行中</div>
          <div className="metric-value amber">{counts.doing}</div>
        </div>
        <div className="metric">
          <div className="metric-label">已完成</div>
          <div className="metric-value teal">{counts.done}</div>
        </div>
      </div>
      <div className="board-grid">
        {statuses.map((status) => (
          <section
            key={status.id}
            className="board-col"
            data-status={status.id}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              handleDrop(status.id, event.dataTransfer.getData("text/plain"));
            }}
          >
            <div className="col-head">
              {status.label}
              <span className="col-count">{counts[status.id]}</span>
            </div>
            <div className="task-stack">
              {tasks.filter((task) => task.status === status.id).length === 0 && (
                <div className="empty-state">暂无任务</div>
              )}
              {tasks
                .filter((task) => task.status === status.id)
                .map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    onEdit={onEdit}
                    onDelete={onDelete}
                    onDragStart={setDraggingId}
                    onDragEnd={() => setDraggingId(null)}
                  />
                ))}
            </div>
          </section>
        ))}
      </div>
      <Confetti burstKey={burstKey} />
    </div>
  );
}
