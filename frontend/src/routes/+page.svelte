<script lang="ts">
  import { browser } from "$app/environment";
  import DOMPurify from "dompurify";
  import { marked } from "marked";

  type SourceChunk = {
    source: string;
    title?: string | null;
    text: string;
    score?: number | null;
  };

  type Msg = {
    role: "user" | "assistant";
    content: string;
    sources?: SourceChunk[];
  };

  let input = "";
  let messages: Msg[] = [];
  let busy = false;
  let includeCitations = true;
  let conversationId: string | null = null;

  let uploadBusy = false;
  let uploadStatus: string | null = null;

  function addUserMessage(text: string) {
    messages = [...messages, { role: "user", content: text }];
  }

  function addAssistantPlaceholder() {
    messages = [...messages, { role: "assistant", content: "", sources: [] }];
  }

  function updateLastAssistant(delta: string) {
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant") return;
    const updated = { ...last, content: last.content + delta };
    messages = [...messages.slice(0, -1), updated];
  }

  function setLastAssistantSources(sources: SourceChunk[]) {
    const last = messages[messages.length - 1];
    if (!last || last.role !== "assistant") return;
    const updated = { ...last, sources };
    messages = [...messages.slice(0, -1), updated];
  }

  async function uploadFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    uploadBusy = true;
    uploadStatus = null;

    try {
      for (const f of Array.from(files)) {
        const fd = new FormData();
        fd.append("file", f);

        const res = await fetch("/api/upload", {
          method: "POST",
          body: fd,
          credentials: "include",
        });
        const txt = await res.text();
        if (!res.ok) {
          uploadStatus = `Upload failed for ${f.name}: ${txt}`;
          break;
        } else {
          uploadStatus = `Uploaded: ${f.name}`;
        }
      }
    } catch (e: any) {
      uploadStatus = e?.message ?? String(e);
    } finally {
      uploadBusy = false;
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    uploadFiles(e.dataTransfer?.files ?? null);
  }

  function onDragOver(e: DragEvent) {
    e.preventDefault();
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;

    busy = true;
    input = "";

    addUserMessage(text);
    addAssistantPlaceholder();
    scrollToBottom();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          message: text,
          include_citations: includeCitations,
          top_k: 5,
          conversation_id: conversationId,
        }),
      });

      if (!res.ok || !res.body) {
        const err = await res.text();
        updateLastAssistant(`\n[Error] ${err}`);
        busy = false;
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buf += decoder.decode(value, { stream: true });

        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);

          const line = frame.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;

          const payload = JSON.parse(line.slice(6));

          if (payload.type === "meta") {
            conversationId = payload.data?.conversation_id ?? conversationId;
          }
          if (payload.type === "token") updateLastAssistant(payload.data);
          if (payload.type === "sources") setLastAssistantSources(payload.data);
          if (payload.type === "error")
            updateLastAssistant(`\n[Error] ${payload.data}`);
        }
      }
    } catch (e: any) {
      updateLastAssistant(`\n[Error] ${e?.message ?? String(e)}`);
    } finally {
      busy = false;
    }
  }

  async function reindex() {
    try {
      await fetch("/api/admin/ingest", {
        method: "POST",
        credentials: "include",
      });
    } catch {}
  }

  async function forceReload() {
    try {
      await fetch("/api/admin/reload", {
        method: "POST",
        credentials: "include",
      });
    } catch {}
  }

  function newConversation() {
    conversationId = null;
    messages = [];
  }

  function renderMarkdown(md: string) {
    if (!browser) return "";
    return DOMPurify.sanitize(marked.parse(md, { async: false }));
  }
  let bottomEl: HTMLDivElement | null = null;

  function scrollToBottom() {
    bottomEl?.scrollIntoView({ behavior: "smooth", block: "end" });
  }
</script>

<div class="shell">
  <header class="topbar">
    <div class="brand">
      <div class="dot"></div>
      <div>
        <div class="title">CELINE AI assistant</div>
        <div class="subtitle">
          Upload a file or ask me questions about energy
        </div>
      </div>
    </div>

    <div class="controls">
      <label class="toggle">
        <input type="checkbox" bind:checked={includeCitations} />
        <span>Sources</span>
      </label>

      <button class="btn" on:click={newConversation} disabled={busy}
        >New chat</button
      >
      <button class="btn" on:click={reindex} disabled={busy}>Poll ingest</button
      >
      <button class="btn" on:click={forceReload} disabled={busy}
        >Force reload</button
      >
    </div>
  </header>

  <section class="uploader" on:drop={onDrop} on:dragover={onDragOver}>
    <div class="uploadCard">
      <div class="uploadTitle">Drag & drop files here</div>
      <div class="uploadText">
        Docs are indexed immediately. Images are described via vision first.
      </div>
      <div class="uploadRow">
        <input
          class="file"
          type="file"
          multiple
          on:change={(e) =>
            uploadFiles((e.currentTarget as HTMLInputElement).files)}
          disabled={uploadBusy}
        />
        <div class="uploadStatus">
          {uploadBusy ? "Uploading…" : (uploadStatus ?? " ")}
        </div>
      </div>
    </div>
  </section>

  <section class="chat">
    {#if messages.length === 0}
      <div class="empty">
        <div class="emptyCard">
          <div class="emptyTitle">Ask something 👇</div>
          <div class="emptyText">
            Conversation ID: {conversationId ?? "new"}<br />
            Streaming answers with optional sources.
          </div>
        </div>
      </div>
    {/if}

    {#each messages as m}
      <div class="msg {m.role}">
        <div class="bubble">
          <div class="role">{m.role === "user" ? "You" : "Assistant"}</div>

          {#if m.role === "assistant"}
            <div class="">
              {@html renderMarkdown(m.content)}
            </div>
          {:else}
            <div class="content">{m.content}</div>
          {/if}

          {#if m.role === "assistant" && m.sources && m.sources.length > 0 && includeCitations}
            <details class="sources">
              <summary>Sources</summary>
              <ul>
                {#each m.sources as s}
                  <li>
                    <div class="src">{s.source}</div>
                    {#if s.title}<div class="meta">{s.title}</div>{/if}
                    <pre class="snippet">{s.text}</pre>
                  </li>
                {/each}
              </ul>
            </details>
          {/if}
        </div>
      </div>
    {/each}

    <div bind:this={bottomEl}></div>
  </section>

  <footer class="composer">
    <form on:submit|preventDefault={send} class="row">
      <input
        class="input"
        placeholder="Ask a question…"
        bind:value={input}
        disabled={busy}
      />
      <button
        class="send"
        type="submit"
        disabled={busy || input.trim().length === 0}
      >
        {busy ? "…" : "Send"}
      </button>
    </form>
  </footer>
</div>

<style>
  .shell {
    max-width: 1100px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }
  .topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 18px 16px;
    position: sticky;
    top: 0;
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
    z-index: 10;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .dot {
    width: 12px;
    height: 12px;
    border-radius: 999px;
    background: #0ea5e9;
  }
  .title {
    font-weight: 700;
  }
  .subtitle {
    font-size: 12px;
    color: #64748b;
  }
  .controls {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .toggle {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 13px;
    color: #334155;
  }
  .btn {
    padding: 8px 10px;
    border-radius: 10px;
    border: 1px solid #cbd5e1;
    background: white;
    cursor: pointer;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .uploader {
    padding: 16px;
  }
  .uploadCard {
    padding: 16px;
    border-radius: 16px;
    background: white;
    border: 1px dashed #94a3b8;
    box-shadow: 0 6px 22px rgba(15, 23, 42, 0.06);
  }
  .uploadTitle {
    font-weight: 700;
  }
  .uploadText {
    margin-top: 6px;
    font-size: 13px;
    color: #475569;
  }
  .uploadRow {
    margin-top: 12px;
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
  .file {
    max-width: 360px;
  }
  .uploadStatus {
    font-size: 12px;
    color: #334155;
    min-height: 16px;
  }

  .chat {
    flex: 1;
    padding: 18px 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .empty {
    display: flex;
    justify-content: center;
    margin-top: 40px;
  }
  .emptyCard {
    max-width: 520px;
    padding: 18px;
    border-radius: 16px;
    background: white;
    border: 1px solid #e2e8f0;
    box-shadow: 0 6px 22px rgba(15, 23, 42, 0.06);
  }
  .emptyTitle {
    font-weight: 700;
    margin-bottom: 6px;
  }
  .emptyText {
    color: #475569;
    font-size: 13px;
  }

  .msg {
    display: flex;
  }
  .msg.user {
    justify-content: flex-end;
  }
  .msg.assistant {
    justify-content: flex-start;
  }
  .bubble {
    max-width: 780px;
    width: fit-content;
    padding: 14px 14px;
    border-radius: 16px;
    background: white;
    border: 1px solid #e2e8f0;
    box-shadow: 0 6px 22px rgba(15, 23, 42, 0.06);
  }
  .msg.user .bubble {
    background: #0ea5e9;
    color: white;
    border-color: #0ea5e9;
  }
  .role {
    font-size: 11px;
    opacity: 0.75;
    margin-bottom: 8px;
  }
  .content {
    white-space: pre-wrap;
    line-height: 1.35;
  }

  .sources {
    margin-top: 10px;
  }
  .sources summary {
    cursor: pointer;
    font-size: 13px;
    color: inherit;
  }
  .sources ul {
    margin: 10px 0 0 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .sources li {
    padding: 10px;
    border-radius: 12px;
    border: 1px solid #e2e8f0;
    background: rgba(248, 250, 252, 0.7);
  }
  .msg.user .sources li {
    background: rgba(255, 255, 255, 0.12);
    border-color: rgba(255, 255, 255, 0.25);
  }
  .src {
    font-size: 12px;
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  .meta {
    font-size: 12px;
    opacity: 0.8;
    margin-top: 4px;
  }
  .snippet {
    margin-top: 8px;
    font-size: 12px;
    white-space: pre-wrap;
    color: inherit;
    opacity: 0.9;
  }

  .composer {
    padding: 16px;
    border-top: 1px solid #e2e8f0;
    background: #f8fafc;
    position: sticky;
    bottom: 0;
  }
  .row {
    display: flex;
    gap: 10px;
  }
  .input {
    flex: 1;
    padding: 12px 14px;
    border-radius: 14px;
    border: 1px solid #cbd5e1;
    background: white;
    font-size: 14px;
  }
  .send {
    padding: 12px 14px;
    border-radius: 14px;
    border: none;
    background: #0f172a;
    color: white;
    cursor: pointer;
    min-width: 90px;
  }
  .send:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
