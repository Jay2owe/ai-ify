## Measure how well the agent does your app's tasks

`python -m aiify.evaluate` runs a list of tasks through the embedded agent, each in a
new chat, and checks every result. It repeats them with each discovery helper (the
app's routes as actions, the `how` search, the app map) switched off in turn, so
you can see what each one adds for your app.

```bash
python -m aiify.evaluate tasks.py --provider codex --out eval/round1
python -m aiify.evaluate tasks.py --out eval/round1 --resume          # carry on after a stop
python -m aiify.evaluate tasks.py --mixes all,no-map --only export-pdf --repeats 3
```

## The tasks file

```python
from aiify.evaluate import Task, says, ran

APP = "myapp.main:app"          # or a function in this file that returns the app
ENV = {"MYAPP_AI": "1"}         # set before the app is imported
PAGE = "/"                      # opened in a hidden browser; None for backend only

def prepare(out_dir):           # once, before the app starts: point it at test data
    os.environ["MYAPP_DATA"] = str(out_dir / "data")

def seed(ctx):                  # once, after the page is open: load demo data
    ctx.data["sample_id"] = ...

TASKS = [
    Task("export-pdf", "How do I export the summary as a PDF?", check=says("Publication")),
    Task("add-sample", "Add sample M04 with genotype APP.",
         check=lambda run: any(s["name"] == "M04" for s in run.state.get("samples", []))),
]
```

A check gets the run: `run.reply`, `run.state` (the app state afterwards, including
what the page reports), `run.commands` (what the agent ran, with status),
`run.approvals` and `run.data` (from `seed`). It returns `True`/`False` or
`(passed, note)`. `says`, `says_any`, `ran` and `all_of` cover the common cases.
Prefer checks the agent cannot satisfy by guessing: a computed number, the page's
state, or whether the app's own tool was used.

A task's `setup(ctx)` runs before each chat; the default reloads the page so every
chat starts from a fresh screen. `ctx.page` is a Playwright page and `ctx.reload()`
waits for the panel to reconnect.

## Helper mixes

| Mix | Routes | how | App map |
|---|---|---|---|
| all | on | on | on |
| none | off | off | off |
| no-routes | off | on | on |
| no-how | on | off | on |
| no-map | on | on | off |

Leaving one helper out at a time shows what each adds without running every
combination. Your own actions, page commands, guide and instructions are always on.
In an app, `Agent(how=False)`, `routes=False` and `app_map=None` switch the same
helpers off for good; `agent.set_helpers(...)` does it for the next chat.

## Cost and results

Every chat runs on the developer's own subscription. `--stop-at 95` (the default)
ends the round when the provider's usage reaches 95%; `--resume` continues later.
Approvals are answered yes (`--approve no` refuses them) and counted. Results go to
`runs.jsonl`, one line per chat as it finishes, and `report.md`: pass rate per mix,
what each helper adds, each task by mix, and every failure with its reason.

Agents vary from chat to chat: one run per task and mix shows a direction; three
runs give numbers worth comparing.

Success check: a round with `--mixes all` writes `report.md` whose "Each task" table
lists every task, and `runs.jsonl` has one line per chat.
