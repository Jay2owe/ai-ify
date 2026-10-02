# Deploy contract

<!-- deploy-required-channels: ["pypi", "github-release"] -->

What a release of ai-ify must deliver, and how each part is checked. The steps
are in [RELEASING.md](RELEASING.md).

## Identity

- One version in `pyproject.toml` `version` and `src/aiify/__init__.py`
  `__version__`, with a matching `## X.Y.Z` section in `CHANGELOG.md`.
- One clean source commit on `main`, pushed, tagged `vX.Y.Z`. The tag starts the
  `release` workflow; nothing is uploaded by hand.
- `README_AI.md` and `aiify_context.json` (root and package copies) regenerated for
  that version.

## Artifacts

Built once by the `release` workflow from the tagged commit, and the same bytes go
to every channel:

| Artifact | Surface |
|---|---|
| `ai_ify-X.Y.Z-py3-none-any.whl` | the installed package (`pip install ai-ify`) |
| `ai_ify-X.Y.Z.tar.gz` | the source archive |

## Gates before tagging

1. The full test suite passes locally, browser tests included.
2. A local `python -m build` and `twine check --strict` pass (outside the checkout).

## Gates in the workflow

The tag matches both version fields; the non-browser tests pass; build; `twine
check --strict`; the wheel installs into a clean environment and reads its guide.

## Channels, in order

| Channel | Destination | Published by |
|---|---|---|
| `pypi` | https://pypi.org/project/ai-ify/ | workflow job `pypi`, trusted publishing (GitHub environment `pypi`, no stored token) |
| `github-release` | https://github.com/Jay2owe/ai-ify/releases | workflow job `github-release`, notes from the changelog section |

## Verification for every channel

- `pypi`: the version's files exist on PyPI, their SHA-256 digests are recorded,
  and a clean environment installs `ai-ify[web]==X.Y.Z` and runs the representative
  workflow below.
- `github-release`: the release for the tag holds the wheel and the source archive,
  with the same SHA-256 hashes as PyPI's; the release's wheel runs the same workflow.

Representative workflow: start an `Agent` on the scripted test agent
(`aiify.testing.fake_agent`), send one message and receive the reply, answer an
`aiify how` question, and read a guide topic, all from the installed package
outside the source checkout.

## Not part of a release

Circadian Workbench, which embeds ai-ify, releases on its own and only raises its
minimum ai-ify version. A version on PyPI is never replaced: a fix is a new version.
