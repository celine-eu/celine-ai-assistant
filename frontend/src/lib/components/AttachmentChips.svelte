<script context="module" lang="ts">
    export type Attachment = {
        id: string;
        filename: string;
    };
</script>

<script lang="ts">
    import { createEventDispatcher } from "svelte";

    export let attachments: Attachment[] = [];

    const dispatch = createEventDispatcher<{ remove: { id: string } }>();
</script>

{#if attachments.length}
    <div class="attachments">
        {#each attachments as a (a.id)}
            <div class="chip">
                <span class="chipName">{a.filename}</span>
                <button
                    type="button"
                    on:click={() => dispatch("remove", { id: a.id })}
                >
                    ✕
                </button>
            </div>
        {/each}
    </div>
{/if}
