<script lang="ts">
  import Composer from "$lib/components/Composer.svelte";
  import DropOverlay from "$lib/components/DropOverlay.svelte";
  import MessageList from "$lib/components/MessageList.svelte";
  import Topbar from "$lib/components/Topbar.svelte";

  import { chatStream, reindex, reload, uploadFile } from "$lib/api";

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

  // Attachments live in the page since they affect send/upload flow
  let attachments: Attachment[] = [];
  const attachmentFiles = new Map<string, File>();

  // drag/drop overlay state
  let dragging = false;
  let dragDepth = 0;

  let messageList: InstanceType<typeof MessageList> | null = null;
  let composer: InstanceType<typeof Composer> | null = null;

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
    attachmentFiles.delete(id);
    attachments = attachments.filter((x) => x.id !== id);
  }

  async function uploadAllAttachments(): Promise<Attachment[]> {
    if (!attachments.length) return [];

    const uploaded: Attachment[] = [];
    for (const a of attachments) {
      const f = attachmentFiles.get(a.id);
      if (!f) continue;
      const res = await uploadFile(f); // should throw on non-2xx
      uploaded.push({
        ...a,
        uri: res?.uri ?? res?.data?.uri ?? undefined,
      });
    }
    return uploaded;
  }

  async function send() {
    const text = input.trim();
    if (!text && !attachments.length) return;

    busy = true;
    errorBanner = null;

    // snapshot & clear composer state immediately
    const localText = text;
    const localAttachments = attachments;
    input = "";
    attachments = [];
    attachmentFiles.clear();

    // optimistic add user + assistant placeholders
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
      const uploaded = await uploadAllAttachments();
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
            "Unknown streaming error";
          throw new Error(String(msg));
        }
      }

      // after stream ends, commit final assistant message metadata
      messages[assistantIdx] = {
        ...messages[assistantIdx],
        content: acc,
        sources: pendingSources,
        attachments: uploaded.length ? uploaded : undefined,
      };
      messages = messages;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      errorBanner = msg;
      messages[assistantIdx] = {
        ...messages[assistantIdx],
        content: `Error: ${msg}`,
      };
      messages = messages;
    } finally {
      for (const a of localAttachments)
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
      busy = false;
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

<svelte:window
  on:dragenter={onDragEnter}
  on:dragleave={onDragLeave}
  on:dragover|preventDefault={() => {}}
  on:drop|preventDefault={onDrop}
/>

<DropOverlay visible={dragging} />

<div class="page">
  <Topbar bind:includeCitations {busy} {onReindex} {onReload} />

  {#if errorBanner}
    <div class="banner">{errorBanner}</div>
  {/if}
  <MessageList
    bind:this={messageList}
    {messages}
    showSources={includeCitations}
  />

  <Composer
    bind:this={composer}
    bind:value={input}
    {busy}
    attachments={attachments.map(({ id, filename, previewUrl }) => ({
      id,
      filename,
      previewUrl,
    }))}
    onAddFiles={addFiles}
    onRemoveAttachment={removeAttachment}
    onSend={send}
  />
</div>

<style>
  /* Only page-level layout owns these containers, so it’s OK here */
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
