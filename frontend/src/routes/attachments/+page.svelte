<script lang="ts">
    import {
        attachmentRawUrl,
        deleteAttachment,
        getUser,
        listAttachments,
        reindex,
        reload,
    } from "$lib/api";
    import Topbar from "$lib/components/Topbar.svelte";
    import { onMount } from "svelte";

    let isAdmin = false;
    let busy = false;
    let errorBanner: string | null = null;

    let items: any[] = [];

    function fmt(ts: number) {
        try {
            return new Date(ts * 1000).toLocaleString();
        } catch {
            return String(ts);
        }
    }

    function isImage(att: any) {
        const ct = String(att?.content_type ?? "");
        if (ct.startsWith("image/")) return true;
        const fn = String(att?.filename ?? "");
        return /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(fn);
    }

    async function load() {
        const res = await listAttachments();
        items = res?.items ?? [];
    }

    onMount(async () => {
        try {
            const u = await getUser();
            isAdmin = Boolean(u?.is_admin);
            await load();
        } catch (e) {
            errorBanner = e instanceof Error ? e.message : String(e);
        }
    });

    async function onDelete(id: string) {
        errorBanner = null;
        busy = true;
        try {
            await deleteAttachment(id);
            await load();
        } catch (e) {
            errorBanner = e instanceof Error ? e.message : String(e);
        } finally {
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
</script>

<div class="page">
    <Topbar includeCitations={true} {busy} {isAdmin} {onReindex} {onReload} />

    {#if errorBanner}
        <div class="banner">{errorBanner}</div>
    {/if}

    <section class="wrap">
        <h1>Attachments</h1>

        {#if !items.length}
            <div class="empty">No uploads yet.</div>
        {:else}
            <div class="grid">
                {#each items as a (a.id)}
                    <div class="card">
                        <div class="preview">
                            {#if isImage(a)}
                                <img
                                    src={attachmentRawUrl(a.id)}
                                    alt={a.filename}
                                />
                            {:else}
                                <div class="fileIcon">FILE</div>
                            {/if}
                        </div>

                        <div class="meta">
                            <div class="name">{a.filename}</div>
                            <div class="sub">
                                <span>{a.size_bytes} bytes</span>
                                <span>•</span>
                                <span>{fmt(a.created_at)}</span>
                            </div>
                        </div>

                        <div class="actions">
                            <a
                                class="btn"
                                href={attachmentRawUrl(a.id)}
                                target="_blank"
                                rel="noreferrer">Open</a
                            >
                            <button
                                class="btn danger"
                                on:click={() => onDelete(a.id)}
                                disabled={busy}
                            >
                                Delete
                            </button>
                        </div>
                    </div>
                {/each}
            </div>
        {/if}
    </section>
</div>

<style>
    .page {
        min-height: 100vh;
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

    .wrap {
        padding: 18px;
    }

    h1 {
        margin: 0 0 14px 0;
        font-size: 20px;
    }

    .empty {
        padding: 14px;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
    }

    .grid {
        display: grid;
        gap: 14px;
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    }

    .card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        overflow: hidden;
        display: flex;
        flex-direction: column;
    }

    .preview {
        height: 160px;
        background: #f8fafc;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    img {
        width: 100%;
        height: 160px;
        object-fit: cover;
        display: block;
    }

    .fileIcon {
        width: 90px;
        height: 90px;
        border-radius: 16px;
        border: 2px dashed #94a3b8;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #475569;
        font-weight: 800;
        letter-spacing: 0.04em;
    }

    .meta {
        padding: 12px 12px 0 12px;
    }

    .name {
        font-size: 13px;
        word-break: break-word;
        color: #0f172a;
    }

    .sub {
        margin-top: 6px;
        color: #64748b;
        font-size: 12px;
        display: flex;
        gap: 8px;
        align-items: center;
    }

    .actions {
        padding: 12px;
        display: flex;
        gap: 10px;
        margin-top: auto;
    }

    .btn {
        appearance: none;
        border: 1px solid #e2e8f0;
        background: #fff;
        color: #0f172a;
        border-radius: 10px;
        padding: 10px 12px;
        font: inherit;
        line-height: 1;
        cursor: pointer;
        text-decoration: none;
        display: inline-flex;
        align-items: center;
    }

    .btn:hover {
        background: #f8fafc;
        border-color: #cbd5e1;
    }

    .danger {
        border-color: #fecaca;
        color: #991b1b;
    }

    .danger:hover:enabled {
        background: #fee2e2;
        border-color: #fca5a5;
    }

    button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
</style>
