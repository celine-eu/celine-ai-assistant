<script lang="ts">
    export let includeCitations = true;
    export let busy = false;
    export let isAdmin = false;

    export let onReindex: () => Promise<void>;
    export let onReload: () => Promise<void>;
</script>

<header class="topbar">
    <div class="left">
        <div class="brand">
            <a
                class="brandLink"
                on:click={() => (window.location.href = "/")}
                on:keydown={(e) =>
                    e.key === "Enter" && (window.location.href = "/")}
                href="/">CELINE Assistant</a
            >
        </div>

        <nav class="nav">
            <a class="navLink" href="/">Chat</a>
            <a class="navLink" href="/history">History</a>
            <a class="navLink" href="/attachments">Attachments</a>
        </nav>
    </div>

    <div class="actions">
        <label class="toggle">
            <input type="checkbox" bind:checked={includeCitations} />
            <span>Citations</span>
        </label>

        {#if isAdmin}
            <button type="button" on:click={() => onReindex()} disabled={busy}
                >Reindex</button
            >
            <button type="button" on:click={() => onReload()} disabled={busy}
                >Reload</button
            >
        {/if}
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

    .left {
        display: flex;
        align-items: center;
        gap: 16px;
    }

    .brand {
        font-weight: 700;
    }

    .brandLink {
        color: inherit;
        text-decoration: none;
    }

    .nav {
        display: flex;
        gap: 12px;
    }

    .navLink {
        color: #0f172a;
        text-decoration: none;
        padding: 6px 10px;
        border-radius: 10px;
        border: 1px solid transparent;
    }

    .navLink:hover {
        background: #f8fafc;
        border-color: #e2e8f0;
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
