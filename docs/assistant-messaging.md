# Assistant messaging implementation contract

Requested: let the research assistant's conversations communicate through their
shared server, with the reusable implementation in ai-ify.

ai-ify owns MessageHub/Mailbox, sender-bound control commands, durable messages,
reply threads, source/context references, acknowledgements, next-turn context and
the shared panel. The research assistant supplies one local hub per workspace,
conversation identities, role labels and frozen context references. It does not
copy the messaging implementation or replace its existing job runner.

Receiving mail waits for the next user-led turn. Automatic replies remain an
open product choice, not an implicitly enabled worker. A future opt-in responder
would need a persisted turn budget, explicit permitted contacts, failure/stop
behavior and its own tests. Existing workflow execution does not resume or notify
planning conversations.

Budgets: opening a chat makes no inbox/history scan; registering its mailbox is
one local transaction. Opening Messages reads bounded history pages. Delivery
does not invoke a provider or validate the research registry. Tests cover absent
store reads, isolation, retries, concurrent writes, source attribution, failed
turn recovery, actual HTTP/control calls and the shared browser controls.

Feedback: 2026-10-06, user: "can we allow them to communicate via the server";
"this is something that should probably be implemented into ai-ify as well as
how you have configured the server".

## Verification

- Full ai-ify suite using the app's Python installation: 184 passed.
- Core, browser and guide checks: 14 passed. Browser tests use real HTTP and
  WebSocket traffic with synthetic conversations, light/dark themes and a
  300-pixel panel; no provider or model turn runs on delivery.
- Research assistant integration, existing embedded panel, concurrent host and
  Windows atomic-write checks: 19 passed after fixing the composer selector and
  routing snapshot saves through the existing Windows collision retry helper.
- Full research assistant suite: 1,081 passed, one skipped, one obsolete
  first-textarea selector failed. The corrected composer selector and Windows
  collision recovery passed the 19 focused follow-up checks above; that full
  suite was not repeated.
- Synthetic new-chat benchmark (244 records): cold host to editable composer
  2.748 seconds; reused host 0.357 seconds, zero redundant context requests.
  These are synthetic timings, not a claim about live evidence-read latency.
- The wheel includes the mailbox, guide and shared panel; an isolated import
  from the built wheel exchanges a synthetic message successfully.

The package configuration is opt-in. The research assistant enables it on its
existing shared host. No separate messaging web server or automatic responder
is introduced.
