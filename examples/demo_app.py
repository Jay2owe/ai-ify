"""A toy sample table with the ai-ify panel, for manual and browser checks.

    python examples/demo_app.py [--port 8765] [--fake]

Open http://127.0.0.1:8765/ and ask the assistant, e.g. "add sample M04 genotype APP,
then switch to the summary view". ``--fake`` uses the scripted test agent instead of
Claude/Codex (no subscription use).

It also shows the app's own context: the "Explain the summary" button starts the
assistant with its own instructions (a launch), and mentioning "cost" or "price"
adds the app's price note to that message (a prompt rule).

It shows all three levels of control:
  backend actions   samples.add / include / remove / summary (Python, below)
  UI commands       show_view and select_sample (registered by the page)
  control tree      everything else, e.g. the unlabelled "Include all" button;
                    the "Danger zone" is marked data-agent="off"
"""
from __future__ import annotations

import argparse
import sys
import threading

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from aiify import Agent, Launch, Profile, When
from aiify.actions import from_functions


class Samples:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.rows = [{"id": 1, "name": "M01", "genotype": "WT", "included": True},
                     {"id": 2, "name": "M02", "genotype": "APP", "included": True},
                     {"id": 3, "name": "M03", "genotype": "APP", "included": False}]
        self.next_id = 4
        self.changed = 0
        self.wiped = 0

    def state(self) -> dict:
        return {"samples": self.rows}

    def _find(self, sample_id) -> dict:
        for row in self.rows:
            if str(row["id"]) == str(sample_id):
                return row
        raise ValueError(f"no sample with id {sample_id}")

    def _touch(self):
        self.changed += 1


def build(fake: bool = False) -> tuple[FastAPI, Agent, Samples]:
    data = Samples()

    def add_sample(name: str, genotype: str):
        """Add a sample (included by default)."""
        with data.lock:
            row = {"id": data.next_id, "name": name, "genotype": genotype, "included": True}
            data.next_id += 1
            data.rows.append(row)
            data._touch()
            return row

    def include_sample(sample_id: int, included: bool = True):
        """Include or exclude a sample from the summary."""
        with data.lock:
            row = data._find(sample_id)
            row["included"] = bool(included)
            data._touch()
            return row

    def remove_sample(sample_id: int):
        """Delete a sample from the table."""
        with data.lock:
            row = data._find(sample_id)
            data.rows.remove(row)
            data._touch()
            return {"removed": row}

    def summary():
        """Included samples counted by genotype."""
        counts: dict[str, int] = {}
        for row in data.rows:
            if row["included"]:
                counts[row["genotype"]] = counts.get(row["genotype"], 0) + 1
        return counts

    actions = from_functions({"samples.add": add_sample, "samples.include": include_sample,
                              "samples.remove": remove_sample, "samples.summary": summary},
                             destructive=["samples.remove"],
                             mutating=["samples.add", "samples.include"])
    engine_argv = None
    if fake:
        fake_agent = [sys.executable, "-m", "aiify.testing.fake_agent"]
        engine_argv = {"claude": fake_agent, "codex": fake_agent}
    agent = Agent(
        app="aiify-demo",
        actions=actions,
        guide="A table of mouse samples (name, genotype, included). The page has a table view "
              "and a summary view that counts included samples by genotype.",
        profiles={
            "assistant": Profile(provider="claude", label="Assistant"),
            "look-only": Profile(provider="claude", label="Look only", allow=["samples.summary"],
                                 instructions="You may only look and change what is shown; "
                                              "say so if asked to change data."),
        },
        state=data.state,
        rules=[When(lambda s: s.get("view") == "summary",
                    "The summary view is on screen; switch to the table before talking about single samples."),
               When(prompt=["cost", "price"], name="price note",
                    add_instructions=lambda turn: f"Genotyping costs 12 pounds per sample; the table has "
                                                  f"{len(data.rows)} samples, so {12 * len(data.rows)} pounds so far.")],
        launches={"explain-summary": Launch(
            label="Explain the summary", profile="look-only",
            instructions=lambda turn: f"They want the genotype summary explained. It is {summary()}. "
                                      "Show the summary view, then explain it in two sentences.",
            message="Explain the summary.")},
        engine_argv=engine_argv,
    )
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return PAGE

    @app.get("/api/state")
    async def state():
        return {**data.state(), "changed": data.changed, "wiped": data.wiped}

    @app.post("/api/include_all")
    async def include_all():
        with data.lock:
            for row in data.rows:
                row["included"] = True
            data._touch()
        return {"ok": True}

    @app.post("/api/wipe")
    async def wipe():
        with data.lock:
            data.rows.clear()
            data.wiped += 1
            data._touch()
        return {"ok": True}

    @app.post("/api/reset")
    async def reset():
        with data.lock:
            data.reset()
            data._touch()
        return {"ok": True}

    agent.mount(app)
    return app, agent, data


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ai-ify demo</title>
<style>
 body { font: 14px/1.45 system-ui, sans-serif; margin: 24px; max-width: 760px; }
 table { border-collapse: collapse; width: 100%; margin-top: 10px; }
 td, th { text-align: left; padding: 4px 8px; border-bottom: 1px solid #ddd; }
 tr.flash td { background: #fff3bf; transition: background 1s; }
 tr.selected td { outline: 2px solid #3b5bdb; outline-offset: -2px; }
 .bar { display: flex; gap: 8px; align-items: center; }
 .danger { margin-top: 24px; padding: 8px; border: 1px dashed #c92a2a; }
 @media (prefers-color-scheme: dark) { body { background: #161615; color: #ecebe6; } td, th { border-color: #333; } tr.flash td { background: #5c4a00; } }
</style></head>
<body>
<h1>Samples</h1>
<div class="bar">
  <label>View <select id="view" data-agent="view-picker"><option>table</option><option>summary</option></select></label>
  <button id="include-all">Include all</button>
  <button id="reset" data-agent="reset-button">Reset</button>
  <button id="explain" data-aiify-launch="explain-summary">Explain the summary</button>
</div>
<div id="out"></div>
<div class="danger" data-agent="off">Danger zone: <button id="wipe">Delete everything</button></div>
<script>
let last = -1, prev = {}, data = null, view = 'table', selected = null;
async function refresh(force) {
  const s = await (await fetch('/api/state')).json();
  if (s.changed === last && !force) return;
  last = s.changed; data = s; render();
}
function render() {
  document.getElementById('view').value = view;
  const out = document.getElementById('out');
  if (view === 'summary') {
    const by = {};
    for (const x of data.samples) if (x.included) by[x.genotype] = (by[x.genotype] || 0) + 1;
    out.innerHTML = '<p>Included samples by genotype: ' +
      (Object.entries(by).map(([g, n]) => g + ' ' + n).join(', ') || 'none') + '</p>';
  } else {
    const rows = data.samples.map(x => {
      const cls = [prev[x.id] !== JSON.stringify(x) ? 'flash' : '', x.id === selected ? 'selected' : ''].join(' ');
      return `<tr class="${cls}" data-id="${x.id}"><td>${x.id}</td><td>${x.name}</td><td>${x.genotype}</td><td>${x.included ? 'yes' : 'no'}</td></tr>`;
    }).join('');
    out.innerHTML = '<table><tr><th>id</th><th>name</th><th>genotype</th><th>included</th></tr>' + rows + '</table>';
  }
  prev = Object.fromEntries(data.samples.map(x => [x.id, JSON.stringify(x)]));
}
function showView(v) { view = v; render(); }
document.getElementById('view').onchange = e => showView(e.target.value);
document.getElementById('out').onclick = e => { const tr = e.target.closest('tr[data-id]'); if (tr) { selected = +tr.dataset.id; render(); } };
document.getElementById('include-all').onclick = () => fetch('/api/include_all', { method: 'POST' }).then(() => refresh());
document.getElementById('wipe').onclick = () => fetch('/api/wipe', { method: 'POST' }).then(() => refresh());
document.getElementById('reset').onclick = () => fetch('/api/reset', { method: 'POST' }).then(() => { view = 'table'; selected = null; refresh(true); });
setInterval(refresh, 800); refresh();
</script>
<script src="/aiify/panel.js" defer></script>
<script>
// level 2: named UI commands, and what the page reports as on screen
// (after DOMContentLoaded, so the deferred panel.js has run)
document.addEventListener('DOMContentLoaded', () => {
window.aiify.registerTool({
  name: 'show_view', description: 'Switch the page between the sample table and the genotype summary',
  inputSchema: { type: 'object', properties: { view: { enum: ['table', 'summary'] } }, required: ['view'] },
  execute: async ({ view: v }) => { showView(v); return { view: v }; },
});
window.aiify.registerTool({
  name: 'select_sample', description: 'Select (outline) one sample row in the table',
  inputSchema: { type: 'object', properties: { id: { type: 'integer' } }, required: ['id'] },
  execute: async ({ id }) => { selected = Number(id); showView('table'); return { selected }; },
});
window.aiify.setState(() => ({ view, selected }));
});
</script>
</body></html>
"""


def main(argv=None) -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--fake", action="store_true", help="use the scripted test agent")
    a = ap.parse_args(argv)
    app, agent, _ = build(fake=a.fake)
    print(f"ai-ify demo: http://127.0.0.1:{a.port}/   (agent work folder {agent.work_folder()})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
