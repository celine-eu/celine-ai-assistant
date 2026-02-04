// frontend/src/libs/api.ts

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
  conversation_id: string | null;
}): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch("/api/chat", {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok || !res.body) {
    throw new Error(await res.text());
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);

      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;

      yield JSON.parse(line.slice(6));
    }
  }
}

export async function getUser() {
  const res = await fetch("/api/user", { credentials: "include" });
  if (!res.ok) return null;
  return res.json();
}

export async function reindex() {
  await fetch("/api/admin/ingest", { method: "POST", credentials: "include" });
}

export async function reload() {
  await fetch("/api/admin/reload", { method: "POST", credentials: "include" });
}
