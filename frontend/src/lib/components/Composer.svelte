<script lang="ts">
    export let value = "";
    export let busy = false;

    export let attachments: {
        id: string;
        filename: string;
        previewUrl?: string;
    }[] = [];

    export let onAddFiles: (files: FileList | null) => void;
    export let onRemoveAttachment: (id: string) => void;
    export let onSend: () => Promise<void>;

    let fileEl: HTMLInputElement | null = null;
    let inputEl: HTMLInputElement | null = null;

    export function focusInput() {
        inputEl?.focus();
    }

    function pickFiles() {
        fileEl?.click();
    }
</script>

<footer class="composer">
    <input
        class="hidden"
        type="file"
        multiple
        bind:this={fileEl}
        on:change={(e) => {
            onAddFiles((e.currentTarget as HTMLInputElement).files);
            (e.currentTarget as HTMLInputElement).value = "";
            focusInput();
        }}
    />

    {#if attachments.length}
        <div class="chips" aria-label="Attachments">
            {#each attachments as a (a.id)}
                <div class="chip" title={a.filename}>
                    <span class="name">{a.filename}</span>
                    <button
                        type="button"
                        class="x"
                        on:click={() => onRemoveAttachment(a.id)}
                        disabled={busy}
                        aria-label={"Remove " + a.filename}
                        title="Remove"
                    >
                        ✕
                    </button>
                </div>
            {/each}
        </div>
    {/if}

    <form class="row" on:submit|preventDefault={() => onSend()}>
        <button
            type="button"
            class="btn ghost"
            on:click={pickFiles}
            disabled={busy}
            tabindex="-3"
        >
            Upload
        </button>

        <input
            class="text"
            bind:this={inputEl}
            bind:value
            placeholder="Ask something…"
            disabled={busy}
            aria-label="Chat message"
            tabindex="0"
        />

        <button
            type="submit"
            class="btn primary"
            disabled={busy || (!value.trim() && attachments.length === 0)}
            tabindex="-2"
        >
            Send
        </button>
    </form>
</footer>

<style>
    .composer {
        padding: 16px;
        border-top: 1px solid #e2e8f0;
        background: #fff;
    }

    .chips {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 10px;
    }

    .chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        max-width: 100%;
        border: 1px solid #e2e8f0;
        background: #f8fafc;
        border-radius: 999px;
        padding: 6px 10px;
    }

    .name {
        max-width: 260px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .x {
        border: 0;
        background: transparent;
        cursor: pointer;
        font: inherit;
        line-height: 1;
        padding: 0 2px;
        opacity: 0.75;
    }

    .x:hover:enabled {
        opacity: 1;
    }

    .x:disabled {
        cursor: not-allowed;
        opacity: 0.4;
    }

    .row {
        display: flex;
        align-items: center;
        gap: 10px;
    }

    .text {
        flex: 1;
        min-width: 0;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 10px 12px;
        background: #fff;
        color: #0f172a;
        font: inherit;
        line-height: 1.2;
        outline: none;
    }

    .text:focus {
        border-color: #94a3b8;
        box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.35);
    }

    .text:disabled {
        background: #f8fafc;
        color: #64748b;
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
    }

    .btn:hover:enabled {
        background: #f8fafc;
        border-color: #cbd5e1;
    }

    .btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .primary {
        background: #0f172a;
        border-color: #0f172a;
        color: #fff;
    }

    .primary:hover:enabled {
        background: #111c33;
        border-color: #111c33;
    }

    .ghost {
        background: transparent;
    }

    .hidden {
        display: none;
    }
</style>
