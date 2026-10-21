## Isolated Sonnet 5.5 application checks — 6 October 2026

All six synthetic tasks passed through the installed applications' native
assistant adapters and prepared workspace shortcuts. Recorded initialization and
model usage identify `claude-sonnet-5-5` for every test; no model fallback was used.

Model reasoning ran through Claude's command-line interface. The tests exercised
native application action adapters, not embedded Agent Client Protocol model
negotiation. Sonnet 5.5 must still be offered by the running adapter to select it
through an embedded Model picker; read the `models` topic for configuration.

These are functional checks of one task per application. They do not compare
helper configurations, establish which model is cheapest, or replace application
regression suites. Sonnet 5.5 was selected for these tests only.

## Tasks and independent verification

| Application | Native action exercised | Independently verified result | Processed tokens in successful run |
| --- | --- | --- | ---: |
| PyFLASH | `PyFLASH.stats.bonferroni_correction` | Raw p-value 0.03 corrected for three tests gives 0.09. The recorded standalone script also reproduced 0.09. | 29,965 |
| AI Research Assistant | `projects.add`, `tasks.add`, `tasks.get` | Synthetic project and held task created and read back; no worker process, conversation, turns or runs started. | 19,122 |
| PyMicroglia | `measure`, followed by native job readback | Both morphology and intensity completed: 16 cell-frame rows, area 9 square pixels in every row, expected intensities of 100 and 200 for the two cells. | 47,881 |
| Auto-Organotypic | `inspect`, `plan` | Four frames, two channels, 7 × 9 pixels and a 1,800-second acquisition interval. Index-only plan resolved; stages did not execute. | 14,708 |
| Circadian Workbench | `estimate_period` | Lomb–Scargle recovered 24.000000000000085 hours from the synthetic 24-hour trace. | 6,320 |
| Protocol Drawing Studio | `studio.run` → `vectors.describe` | Identified the rectangle and text objects and “Synthetic test” label. Source drawing bytes remained unchanged. | 6,607 |

Source-file fingerprints matched their pre-run values. The measurement tables
were opened and checked by the independent verifier, rather than relying on the
model's description. Every successful agent run called the prepared workspace
overview and native action contracts before executing its task.

All nine installed assistant roles passed the default-switch check: local
guidance, shipped app map and prepared shortcuts enabled; additional web routes
disabled. Protocol Drawing Studio has four roles; each was checked. Only its
drawing role received a live model task in this evaluation.

## How the agents solved the tasks

Each fresh Claude process received a synthetic task and three test controls:
workspace overview, allowed action contracts and native action execution.
PyMicroglia also received a control for reading only jobs created by that test.
The controls called the real application adapters; scientific calculations and
recording were performed by the installed applications.

The agents did not interact with the graphical interface or load a personal
Circadian, PyFLASH or other skill. The test controller prebound synthetic input,
output and state locations and restricted each application to its declared test
actions. Research routing, scoring and worker launch were disabled, and its task
was forced to remain held. Circadian returned a bounded scientific summary while
the full native reply remained in the local tool-call receipt.

## Exclusion of user context

The restriction was enforced through the model's available tools and the test
controller:

- Fresh profile and Claude configuration directory for each application, outside
  the user's project directories. Ancestors contained no `CLAUDE.md` or `AGENTS.md`.
- Saved settings, auto-memory, personal skills, slash commands, Chrome integration
  and session persistence disabled. No user instructions, conversations, memories
  or personal plugin configuration were copied.
- Claude restricted mode, no built-in tools, strict configuration of the sole
  test tool server, and permissions limited to those test controls.
- Initialization inspected during execution: exact requested model, empty skill
  list and only test-control tool names. Two CLI built-in plugins were reported;
  no personal plugins were loaded, and no inherited instruction files existed.
- No model file-reading, shell or browser tools. Unknown actions and external
  file-path parameters were rejected by executable guard checks. Inputs and
  outputs were fixed by the controller, rather than chosen by the model.
- Existing subscription authentication supplied only to the Claude process;
  the native application server received neither the OAuth token nor user
  authentication configuration.

This is a model-tool boundary with fixed application inputs, not an operating
system container or separate Windows account. Trusted installed application code
still ran under the existing Windows account. These restrictions describe this
test harness, not the ordinary assistants' default file permissions.

## Usage and retained attempts

The six successful runs reported **124,603 processed tokens**: 50 ordinary input,
44,294 cache-creation input, 74,402 cache-read input and 5,857 output tokens.
Processed tokens include inputs reused across successive tool calls, so this is
not the number of unique words in the task descriptions.

Including completed unsuccessful task attempts and reported messages from two
interrupted harness attempts, recorded task usage is **160,921 tokens**. This
excludes the separate authentication/isolation probe and any unreported in-flight
usage from interrupted calls. The completed task attempts reported a combined
**$0.3085462 list-price equivalent**; this is a CLI accounting estimate, not an
additional charge to the user's subscription.

The retained attempts document two harness adjustments: native tool service
startup moved outside Claude's subprocess tree, and Windows Store Python's
executable was explicitly bound because the fresh profile otherwise rewrote its
alias to a nonexistent path. An initial Circadian reply exceeded Claude's tool
display limit; the agent correctly declined to guess or read files, and passed
after the controller returned the native result's compact summary. No private
context or general file tool was enabled to resolve these issues.

## Evidence and limits

[Machine-readable verification and usage](model-tests.json)
records each application's native actions, observed tool names, helper switches
and usage. Full synthetic fixtures, original model streams, native tool replies,
guard receipts and retained attempts remain in
`C:/Temp/ai-ify-sonnet-55-isolated/<application>/`. Harness sources and the
independent verifier remain under
`%LOCALAPPDATA%/ai-ify/sonnet-5.5-isolated/` and are linked in the evaluator's existing local helper-evaluation record.
Original raw logs and local harness sources are not part of the public package;
the packaged JSON is the verification summary.

These checks do not exercise research workers, complete imaging pipelines,
drawing mutation, graphical control, personal-skill routing, or every model and
permission combination. They establish that the declared synthetic tasks work
through native adapters with user context excluded under the stated boundary.
