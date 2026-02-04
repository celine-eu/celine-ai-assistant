<script lang="ts">
  import Composer from "$lib/components/Composer.svelte";
  import DropOverlay from "$lib/components/DropOverlay.svelte";
  import MessageList from "$lib/components/MessageList.svelte";
  import Topbar from "$lib/components/Topbar.svelte";
  import { onMount } from "svelte";

  import {
    chatStream,
    fetchConversationMessages,
    getUser,
    reindex,
    reload,
    uploadFile,
  } from "$lib/api";

  type SourceChunk = {
    source: string;
    title?: string | null;
    text: string;
    score?: number | null;
  };

  type Attachment = {
    id: string;
    filename: string;
    contentType: string | null;
    size: number;
    previewUrl?: string;
    uri?: string;
    attachmentId?: string;
  };

  type Msg = {
    role: "user" | "assistant";
    content: string;
    sources?: SourceChunk[];
    attachments?: Attachment[];
  };

  let includeCitations = true;
  let busy = false;
  let errorBanner: string | null = null;

  let conversationId: string | null = null;
  let messages: Msg[] = [];
  let input = "";

  let attachments: Attachment[] = [];
  const attachmentFiles = new Map<string, File>();

  let dragging = false;
  let dragDepth = 0;

  let messageList: InstanceType<typeof MessageList> | null = null;
  let composer: InstanceType<typeof Composer> | null = null;

  let isAdmin = false;

  onMount(async () => {
    try {
      const u = await getUser();
      isAdmin = Boolean(u?.is_admin);

      const url = new URL(window.location.href);
      const cid = url.searchParams.get("conversation_id");
      if (cid) {
        conversationId = cid;
        const res = await fetchConversationMessages(cid);
        const loaded: Msg[] = (res?.messages ?? []).map((m: any) => ({
          role: m.role,
          content: m.content,
        }));
        messages = loaded;
        await messageList?.scrollToBottom(true);
      }
    } catch (e) {
      errorBanner = e instanceof Error ? e.message : String(e);
    }
  });

  function addFiles(files: FileList | null) {
    if (!files) return;
    for (const f of Array.from(files)) {
      const id = crypto.randomUUID();
      attachmentFiles.set(id, f);

      const a: Attachment = {
        id,
        filename: f.name,
        contentType: f.type || null,
        size: f.size,
      };

      if (
        a.contentType?.startsWith("image/") ||
        /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(a.filename)
      ) {
        a.previewUrl = URL.createObjectURL(f);
      }

      attachments = [...attachments, a];
    }
  }

  function removeAttachment(id: string) {
    const a = attachments.find((x) => x.id === id);
    if (a?.previewUrl) URL.revokeObjectURL(a.previewUrl);
    attachments = attachments.filter((x) => x.id !== id);
    attachmentFiles.delete(id);
  }

  async function uploadAllAttachments(
    local: Attachment[],
  ): Promise<Attachment[]> {
    const out: Attachment[] = [];
    for (const a of local) {
      const f = attachmentFiles.get(a.id);
      if (!f) continue;

      const res = await uploadFile(f);
      out.push({
        ...a,
        uri: res?.uri,
        attachmentId: res?.attachment_id,
      });
    }
    return out;
  }

  async function send() {
    const localText = input.trim();
    if (!localText || busy) return;

    errorBanner = null;
    busy = true;
    input = "";

    const localAttachments = attachments;
    attachments = [];

    messages = [
      ...messages,
      {
        role: "user",
        content: localText,
        attachments: localAttachments.map(
          ({ id, filename, previewUrl, contentType, size }) => ({
            id,
            filename,
            previewUrl,
            contentType,
            size,
          }),
        ),
      },
      { role: "assistant", content: "" },
    ];

    const assistantIdx = messages.length - 1;

    try {
      const uploaded = await uploadAllAttachments(localAttachments);

      let acc = "";
      let pendingSources: SourceChunk[] | undefined;

      for await (const evt of chatStream({
        message: localText,
        include_citations: includeCitations,
        top_k: 5,
        conversation_id: conversationId,
      })) {
        if (evt.type === "token") {
          const t =
            (evt as any).data?.token ??
            (evt as any).token ??
            (evt as any).data ??
            "";
          acc += String(t);
          messages[assistantIdx] = { ...messages[assistantIdx], content: acc };
          messages = messages;
          await messageList?.scrollToBottom();
          continue;
        }

        if (evt.type === "sources") {
          pendingSources =
            (evt as any).data?.sources ??
            (evt as any).sources ??
            (evt as any).data;
          continue;
        }

        if (evt.type === "meta") {
          conversationId =
            (evt as any).data?.conversation_id ??
            (evt as any).conversation_id ??
            conversationId;
          continue;
        }

        if (evt.type === "error") {
          const msg =
            (evt as any).data?.message ??
            (evt as any).message ??
            (evt as any).data ??
            "Unknown streaming error";
          throw new Error(String(msg));
        }
      }

      messages[assistantIdx] = {
        ...messages[assistantIdx],
        content: acc,
        sources: pendingSources,
        attachments: uploaded.length ? uploaded : undefined,
      };
      messages = messages;
      await messageList?.scrollToBottom(true);
    } catch (e) {
      errorBanner = e instanceof Error ? e.message : String(e);

      messages = messages.filter((_, idx) => idx !== assistantIdx);
      await messageList?.scrollToBottom(true);
    } finally {
      for (const a of localAttachments)
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
      attachmentFiles.clear();
      busy = false;
      composer?.focusInput();
    }
  }

  async function onReindex() {
    errorBanner = null;
    try {
      await reindex();
    } catch (e) {
      errorBanner = e instanceof Error ? e.message : String(e);
    }
  }

  async function onReload() {
    errorBanner = null;
    try {
      await reload();
    } catch (e) {
      errorBanner = e instanceof Error ? e.message : String(e);
    }
  }

  function onDragEnter(e: DragEvent) {
    if (!e.dataTransfer?.types.includes("Files")) return;
    dragDepth += 1;
    dragging = true;
  }

  function onDragLeave() {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dragging = false;
  }

  function onDrop(e: DragEvent) {
    dragDepth = 0;
    dragging = false;
    addFiles(e.dataTransfer?.files ?? null);
  }
</script>

<div
  class="page"
  role="document"
  on:dragenter|preventDefault={onDragEnter}
  on:dragleave|preventDefault={onDragLeave}
  on:dragover|preventDefault={() => {}}
  on:drop|preventDefault={onDrop}
>
  <Topbar {includeCitations} {busy} {isAdmin} {onReindex} {onReload} />

  {#if errorBanner}
    <div class="banner">{errorBanner}</div>
  {/if}

  <MessageList
    bind:this={messageList}
    {messages}
    showSources={includeCitations}
    assistantLoading={busy}
  />

  <Composer
    bind:this={composer}
    bind:value={input}
    {busy}
    {attachments}
    onAddFiles={addFiles}
    onRemoveAttachment={removeAttachment}
    onSend={send}
  />

  <DropOverlay visible={dragging} />
</div>

<style>
  .page {
    height: 100vh;
    display: flex;
    flex-direction: column;
    max-width: 80em;
    margin: 0 auto;
  }

  .banner {
    padding: 10px 16px;
    background: #fff7ed;
    border-bottom: 1px solid #fed7aa;
  }
</style>
