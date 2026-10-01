## Adding the panel to the page

Either let ai-ify add it to every HTML page the app serves:

```python
agent.mount(app, inject=True)                          # every page
agent.mount(app, inject=lambda path: path == "/")      # only the pages you choose
```

or put the tag in the page yourself, before `</body>`:

```html
<script src="/aiify/panel.js" defer></script>
```

`aiify.web.panel_tag(**options)` returns that tag with options filled in, for apps
that build their pages in Python. `inject` skips pages that already load
`panel.js`, non-HTML responses, compressed responses and FastAPI's `/docs`.

## Where it sits

| Layout | What the person sees |
|---|---|
| `overlay` (default) | A round button bottom-right; the panel slides over the right edge of the app |
| `dock` | The app's page shrinks to make room, so nothing is covered |
| `float` | A separate window over the app: drag it by its title bar, resize it from its bottom-right corner |
| `inline` | The panel fills an element of the app's choosing (a tab, a side column), always open |

The person can switch between overlay, dock and float with the "view" picker in the
panel, and set "opacity": lower values thin the panel's background (never its text)
so the app shows through while both are in view. Both choices, and the window's
place and size, are remembered in that browser.

## Options

Set them as `panel={...}` with `inject=True`, as `panel_tag(...)` arguments, or as
`data-` attributes on the script tag:

| Option | Values | Effect |
|---|---|---|
| `layout` | `overlay`, `dock`, `float`, `inline` | Where the panel starts (the person's own choice wins once made) |
| `target` | a CSS selector, e.g. `#ai` | The element an `inline` panel fills |
| `opacity` | `30` to `100` | How solid the background starts |
| `launcher` | `none` | No round button; the app opens the panel itself |
| `accent` | a CSS colour | Buttons, links and bars in the app's colour |
| `font` | `system`, or a CSS font list | The panel uses the page's font unless told otherwise |
| `theme` | `light`, `dark` | Force a theme (default follows the system) |
| `title` | text | Panel title (default "Assistant · app name") |
| `open` | `true` | Start open |

```python
agent.mount(app, inject=True, panel={"layout": "float", "opacity": 85, "accent": "#2b6cb0"})
```

With `launcher: none`, open the panel from the app's own button:

```html
<button onclick="aiify.open()">Assistant</button>
```

`aiify.open()`, `aiify.close()`, `aiify.toggle()`, `aiify.setLayout("dock")` and
`aiify.setOpacity(70)` work from any script on the page.

Success check: open the page; the panel appears as chosen, and after picking
another view and reloading, the panel comes back the same way.
