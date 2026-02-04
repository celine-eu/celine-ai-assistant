<script lang="ts">
    export let visible: boolean;
</script>

{#if visible}
    <div class="dropOverlay">
        <div class="dropOverlayCard">Drop files to attach</div>
    </div>
{/if}

<style>
    .dropOverlay {
        position: fixed;
        inset: 0;
        background: rgba(15, 23, 42, 0.25);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 50;
    }

    .dropOverlayCard {
        background: white;
        border: 2px dashed #94a3b8;
        border-radius: 16px;
        padding: 22px 26px;
        font-weight: 700;
    }
</style>
