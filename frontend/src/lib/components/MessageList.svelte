<script lang="ts">
    import ChatMessage from "$lib/components/ChatMessage.svelte";
    import DOMPurify from "dompurify";
    import { marked } from "marked";
    import { tick } from "svelte";

    function renderMarkdown(md: string): string {
        return DOMPurify.sanitize(marked.parse(md, { async: false }) as string);
    }

    export let messages: {
        role: "user" | "assistant";
        content: string;
        attachments?: any[];
        sources?: any[];
    }[] = [];

    export let showSources = true;

    let el: HTMLElement | null = null;
    let bottom: HTMLElement | null = null;

    let stickToBottom = true;

    function updateStickiness() {
        if (!el) return;
        const gap = el.scrollHeight - (el.scrollTop + el.clientHeight);
        stickToBottom = gap < 140;
    }

    export async function scrollToBottom(force = false) {
        if (!force && !stickToBottom) return;
        await tick();
        bottom?.scrollIntoView({ block: "end", behavior: "smooth" });
    }
</script>

<section class="chat" bind:this={el} on:scroll={updateStickiness}>
    {#each messages as m, i (i)}
        <ChatMessage
            role={m.role}
            content={m.content}
            attachments={m.attachments}
            sources={m.sources}
            {renderMarkdown}
            {showSources}
        />
    {/each}
    <div bind:this={bottom}></div>
</section>

<style>
    .chat {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
    }
</style>
