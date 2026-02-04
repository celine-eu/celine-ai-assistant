<script lang="ts">
    import DOMPurify from "dompurify";
    import { marked } from "marked";

    export let text = "";

    marked.setOptions({
        gfm: true,
        breaks: true,
    });

    $: rendered = marked.parse(text ?? "");
    $: html =
        typeof rendered === "string"
            ? DOMPurify.sanitize(rendered, {
                  USE_PROFILES: { html: true },
                  ALLOWED_URI_REGEXP:
                      /^(?:(?:https?|mailto|tel):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i,
                  ADD_ATTR: ["target", "rel"],
              })
            : "";
</script>

<div class="markdown">
    {@html html}
</div>

<style>
    .markdown :global(p) {
        margin: 0.6em 0;
    }

    .markdown :global(pre) {
        background: #0f172a;
        color: #e5e7eb;
        padding: 12px;
        border-radius: 10px;
        overflow-x: auto;
    }

    .markdown :global(code) {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
            monospace;
    }

    .markdown :global(a) {
        color: #2563eb;
        text-decoration: underline;
    }

    .markdown :global(ul),
    .markdown :global(ol) {
        margin: 0.6em 0;
        padding-left: 1.2em;
    }

    .markdown :global(blockquote) {
        margin: 0.6em 0;
        padding-left: 0.9em;
        border-left: 3px solid #e2e8f0;
        color: #334155;
    }

    .markdown :global(table) {
        border-collapse: collapse;
        margin: 0.8em 0;
        width: 100%;
    }

    .markdown :global(th),
    .markdown :global(td) {
        border: 1px solid #e2e8f0;
        padding: 8px;
        vertical-align: top;
    }

    .markdown :global(th) {
        background: #f8fafc;
        text-align: left;
    }
</style>
