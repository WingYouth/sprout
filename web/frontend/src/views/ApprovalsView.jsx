import { useEffect, useState } from "react";
import { Check, RefreshCw, ShieldAlert, X } from "lucide-react";
import { decideApproval, getApprovals } from "../api";

function approvalContent(record) {
  return record.action_summary || record.approval_class || record.tool || "-";
}

export default function ApprovalsView({ onToast }) {
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const data = await getApprovals();
      setApprovals(data.approvals || []);
    } catch (error) {
      onToast(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function decide(record, approve) {
    try {
      await decideApproval(record.id, approve);
      await load();
      onToast(approve ? "审批已通过" : "审批已拒绝");
    } catch (error) {
      onToast(error.message);
    }
  }

  return (
    <div className="view">
      <div className="storage-toolbar">
        <button className="btn" onClick={load} disabled={loading}><RefreshCw size={15} />刷新</button>
      </div>
      <div className="metric-row">
        <div className="metric"><div className="metric-label"><ShieldAlert size={15} />待处理审批</div><div className="metric-value amber">{approvals.filter((item) => item.status === "pending").length}</div></div>
        <div className="metric"><div className="metric-label">审批总数</div><div className="metric-value purple">{approvals.length}</div></div>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>工具</th><th>审批内容</th><th>审批类别</th><th>会话</th><th>资源范围</th><th>来源</th><th>状态</th><th>创建时间</th><th /></tr></thead>
          <tbody>
            {approvals.length === 0 ? <tr><td colSpan="9"><div className="empty-state">暂无审批记录</div></td></tr> : approvals.map((record) => (
              <tr key={record.id}>
                <td>{record.tool}</td>
                <td><div className="approval-content-block">{approvalContent(record)}</div></td>
                <td className="config-value">{record.approval_class || "-"}</td>
                <td className="config-value">{record.session_id || "-"}</td>
                <td className="config-value">{record.resource_scope || "-"}</td>
                <td>{record.source || "-"}</td>
                <td><span className={`log-status ${record.status === "pending" ? "log-status-warn" : "log-status-ok"}`}>{record.status}</span></td>
                <td>{new Date(record.created_at).toLocaleString()}</td>
                <td style={{ whiteSpace: "nowrap" }}>{record.status === "pending" && <><button className="icon-btn" title="批准" onClick={() => decide(record, true)}><Check size={15} /></button><button className="icon-btn danger" title="拒绝" onClick={() => decide(record, false)}><X size={15} /></button></>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
