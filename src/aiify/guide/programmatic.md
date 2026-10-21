# Use the assistant from application code

Choose visible conversation methods when a person should see the exchange.
Choose `ask` when app code needs a returned answer without changing their chat.

## Start, stop and observe status

`agent.mount(app)` owns lifecycle for a web app; do not also start a background
thread for that same instance. Without a web server, use `await agent.start()`
and `await agent.stop()` on your event loop, or pair `start_background()` with
`stop_background()` in a desktop app. Stop in a `finally` block on failure.
`prewarm=True` starts the adapter during startup; `agent.warm()` requests warm-up
after starting. No model is needed to read the package's context module.

`agent.info()` returns readiness, busy status, provider settings/options,
features and pending work for your UI. `agent.current_state()` returns merged
Python/page facts. `agent.helpers()` and `agent.helper_availability()` distinguish
enabled helpers from those the host can offer.

## Sending and receiving a visible reply

This complete example uses the fake agent in a temporary working folder:

```python
import asyncio
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from aiify import Agent

async def main():
    with TemporaryDirectory() as folder:
        os.environ["AIIFY_HOME"] = str(Path(folder) / "home")
        os.environ["FAKE_ACP_STORE"] = str(Path(folder) / "sessions.json")
        agent = Agent(
            "events-example", cwd=Path(folder) / "work",
            engine_argv={"claude": [sys.executable, "-m", "aiify.testing.fake_agent"]},
            limit_check_every=None,
        )
        await agent.start()
        events = agent.subscribe()
        try:
            summary = await asyncio.wait_for(agent.send("hi"), timeout=30)
            assert summary["stop"] == "end_turn", summary
            parts = []
            while True:
                event = await asyncio.wait_for(events.get(), timeout=30)
                if event["kind"] == "text":
                    parts.append(event["text"])
                if event["kind"] == "done":
                    assert event["stop"] == "end_turn", event
                    break
            assert "".join(parts) == "hello from fake"
            print("".join(parts))
        finally:
            agent.unsubscribe(events)
            await agent.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

`await send(text, echo=True)` waits for the turn and returns its completion
summary, including `stop`, rather than the answer text. A call during an active
reply raises `AiifyError` with code `invalid`. Check the stop reason. `send_soon`
schedules sending without waiting for completion; use the queue when requests
must execute in order. Events include user messages, text chunks, tool updates,
permission requests, info, errors and a final `done`. Unsubscribe when your UI
closes; always put a timeout on waits. A listener that falls 10,000 events behind
receives one `resync` event and no more; subscribe again and read `agent.info()`.

`await agent.cancel(unqueue=True)` cancels the active reply and returns queued
text to the UI rather than sending it later. With the default `unqueue=False`,
queued work remains eligible to run. `await agent.new_chat()` cancels the active
reply and resets visible conversation/launch context. Persistent notes survive.
For a custom UI, `agent.answer(request_id, option)` resolves a permission request;
choose an actual option from that request only after the person's decision.
A permission request nobody answers is refused after 10 minutes and the reply goes on.

## Configure an existing instance

These fragments assume `agent` has been started:

```python
await agent.configure(profile="viewer")  # key from your profiles mapping
await agent.configure(provider="codex")  # changes provider and starts a new chat
await agent.configure(model=choice)       # choice from the running adapter
agent.set_helpers(how=True, routes=False)
await agent.new_chat()                    # refresh helper orientation
```

Changing profile or provider starts a new chat; model, effort and mode are
applied to the active adapter settings. For changes submitted by your own
person-facing settings UI, use `by_person=True` so configured picker locks and
limits apply. Host calls without it may override those restrictions.

## Get structured answers without changing the chat

`await agent.ask(prompt, schema=None, provider=None, model=None, effort=None,
context=True, timeout=300)` creates and closes a separate conversation. It
returns text without a schema, a dict/value for JSON Schema, or a validated
Pydantic instance for a Pydantic model class. It includes guide and state when
`context=True`; it is not a copy of the visible conversation and its whole rule
history. Use `context=False` for a question that should receive only your prompt
and schema. Ask checks the structured reply, retries once on invalid output,
then raises `AiifyError` if it remains invalid. Approval-requiring tools are
refused in this hidden conversation.

The following fragment runs with the fake-configured agent above:

```python
answer = await agent.ask(
    'reply-json {"count": 3}', context=False,
    schema={"type": "object", "required": ["count"],
            "properties": {"count": {"type": "integer"}}},
)
assert answer == {"count": 3}
```

When the optional `jsonschema` library is installed, JSON Schema dicts are
validated with it. Without that library, checks cover the top-level type and
required object fields only, not all nested constraints. Install `jsonschema`
or use a Pydantic model when your output
needs stronger type or domain validation, and check scientific meaning in your
host code. `timeout` bounds individual startup/send waits, not necessarily the
total time across startup and retries. Handle `AiifyError` and show recovery;
`signed_out` means complete sign-in through the panel first.

## Queue, schedule, attach and launch from code

These fragments use a started `agent`; pending IDs come from returned dictionaries:

```python
from datetime import timedelta

pending = agent.schedule_message("Summarise the latest notes", timedelta(minutes=5))
agent.remove_pending(pending["id"])
attached = agent.attach("selection.txt", text="Only notes 1 and 2 are selected.")
agent.detach(attached["id"])
agent.queue_message("Read the notes after the active reply finishes")
```

An idle queue sends immediately. Scheduled `at` accepts a datetime (naive means
local time), timedelta, epoch seconds or ISO timestamp. Prefer aware datetimes
for explicit time zones. Shutdown loses queued/scheduled messages. Attachments
are held for the next visible message and saved copies remain on disk; detaching
removes them from the pending list. `await agent.launch(name, data, attach=...)`
uses an existing named `Launch`, not arbitrary instructions supplied as a name.

In a desktop thread with `start_background`, submit async work to `agent.loop`
using `asyncio.run_coroutine_threadsafe`. Calling `.result()` blocks that thread;
use completion callbacks or your GUI's task system to keep its UI responsive.
`console_status()` reports whether Console is available; `open_console()` opens
the provider's resumed conversation. Read `console-and-limits` for account and
usage behavior, and `messaging` for mail operations that do not run a model.
