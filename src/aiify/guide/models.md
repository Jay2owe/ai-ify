## Which models can be used

Think of the model picker as the menu supplied by your signed-in provider.
ai-ify supplies the application controls; the provider supplies the models.

The built-in providers are **Claude** (`provider="claude"`) and **Codex**
(`provider="codex"`). Claude models run through the Claude adapter, and OpenAI
models run through the Codex adapter. Both use the subscription sign-in exposed
by their adapter. Gemini and arbitrary API model endpoints are not built-in
provider choices.

Available models depend on your account, organization restrictions and installed
adapter version. Claude families such as Sonnet, Opus, Haiku and Fable, and OpenAI
GPT models, can be selected **when the running adapter exposes them**. ai-ify does
not maintain a separate fixed model list or make an unavailable model accessible.
See [Claude model configuration](https://code.claude.com/docs/en/model-config)
and [OpenAI model selection](https://learn.chatgpt.com/docs/models) for the
providers' current guidance.

## Choose a model in an application

1. Choose a provider or an application profile and complete sign-in.
2. Once the agent is ready, choose a value from the panel's **Model** picker.
   Model, effort and permission choices come from the running adapter.
3. Send the next message. A model change applies to that message; switching
   provider starts a new chat. Applications can lock pickers in a profile or launch.

The provider's CLI model name, an API model ID and the adapter's model-choice value
may differ. Use the value offered by this application's picker. An unavailable
choice is reported as an error; check the current selection before retrying.

## Configure the application default

```python
from aiify import Agent, Profile

agent = Agent("myapp", profiles={
    "claude": Profile(provider="claude", model=None, effort=None),
    "codex": Profile(provider="codex", model=None, effort=None),
})
```

`model=None` and `effort=None` retain the adapter's defaults. They do not guarantee
the cheapest model. To pin a model, replace `None` with an exact choice reported
by your running adapter. After the agent is ready, code can inspect
`agent.session.options()["model"]`, containing the selected `value` and available
`choices`, and use `await agent.configure(model=choice)` to select a supported value.

The low-token helper defaults concern guidance, maps, prepared shortcuts and
optional web routes. They do not select or rank models by price.

## What has actually been tested

**Claude Sonnet 5.5**, exact observed ID `claude-sonnet-5-5`, passed six synthetic
application tasks on 6 October 2026: PyFLASH, AI Research Assistant, PyMicroglia,
Auto-Organotypic, Circadian Workbench and Protocol Drawing Studio. Tests used
Claude's command-line interface and restricted controls calling the applications'
native assistant action adapters. They did not exercise embedded Agent Client
Protocol model negotiation, graphical interaction or personal-skill routing.

This validates that task solver with those native controls. It does not establish
that every installed Claude adapter advertises the same ID in its Model picker.
Other Claude and Codex choices are supported through their respective adapters,
but this six-application evaluation did not test them or rank their quality or cost.
The model's official ID is documented in
[Anthropic's Sonnet 5.5 specifications](https://platform.claude.com/docs/en/models/sonnet-5-5/overview).

Read the packaged `model-tests` topic for tasks, independently checked results,
token usage and the enforced privacy boundary. That test excluded user context
with fresh profiles and restricted tools; ordinary application permissions depend
on the host application and provider setup.

The [machine-readable test summary](model-tests.json) ships alongside the guide.
It can also be read with Python:

```python
from importlib.resources import files
import json
summary = json.loads(files("aiify").joinpath("guide", "model-tests.json").read_text(encoding="utf-8"))
```
