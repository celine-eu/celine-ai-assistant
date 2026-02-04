<script lang="ts">
    export let value = "";
    export let placeholder = "";
    export let disabled = false;
    export let ariaLabel: string | undefined = undefined;
</script>

<input class="ti" bind:value {placeholder} {disabled} aria-label={ariaLabel} />

<style>
    .ti {
        width: 100%;
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

    .ti:focus {
        border-color: #94a3b8;
        box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.35);
    }

    .ti:disabled {
        background: #f8fafc;
        color: #64748b;
    }
</style>
