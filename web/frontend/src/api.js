const TOKEN_KEY = "sprout_api_token";

// The API token lives in localStorage, never in the served bundle: with
// `[security] web_auth_enabled = true` every /api route needs
// `Authorization: Bearer <token>`, and the browser has to hold it somewhere.
export function getApiToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setApiToken(token) {
  try {
    if (token) {
      window.localStorage.setItem(TOKEN_KEY, token);
    } else {
      window.localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // Storage can be unavailable (private mode); the request then goes out
    // unauthenticated and the server answers 401, which is the honest outcome.
  }
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) {
    headers["Content-Type"] = "application/json";
  }
  const token = getApiToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    throw new Error(data.error || "接口需要 API token，请在“控制台偏好”中填写");
  }
  if (!response.ok) {
    throw new Error(data.error || "request failed");
  }
  return data;
}

export function getHealth() {
  return request("/api/health");
}

export function getTasks() {
  return request("/api/tasks");
}

export function getProjectWorkspaces() {
  return request("/api/project/workspaces");
}

export function openProjectWorkspace(path) {
  return request("/api/project/workspaces", {
    method: "POST",
    body: JSON.stringify({ path })
  });
}

export function analyzeProjectWorkspace(workspaceId) {
  return request(`/api/project/workspaces/${workspaceId}/analyze`, { method: "POST" });
}

export function getProjectTasks(workspaceId = "") {
  const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  return request(`/api/project/tasks${query}`);
}

export function createProjectTask(workspaceId, instruction) {
  return request("/api/project/tasks", {
    method: "POST",
    body: JSON.stringify({ workspace_id: workspaceId, instruction })
  });
}

export function runProjectTask(taskId) {
  return request(`/api/project/tasks/${taskId}/run`, { method: "POST" });
}

export function getTaskChanges(taskId) {
  return request(`/api/project/tasks/${taskId}/changes`);
}

export function getProposal(proposalId) {
  return request(`/api/project/proposals/${proposalId}`);
}

export function decideProposal(proposalId, action, reason = "") {
  return request(`/api/project/proposals/${proposalId}/${action}`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {})
  });
}

export function getApprovals(status = "") {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return request(`/api/approvals${query}`);
}

export function decideApproval(id, approve, reason = "") {
  return request(`/api/approvals/${id}/decide`, {
    method: "POST",
    body: JSON.stringify({ approve, reason })
  });
}

export function createTask(task) {
  return request("/api/tasks", {
    method: "POST",
    body: JSON.stringify(task)
  });
}

export function updateTask(id, task) {
  return request(`/api/tasks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(task)
  });
}

export function deleteTask(id) {
  return request(`/api/tasks/${id}`, { method: "DELETE" });
}

export function getSettings() {
  return request("/api/settings");
}

export function savePreferences(preferences) {
  return request("/api/preferences", {
    method: "PUT",
    body: JSON.stringify(preferences)
  });
}

export function getTokens() {
  return request("/api/tokens");
}

export function getLogs() {
  return request("/api/logs");
}

export function getStorageStatus() {
  return request("/api/storage/status");
}

export function getStoragePlan() {
  return request("/api/storage/plan");
}

export function getStorageTopology() {
  return request("/api/storage/topology");
}

export function getGraphStatus() {
  return request("/api/storage/graph/status");
}

export function getVectorCount(namespace) {
  const query = namespace ? `?namespace=${encodeURIComponent(namespace)}` : "";
  return request(`/api/storage/vectors/count${query}`);
}

export function sendChat(payload) {
  return request("/api/chat", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export async function streamChat(payload, handlers) {
  const headers = { "Content-Type": "application/json" };
  const token = getApiToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers,
    body: JSON.stringify(payload)
  });
  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "request failed");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data: "));
      if (dataLine) {
        const data = JSON.parse(dataLine.slice(6));
        if (data.type === "chunk") handlers.onChunk?.(data.content || "");
        if (data.type === "done") handlers.onDone?.(data);
        if (data.type === "error") handlers.onError?.(data.message || "stream error");
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}
