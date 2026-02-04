<script lang="ts">
    export let includeCitations = true;
    export let busy = false;

    export let onReindex: () => Promise<void>;
    export let onReload: () => Promise<void>;
</script>

<header class="topbar">
    <div class="brand">Chat</div>

    <div class="actions">
        <label class="toggle">
            <input type="checkbox" bind:checked={includeCitations} />
            <span>Citations</span>
        </label>

        <button type="button" on:click={() => onReindex()} disabled={busy}
            >Reindex</button
        >
        <button type="button" on:click={() => onReload()} disabled={busy}
            >Reload</button
        >
    </div>
</header>

<style>
    .topbar {
        padding: 16px;
        border-bottom: 1px solid #e2e8f0;
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        background: #fff;
    }

    .brand {
        font-weight: 600;
    }

    .actions {
        display: flex;
        align-items: center;
        gap: 10px;
    }

    .toggle {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        user-select: none;
    }

    button {
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

    button:hover:enabled {
        background: #f8fafc;
        border-color: #cbd5e1;
    }

    button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
</style>
