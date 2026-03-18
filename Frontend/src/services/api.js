const API_BASE_URL = "http://localhost:8000";

export async function createSession() {
  const res = await fetch(`${API_BASE_URL}/chat/session`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to create session");
  return res.json(); // { session_id }
}

export async function getSession(sessionId) {
  const res = await fetch(`${API_BASE_URL}/chat/session/${sessionId}`);
  if (!res.ok) throw new Error("Failed to fetch session");
  return res.json(); // { session_id, messages[] }
}

export async function sendMessage(sessionId, message) {
  const res = await fetch(`${API_BASE_URL}/chat/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to send message");
  }
  return res.json(); // { session_id, reply: MessageItem }
}

export async function getSchema() {
  const res = await fetch(`${API_BASE_URL}/schema`);
  if (!res.ok) throw new Error("Failed to fetch schema");
  return res.json();
}
