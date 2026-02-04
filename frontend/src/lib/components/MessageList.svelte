<script lang="ts">
    export let messages: Array<any> = [];
    export let showSources = true;
    export let assistantLoading = false;

    let scroller: HTMLDivElement | null = null;

    export async function scrollToBottom(force = false) {
        await tick();
        if (!scroller) return;
        if (force) {
            scroller.scrollTop = scroller.scrollHeight;
            return;
        }
        const nearBottom =
            scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <
            200;
        if (nearBottom) scroller.scrollTop = scroller.scrollHeight;
    }

    import { tick } from "svelte";
    import Markdown from "./Markdown.svelte";
</script>

<div class="wrap" bind:this={scroller}>
    {#each messages as m, idx (idx)}
        <div class="row {m.role}">
            <div class="bubble">
                {#if m.role === "assistant" && assistantLoading && idx === messages.length - 1 && (!m.content || m.content.trim().length === 0)}
                    <div class="typing" aria-label="Assistant is generating">
                        <span class="dot"></span>
                        <span class="dot"></span>
                        <span class="dot"></span>
                    </div>
                {:else if m.role === "assistant"}
                    <Markdown text={m.content} />
                {:else}
                    <div class="content">{m.content}</div>
                {/if}

                {#if m.attachments && m.attachments.length}
                    <div class="att">
                        {#each m.attachments as a (a.id)}
                            <div class="attItem">
                                {#if a.previewUrl}
                                    <img
                                        class="thumb"
                                        src={a.previewUrl}
                                        alt={a.filename}
                                    />
                                {/if}
                                <div class="attMeta">
                                    <div class="attName">{a.filename}</div>
                                    <div class="attSub">{a.size} bytes</div>
                                </div>
                            </div>
                        {/each}
                    </div>
                {/if}

                {#if m.role === "assistant" && showSources && m.sources && m.sources.length}
                    <details class="sources">
                        <summary>Sources</summary>
                        <ul>
                            {#each m.sources as s (s.source + (s.title ?? ""))}
                                <li>
                                    <div class="srcTitle">
                                        {s.title ?? s.source}
                                    </div>
                                    <div class="">
                                        <Markdown text={s.text} />
                                    </div>
                                </li>
                            {/each}
                        </ul>
                    </details>
                {/if}
            </div>
        </div>
    {/each}
</div>

<style>
    .wrap {
        flex: 1;
        overflow: auto;
        padding: 16px;
        background: #fbfdff;
    }

    .row {
        display: flex;
        margin: 10px 0;
    }

    .row.user {
        justify-content: flex-end;
    }

    .row.assistant {
        justify-content: flex-start;
    }

    .bubble {
        max-width: 70ch;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 12px 14px;
        background: white;
    }

    .row.user .bubble {
        background: #f8fafc;
    }

    .content {
        white-space: pre-wrap;
        word-break: break-word;
    }

    .typing {
        display: inline-flex;
        gap: 6px;
        align-items: center;
        height: 20px;
    }

    .dot {
        width: 7px;
        height: 7px;
        border-radius: 999px;
        background: #64748b;
        animation: bounce 1.2s infinite ease-in-out;
    }

    .dot:nth-child(2) {
        animation-delay: 0.15s;
    }

    .dot:nth-child(3) {
        animation-delay: 0.3s;
    }

    @keyframes bounce {
        0%,
        80%,
        100% {
            transform: translateY(0);
            opacity: 0.5;
        }
        40% {
            transform: translateY(-6px);
            opacity: 1;
        }
    }

    .att {
        margin-top: 10px;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .attItem {
        display: flex;
        gap: 10px;
        align-items: center;
        border: 1px solid #e2e8f0;
        background: #fff;
        border-radius: 12px;
        padding: 8px;
    }

    .thumb {
        width: 42px;
        height: 42px;
        border-radius: 10px;
        object-fit: cover;
        border: 1px solid #e2e8f0;
    }

    .attName {
        font-size: 13px;
        word-break: break-word;
    }

    .attSub {
        font-size: 12px;
        color: #64748b;
        margin-top: 2px;
    }

    .sources {
        margin-top: 10px;
        font-size: 13px;
    }

    .sources summary {
        cursor: pointer;
        color: #334155;
    }

    .sources ul {
        margin: 8px 0 0 18px;
        padding: 0;
    }

    .srcTitle {
        font-weight: 600;
        margin-bottom: 4px;
    }

    .srcText {
        color: #334155;
        white-space: pre-wrap;
    }
</style>
