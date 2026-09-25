import { useEffect, useState } from "react";
import { Box, Database, HardDrive, Network, RefreshCw } from "lucide-react";
import {
  getGraphStatus,
  getStoragePlan,
  getStorageStatus,
  getStorageTopology,
  getVectorCount
} from "../api";

const laneNames = {
  sqlite: "SQLite",
  redis: "Redis",
  milvus: "Milvus",
  neo4j: "Neo4j"
};

function Metric({ icon: Icon, label, value, detail, tone = "purple", href }) {
  const content = (
    <>
      <div className="metric-label">
        <Icon size={15} />
        {label}
      </div>
      <div className={`metric-value ${tone}`}>{value || "-"}</div>
      {detail && <div className="metric-detail">{detail}</div>}
    </>
  );
  if (href) {
    return (
      <a className="metric metric-link" href={href} target="_blank" rel="noreferrer">
        {content}
      </a>
    );
  }
  return <div className="metric">{content}</div>;
}

function laneHttpUrl(dsn, defaultPort, mapPort) {
  if (!dsn || dsn === "none" || dsn === "memory" || dsn.startsWith("memory://")) {
    return null;
  }
  const withoutScheme = dsn.replace(/^[a-z0-9]+:\/\//i, "");
  const hostPart = withoutScheme.split("/")[0].split("@").pop() || "";
  const [host, rawPort] = hostPart.split(":");
  const port = mapPort ? mapPort(rawPort) : rawPort || String(defaultPort);
  return host ? `http://${host}:${port}` : null;
}

function milvusUrl(dsn) {
  return laneHttpUrl(dsn, 19530);
}

function neo4jUrl(dsn) {
  return laneHttpUrl(dsn, 7474, (rawPort) => {
    if (!rawPort || rawPort === "7687") return "7474";
    return rawPort;
  });
}

function findLane(plan, key) {
  return plan.find((entry) => entry.key === key);
}

function MetricLink({ icon, label, value, detail, tone, dsn, buildUrl }) {
  return (
    <Metric
      icon={icon}
      label={label}
      value={value}
      detail={detail}
      tone={tone}
      href={buildUrl(dsn)}
    />
  );
}

export default function StorageView() {
  const [status, setStatus] = useState({ storage: {}, lanes: {} });
  const [plan, setPlan] = useState([]);
  const [topology, setTopology] = useState({ entities: [], databases: [] });
  const [graph, setGraph] = useState(null);
  const [vectorCount, setVectorCount] = useState(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    const [statusResult, planResult, topologyResult, graphResult, vectorResult] =
      await Promise.allSettled([
        getStorageStatus(),
        getStoragePlan(),
        getStorageTopology(),
        getGraphStatus(),
        getVectorCount()
      ]);
    setStatus(
      statusResult.status === "fulfilled" ? statusResult.value : { storage: {}, lanes: {} }
    );
    setPlan(planResult.status === "fulfilled" ? planResult.value.lanes || [] : []);
    setTopology(
      topologyResult.status === "fulfilled"
        ? topologyResult.value
        : { entities: [], databases: [] }
    );
    setGraph(graphResult.status === "fulfilled" ? graphResult.value : null);
    setVectorCount(
      vectorResult.status === "fulfilled" ? vectorResult.value.count : null
    );
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  const lanes = status.lanes || {};
  const storage = status.storage || {};
  const milvus = findLane(plan, "milvus");
  const neo4j = findLane(plan, "neo4j");

  return (
    <div className="view">
      <div className="storage-toolbar">
        <button className="btn" onClick={load} disabled={loading}>
          <RefreshCw size={16} />
          刷新
        </button>
      </div>

      <div className="metric-row">
        <Metric
          icon={HardDrive}
          label="SQLite"
          value={`${storage.conversation?.sessions || 0} / ${storage.conversation?.turns || 0}`}
          detail="sessions / turns"
          tone="purple"
        />
        <Metric
          icon={Database}
          label="Redis"
          value={lanes.cache || "-"}
          detail="cache lane"
          tone="amber"
        />
        <MetricLink
          icon={Box}
          label="Milvus"
          value={vectorCount ?? "-"}
          detail={lanes.vectors || "vectors"}
          tone="teal"
          dsn={milvus?.dsn}
          buildUrl={milvusUrl}
        />
        <MetricLink
          icon={Network}
          label="Neo4j"
          value={graph ? `${graph.sessions} / ${graph.turns}` : "-"}
          detail={lanes.graph || "graph"}
          tone="rose"
          dsn={neo4j?.dsn}
          buildUrl={neo4jUrl}
        />
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Lane</th>
              <th>类型</th>
              <th>Authority</th>
              <th>Backend</th>
              <th>DSN</th>
            </tr>
          </thead>
          <tbody>
            {plan.length === 0 ? (
              <tr>
                <td colSpan="5">暂无数据层计划</td>
              </tr>
            ) : (
              plan.map((entry) => (
                <tr key={entry.key}>
                  <td>
                    <span className="lane-name">
                      {laneNames[entry.key] || entry.key}
                    </span>
                  </td>
                  <td>{entry.scheme}</td>
                  <td>{entry.authority ? "是" : "否"}</td>
                  <td>{entry.backend}</td>
                  <td><span className="config-value">{entry.dsn || "-"}</span></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Entity</th>
              <th>Authority</th>
              <th>Derived Lanes</th>
              <th>Payload</th>
            </tr>
          </thead>
          <tbody>
            {(topology.entities || []).map((entity) => (
              <tr key={entity.entity}>
                <td>{entity.entity}</td>
                <td>{entity.authority}</td>
                <td>{(entity.derived || []).join(", ") || "-"}</td>
                <td>{entity.payload_lane || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
