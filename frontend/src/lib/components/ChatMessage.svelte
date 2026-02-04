<script lang="ts">
    import Markdown from "./Markdown.svelte";

    export let role: "user" | "assistant";
    export let content: string;
    export let attachments:
        | { id: string; filename: string; previewUrl?: string }[]
        | undefined;
    export let sources: any[] | undefined;
    export let showSources: boolean;
</script>

<div class="msg {role}">
    <div class="bubble">
        <div class="role">{role === "user" ? "You" : "Assistant"}</div>

        {#if role === "assistant"}
            <div><Markdown text={content} /></div>
        {:else}
            <div class="content">{content}</div>

            {#if attachments}
                <div class="msgAttachments">
                    {#each attachments as a (a.id)}
                        {#if a.previewUrl}
                            <img src={a.previewUrl} alt={a.filename} />
                        {:else}
                            <div class="fileLine">{a.filename}</div>
                        {/if}
                    {/each}
                </div>
            {/if}
        {/if}

        {#if role === "assistant" && showSources && sources?.length}
            <details>
                <summary>Sources</summary>
                <ul>
                    {#each sources as s}
                        <li><Markdown text={s.text} /></li>
                    {/each}
                </ul>
            </details>
        {/if}
    </div>
</div>

<style>
    .msg {
        display: flex;
    }
    .msg.user {
        justify-content: flex-end;
    }
    .bubble {
        max-width: 780px;
        padding: 14px;
        border-radius: 16px;
        background: white;
        border: 1px solid #e2e8f0;
    }
    .msg.user .bubble {
        background: #0ea5e9;
        color: white;
    }
    img {
        max-width: 420px;
        border-radius: 12px;
    }
</style>
