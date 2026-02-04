<script lang="ts">
    export let type: "button" | "submit" | "reset" = "button";
    export let disabled = false;
    export let variant: "primary" | "ghost" | "danger" = "primary";
</script>

<button class="btn {variant}" {type} {disabled}>
    <slot />
</button>

<style>
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
        transition:
            background 120ms ease,
            border-color 120ms ease,
            transform 80ms ease;
    }

    .btn:hover:enabled {
        background: #f8fafc;
        border-color: #cbd5e1;
    }

    .btn:active:enabled {
        transform: translateY(1px);
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

    .danger {
        background: #b91c1c;
        border-color: #b91c1c;
        color: #fff;
    }

    .danger:hover:enabled {
        background: #991b1b;
        border-color: #991b1b;
    }
</style>
