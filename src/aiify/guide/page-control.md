## The panel

Add one tag to the page after `agent.mount(app)`:

```html
<script src="/aiify/panel.js" defer></script>
```

Optional attributes: `data-open="true"` (start open), `data-theme="dark|light"`,
`data-title="..."`, `data-bridge="false"` (chat only; the agent cannot act on the page).
The panel lives in a shadow root, so the page's styles and the panel's do not mix.
A page with a Content Security Policy needs `connect-src 'self'` (which covers the
websocket on the same host) and must allow the script from its own origin.

## Named UI commands

Register page functions the agent can call by name (`aiify ui do NAME key=value`):

```html
<script>
document.addEventListener('DOMContentLoaded', () => {
  window.aiify.registerTool({
    name: 'show_view',
    description: 'Switch between the table and the summary',
    inputSchema: {type: 'object', properties: {view: {enum: ['table', 'summary']}}, required: ['view']},
    execute: async ({view}) => { showView(view); return {view}; },
  });
  window.aiify.setState(() => ({view: currentView, selected: selectedId}));
});
</script>
```

Run this after `panel.js` (it is deferred, so wait for `DOMContentLoaded` or place
the code in a later deferred file). `setState` reports what is on screen; it is
merged into the state sent with each message and returned by `aiify state`.

## The control tree

`aiify ui tree` lists visible controls with refs. Make important ones stable:

```html
<button data-agent="export-bundle">Export</button>   <!-- ref "export-bundle" never changes -->
<div data-agent="off">...</div>                       <!-- hidden from the agent entirely -->
```

Numbered refs (`e12`) go stale after the page changes; the reply then says
`stale_ref` and the agent lists the tree again. Prefer, in order: a backend action,
a named UI command, a named control, then a numbered one.