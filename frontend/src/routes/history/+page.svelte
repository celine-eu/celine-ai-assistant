<script lang="ts">
    import {
        deleteConversation,
        getUser,
        listConversations,
        reindex,
        reload,
    } from "$lib/api";
    import Markdown from "$lib/components/Markdown.svelte";
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

    async function load() {
        const res = await listConversations();
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
            await deleteConversation(id);
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
        <h1>History</h1>

        {#if !items.length}
            <div class="empty">No conversations yet.</div>
        {:else}
            <div class="list">
                {#each items as c (c.conversation_id)}
                    <div class="card">
                        <div class="meta">
                            <div class="id">{c.conversation_id}</div>
                            <div class="sub">
                                <span>{c.message_count} msgs</span>
                                <span>•</span>
                                <span>Last: {fmt(c.last_message_at)}</span>
                            </div>
                            {#if c.last_snippet}
                                <div class="snippet">
                                    <Markdown text={c.last_snippet} />
                                </div>
                            {/if}
                        </div>

                        <div class="actions">
                            <a
                                class="btn"
                                href={"/?conversation_id=" +
                                    encodeURIComponent(c.conversation_id)}
                                >Open</a
                            >
                            <button
                                class="btn danger"
                                on:click={() => onDelete(c.conversation_id)}
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

    .list {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .card {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        padding: 14px;
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
    }

    .id {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
            "Liberation Mono";
        font-size: 12px;
        color: #334155;
    }

    .sub {
        margin-top: 6px;
        color: #64748b;
        font-size: 12px;
        display: flex;
        gap: 8px;
        align-items: center;
    }

    .snippet {
        margin-top: 10px;
        color: #0f172a;
        font-size: 13px;
        white-space: pre-wrap;
        word-break: break-word;
    }

    .actions {
        display: flex;
        gap: 10px;
        align-items: flex-start;
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
