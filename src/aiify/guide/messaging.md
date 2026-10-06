## Connect assistants without merging their conversations

One `MessageHub` is an explicitly chosen messaging workspace. Attach its
mailboxes to agents that should be able to contact each other:

```python
from aiify import Agent, MessageHub

hub = MessageHub("assistant-messages.sqlite3")
analysis = Agent("analysis", messaging=hub.mailbox("analysis", label="Analysis assistant"))
writing = Agent("writing", messaging=hub.mailbox("writing", label="Writing assistant"))
# Mount/start these agents using the normal app lifecycle.
# Once started:
analysis.messaging.send("writing", "Use the accepted result", references=[{"record_id": "finding-12"}])
writing.messaging.inbox()
```

The same shared panel displays **Messages** when a mailbox is attached. Choose
an active recipient, send a message, inspect Inbox or History, reply to a received
message, or acknowledge it. Messages do not switch focus or start a model turn.
Incoming messages become attributed context on the recipient's next user-led
turn. The original frozen conversation context is not rewritten.

Automatic responses and assistant-to-assistant loops are not implemented.
Receiving a message is not an approval to execute it. Normal action permissions
and the user's instructions still apply. Messages never mark research accepted.

## Code and agent commands

The existing authenticated control port binds the sender to its own mailbox.
Agents use the same commands through the normal `aiify --app NAME` command:

```text
messages.peers
messages.inbox limit=20
messages.history after=0 limit=20
messages.send recipient=writing text="Explain the accepted method" request_key=method-question-1
messages.reply message_id=msg-... text="The exact method is linked here"
messages.ack message_ids=["msg-..."]
```

`describe` lists the operations, parameters and read/write classifications.
`messages.send` and `messages.reply` accept up to twenty JSON `references` and
an optional `request_key` for retry-safe delivery. Retrying the same sender/key
with different contents is rejected. The sender cannot be changed by a command
parameter. A reply must stay between the original participants. Each history
page returns `next_after` and `has_more`; messages retain their global sequence.

For headless use, call `mailbox.activate()` to register an identity and
`mailbox.deactivate()` when its owner stops. A hub has no mandatory web framework
or background process. An app can notify an open panel through its existing
server; delivery still persists if no panel is open. External callers can use
the already running agent's authenticated control port without sharing its full
conversation history.

## Persistence and audit boundaries

Use a local SQLite file. Constructors and reads of an absent store create no
files. Messages, exact reference values, sender/recipient context metadata,
timestamps, thread links and acknowledgement events persist across app restarts.
There is no delete or edit-message operation. This is an application audit trail,
not a tamper-proof archive against a person who can edit the database file.

Stopping an agent marks its mailbox disconnected within that hub but retains its
history. Code can leave mail for a previously registered offline identity; it
becomes available when that same identity reconnects. The panel disables offline
recipients when composing new mail. A new identity has a separate inbox.

Inbox/history reads do not acknowledge messages. A successful completed model
turn records which messages were included; failed/authentication/cancelled turns
leave them pending. Each turn includes at most five incoming messages with a
bounded text budget and an explicit pointer when more remain. Large evidence
stays in its owning package and is linked, not copied into all conversations.

Create separate hubs for unrelated workspaces. Every mailbox in one hub can
address the other registered mailboxes. OS access to the local store remains the
host application's authority boundary; this does not grant access to arbitrary
other apps or computers. Online callbacks operate within one hub instance;
another process can inspect persisted mail, but does not gain live notifications
unless it uses the owning agent's control port.
