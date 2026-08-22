# Widget Architecture

This document explains how the embeddable chat widget is built, how it connects
to the agent backend, and what should happen next.

## Goal

The product goal is:

```text
Any host app
  Angular / Vue / React / plain HTML
    embeds <agent-chat>
      custom element wrapper
        Shadow DOM boundary
          React chat UI
            shadcn AI Elements-style primitives
              conversation API
                ConversationService
                  agent engine
```

The host application should not need to install React or know anything about
the agent runtime. It only loads `widget.js` and places `<agent-chat>` on the
page.

## Current Implementation

### Public Integration

The public contract is still a framework-agnostic Web Component:

```html
<script type="module" src="/widget.js"></script>
<agent-chat
  title="Support"
  color="#2563eb"
  greeting="Hi! How can I help?"
  mode="floating">
</agent-chat>
```

Attributes configure the widget. Host pages can listen for safe metadata through
the `agent-chat:answer` DOM event.

### Internal UI

Inside the custom element, the widget creates a Shadow DOM root and mounts a
React tree. The React layer uses local AI chat components under:

```text
src/agent_manager/api/static/widget/react/
```

The important components are:

- `Conversation` / `ConversationContent`
- `Message` / `MessageContent` / `MessageResponse`
- `PromptInput` / `PromptInputTextarea` / `PromptInputSubmit`
- `Tool` / `ToolHeader` / `ToolContent` / `ToolOutput`

These are adapted for widget usage from the shadcn AI Elements pattern. They use
real UI/runtime dependencies where useful:

- `streamdown` for markdown-like assistant responses.
- `use-stick-to-bottom` for chat auto-scroll behavior.
- `lucide-react` for icons.

They are not imported from a `shadcn` npm package because shadcn components are
source files copied into a project, not a runtime component package.

### Styling

The widget styles are injected into the Shadow DOM from:

```text
src/agent_manager/api/static/widget/styles/styles.ts
```

This keeps widget styling isolated from Angular, Vue, React, or any other host
application CSS. The host page does not need Tailwind.

## Backend Contract

The widget talks to the agent manager API:

```text
POST /conversations
GET  /conversations/{id}/messages
POST /conversations/{id}/messages
POST /conversations/{id}/messages/stream
POST /conversations/{id}/runs/{run_id}/approvals/{approval_id}/decision
POST /conversations/{id}/runs/{run_id}/approvals/{approval_id}/decision/stream
POST /conversations/{id}/runs/{run_id}/approvals/{approval_id}/cancel
```

The non-streaming endpoint remains available to explicit API clients. The widget
does not automatically replay a failed streaming mutation through it, because a
network failure cannot prove the original request made no state change. The
streaming endpoint returns Server-Sent Events over a POST request, so the browser
client uses `fetch()` and `ReadableStream` instead of `EventSource`.

Streaming events include:

- `turn_started` — the persisted user-message and run identities for this turn.
- `answer_delta` — append assistant text as it arrives.
- `route` — update the visited agent/sub-agent path.
- `tool_started`, `tool_succeeded`, `tool_failed` — update tool activity.
- `final` — authoritative final answer and metadata.
- `pending_approval` — sanitized tool request, provider/server identity, masked
  arguments, and the identifiers required to resume it.
- `resume_started` — the existing run has left suspension and is executing
  again under the same `run_id`.
- `error` — stream failure.

While a turn runs, the composer remains editable but cannot submit another
turn; its primary action becomes **Stop**. Stopping aborts the response-owned
stream and therefore cancels and awaits the graph producer. The persisted user
message remains visible with run status `cancelled`, while the widget projects
that lifecycle state as *Generation stopped*. That label is not an assistant
message and never enters model context.

Previous user messages expose **Edit**. Submitting an edit sends
`edit_message_id`; the manager appends a new user message at that message's
parent and selects the new immutable branch. Original messages and downstream
runs are retained rather than updated or deleted.

A user may also explicitly edit the prompt of a pending-approval run. Submitting
that edit creates a new branch and run; it does not decide, cancel, or mutate the
old approval. A later resume of the old approval stays attached to its inactive
original branch.

When a stream pauses for approval, the assistant entry renders three decisions:
**Approve** (`allow_once`), **Deny** (`deny`), and **Approve for this session**
(`allow_for_session`), plus a distinct **Cancel run** lifecycle action. Decision
controls are disabled while a decision is in flight, but Cancel remains
available: the backend atomically lets either cancellation or the approval claim
win. A successful cancellation replaces the card with *Generation stopped* and
unblocks the composer. Once resume starts, both new turns and approval resumes
use an engine-owned graph task. The textarea and Edit stay available for draft
preparation, submit stays blocked, and the primary action becomes **Stop**. Stop
aborts the resume stream and therefore cancels the actual graph task and the
same run. The completed resume replaces the approval card in place rather than
starting a second conversation turn. Decision retries are
idempotent: a completed graph result is recovered from its checkpoint and the
assistant message is appended once by its stable run-derived id.

## Agent Connection Behavior

The widget stores the current `conversation_id` in `localStorage` per endpoint.
If the backend no longer knows that conversation, the widget treats the stored
id as stale:

1. Clear the stale id from `localStorage`.
2. Create a new conversation.
3. Retry the message.

This prevents common local-development failures after restarting the backend.

## What Is Verified

Automated coverage verifies:

- The widget renders and remains accessible in floating and inline modes.
- Messages are sent through the conversation API.
- Streaming SSE responses update the assistant message.
- All three approval actions resume the existing run without duplicate requests.
- Pending approvals can be terminally cancelled, including during an in-flight
  decision, without executing the tool when cancellation wins.
- Active approval resumes expose editable drafts and Stop while preventing a
  concurrent submission; stopping cancels the graph and preserves no partial
  assistant message.
- Session approval suppresses the next prompt for the same scoped tool.
- Stale conversation ids are recovered automatically.
- Browser demos still work through Playwright.
- The backend stream endpoint emits SSE frames.
- Cancellation remains visible after history reload without persisting fake
  assistant content.
- Editing selects a new branch and excludes the original descendants from model
  context.

Manual verification with the real demo config verifies:

```text
widget -> conversation API -> ConversationService -> engine -> sub-agent
```

For example, asking:

```text
what are your support hours?
```

routes through:

```text
concierge_router -> concierge_router/hours_agent
```

## Next Step

The next product step is to make the streamed agent activity richer in the UI:

1. Show routing as a first-class in-chat panel, not only a small metadata pill.
2. Show tool calls while they are running, with start/success/error states.
3. Add a visible "agent is thinking / routing" state before the first token.
4. Minify the widget bundle and consider size budgets.
5. Add configuration for theme, launcher text, panel size, and branding.

The next architecture step is to decide whether the copied AI Elements-style
components should remain local to the widget or be formalized as a small
internal UI package.
