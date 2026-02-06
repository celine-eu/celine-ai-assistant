export type ChatStreamEvent =
  | { type: "meta"; data: { conversation_id?: string } }
  | { type: "token"; data: string }
  | { type: "sources"; data: any[] }
  | { type: "error"; data: string };

export async function uploadFile(file: File) {
  const fd = new FormData();
  fd.append("file", file);

  const res = await fetch("/api/upload", {
    method: "POST",
    body: fd,
    credentials: "include",
  });

  const ct = res.headers.get("content-type") ?? "";
  if (!res.ok) {
    const err = ct.includes("json") ? JSON.stringify(await res.json()) : await res.text();
    throw new Error(err);
  }

  if (ct.includes("json")) return await res.json();
  return { status: "ok" };
}

export async function* chatStream(payload: {
  message: string;
  include_citations: boolean;
  top_k: number;
  conversation_id?: string | null;
  attachment_ids?: string[];
}) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      message: payload.message,
      include_citations: payload.include_citations,
      top_k: payload.top_k,
      conversation_id: payload.conversation_id ?? null,
      attachment_ids: payload.attachment_ids ?? [],
    }),
  });

  if (!res.ok || !res.body) {
    const txt = await res.text();
    throw new Error(txt || `HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();

  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);

      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const jsonStr = line.slice("data: ".length);
      yield JSON.parse(jsonStr);
    }
  }
}

export async function getUser() {
  const res = await fetch("/api/user", { credentials: "include" });
  if (!res.ok) return null;
  return res.json();
}

export async function reindex() {
  const res = await fetch("/api/admin/ingest", { method: "POST", credentials: "include" });
  if (!res.ok) throw new Error(await res.text());
}

export async function reload() {
  const res = await fetch("/api/admin/reload", { method: "POST", credentials: "include" });
  if (!res.ok) throw new Error(await res.text());
}

export async function listConversations() {
  const res = await fetch("/api/conversations", { credentials: "include" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteConversation(conversationId: string) {
  const res = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchConversationMessages(conversationId: string) {
  const res = await fetch(`/api/conversations/${encodeURIComponent(conversationId)}/messages`, {
    credentials: "include",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listAttachments() {
  const res = await fetch("/api/attachments", { credentials: "include" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function attachmentRawUrl(attachmentId: string) {
  return `/api/attachments/${encodeURIComponent(attachmentId)}/raw`;
}

export async function deleteAttachment(attachmentId: string) {
  const res = await fetch(`/api/attachments/${encodeURIComponent(attachmentId)}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
