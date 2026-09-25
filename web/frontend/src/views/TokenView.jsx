import { useEffect, useState } from "react";
import { Coins, RefreshCw } from "lucide-react";
import { getTokens } from "../api";

export default function TokenView() {
  const [data, setData] = useState({ summary: {}, records: [] });
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      setData(await getTokens());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const summary = data.summary || {};
  const records = data.records || [];

  return (
    <div className="view">
      <div className="token-toolbar">
        <button className="btn" onClick={load} disabled={loading}>
          <RefreshCw size={16} />
          刷新
        </button>
      </div>
      <div className="metric-row">
        <div className="metric">
          <div className="metric-label">请求数</div>
          <div className="metric-value purple">{summary.requests || 0}</div>
        </div>
        <div className="metric">
          <div className="metric-label">输入 Tokens</div>
          <div className="metric-value amber">{summary.input_tokens || 0}</div>
        </div>
        <div className="metric">
          <div className="metric-label">输出 Tokens</div>
          <div className="metric-value teal">{summary.output_tokens || 0}</div>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>Provider</th>
              <th>Model</th>
              <th>输入</th>
              <th>输出</th>
              <th>总计</th>
              <th>Request ID</th>
            </tr>
          </thead>
          <tbody>
            {records.length === 0 ? (
              <tr>
                <td colSpan="7">
                  <div className="empty-state">
                    <Coins size={18} />
                    暂无 token 使用记录
                  </div>
                </td>
              </tr>
            ) : (
              records.map((record) => (
                <tr key={record.id}>
                  <td>{new Date(record.ts).toLocaleString()}</td>
                  <td>{record.provider || "-"}</td>
                  <td>{record.model || "-"}</td>
                  <td>{record.input_tokens || 0}</td>
                  <td>{record.output_tokens || 0}</td>
                  <td>{record.total_tokens || 0}</td>
                  <td><span className="request-id">{record.request_id || "-"}</span></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
