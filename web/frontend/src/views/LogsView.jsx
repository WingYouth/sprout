import { useEffect, useState } from "react";
import { FileText, RefreshCw } from "lucide-react";
import { getLogs } from "../api";

function statusClass(status) {
  if (status === "ok" || status === "done" || status === "todo") return "log-status-ok";
  if (status === "doing") return "log-status-warn";
  if (Number(status) >= 500) return "log-status-error";
  if (Number(status) >= 400) return "log-status-error";
  if (Number(status) >= 300) return "log-status-warn";
  return "log-status-ok";
}

export default function LogsView() {
  const [data, setData] = useState({ count: 0, records: [], categories: [] });
  const [loading, setLoading] = useState(true);
  const [categoryFilter, setCategoryFilter] = useState("all");

  async function load() {
    setLoading(true);
    try {
      setData(await getLogs());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const filtered = data.records.filter((record) => {
    return categoryFilter === "all" || record.category === categoryFilter;
  });

  return (
    <div className="view">
      <div className="storage-toolbar">
        <button className="btn" onClick={load} disabled={loading}>
          <RefreshCw size={16} />
          刷新
        </button>
        <div className="log-filter-group">
          <button
            className={`btn ${categoryFilter === "all" ? "primary" : ""}`}
            onClick={() => setCategoryFilter("all")}
          >
            全部
          </button>
          {(data.categories || []).map((category) => (
            <button
              key={category.key}
              className={`btn ${categoryFilter === category.key ? "primary" : ""}`}
              onClick={() => setCategoryFilter(category.key)}
            >
              {category.label} {category.count}
            </button>
          ))}
        </div>
      </div>
      <div className="metric-row">
        <div className="metric">
          <div className="metric-label">
            <FileText size={15} />
            请求日志
          </div>
          <div className="metric-value purple">{data.count || 0}</div>
          <div className="metric-detail">webapi.db / web_requests</div>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>分类</th>
              <th>摘要</th>
              <th>状态</th>
              <th>详情</th>
              <th>Session</th>
              <th>User</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan="7">暂无请求日志</td>
              </tr>
            ) : (
              filtered.map((record) => (
                <tr key={record.id}>
                  <td>{new Date(record.ts).toLocaleString()}</td>
                  <td>{record.category || "-"}</td>
                  <td><span className="config-value">{record.summary || "-"}</span></td>
                  <td>
                    <span className={`log-status ${statusClass(record.status)}`}>
                      {record.status ?? "-"}
                    </span>
                  </td>
                  <td>{record.detail || "-"}</td>
                  <td>{record.session_id || "-"}</td>
                  <td>{record.user_id || "-"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
