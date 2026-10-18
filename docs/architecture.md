# Agent architecture

`AgentOrchestrator` is a conversation-bound wrapper over `SupervisorAgent`.
It exposes `invoke`, `stream`, `resume` and `resume_stream`; `ConversationStore`
owns SQLite history and sidebar metadata. The supervisor's checkpoint is the
execution source of truth, including when a custom checkpointer is injected.
`SupervisorAgent` inherits from `DeepAgent`, with planning, local skills and
file-backed memory. Its `ask_user` tool pauses execution for human clarification
and resumes through the existing UI or CLI.

```text
AgentOrchestrator -> SupervisorAgent
  -> delegate_research -> ResearchAgent (public web and HTTP)
  -> delegate_coding -> CodingAgent (workspace files and host execution)
  -> delegate_database -> DatabaseAgent (private knowledge base)
```

`BaseAgent.runnable` creates one runnable on first use. Configure its model,
tools, prompt and checkpointer before execution. `WorkflowAgent` adds limits
and human review to a single tool loop; it does not force inspection, mutation,
verification or an extra synthesis call on every task.

## Context and delegation

Model middleware limits completed conversation turns before every model call.
The entire active turn is preserved to keep tool-call/result pairs valid;
checkpoint and visible history are not pruned by this transient context policy.
The active turn can exceed `max_history_messages`, but tool and output budgets
bound specialist execution.
Ollama uses a 16,384-token context window by default in this app. Set
`OLLAMA_NUM_CTX` for the UI or CLI, or `AgentConfig(num_ctx=...)` in code, to
match the model and available memory. The message limit does not guarantee a
token limit, so very large active turns can still exceed the context window.

Delegation takes original `user_request`, a bounded `task` goal and optional
`retry_reason`. Prior specialist reports are passed as dependency evidence with
source URLs, document metadata, paths, actual outcomes and errors. Dependent
calls must be made in sequence. An identical completed task is reused; a repeated
incomplete task requires an explicit reason and knowledge of the previous outcome.

Reports contain `status` (`completed`, `partial`, `error`), `answer`, `evidence`
and `errors`. They are assembled from actual messages without another model call.
A specialist's active task includes the full original request and dependency
reports, so trimming earlier turns cannot discard constraints or source evidence.
A failure retains confirmed tool results. Empty retrieval is distinct from failed
retrieval. Mutations with uncertain outcomes are not marked safe to retry.

## Persistence and human input

SQLite conversation rows retain the existing format. Checkpoint thread ids retain
the `platon-chat-v2:` prefix, and older visible conversations bootstrap once when
no checkpoint exists. Old interrupted staged workflows cannot be resumed with the
new single-loop topology; start a new conversation for those legacy interruptions.

A fresh user message is persisted before execution. Failures preserve checkpoints
and visible user turns. `retry_stream()` resumes the failed node without adding
another message or re-executing completed graph nodes. An unfinished run must be
continued before another user message is accepted. This cannot guarantee exactly-once
execution when the failing tool itself performed a side effect before raising.

Mutations, host execution, ingestion and HTTP POST pause for concrete approval.
`ask_user` instead emits `{"kind":"clarification","question":"..."}`. Resume with
`{interrupt_id: {"answer":"..."}}` for questions or
`{interrupt_id: {"decisions":[{"type":"approve"}]}}` for action reviews.

## Streaming UI

`/api/chat`, `/api/resume` and `/api/retry` return newline-delimited JSON events:
`delta`, `progress`, and a terminal `result` (or a transport `error`). The UI streams
supervisor text, displays progress, questions, approvals and incomplete outcomes.
Sync graph execution runs in one dedicated server worker. An application lock
prevents concurrent runs and conversation switches; cached history remains readable.
Disconnecting the browser does not abandon an executing tool.

## Tools and defaults

File tools resolve paths inside the workspace and return typed failures.
Shell uses the host shell; Python uses a fresh subprocess. Both start in the
workspace, preserve process exit/output information, and have a timeout.
They are not security sandboxes. Python variables do not survive across calls.
RAG retrieval uses `get_collection`; only ingestion may create a collection.

`AgentConfig` defaults: research 6, coding 15, database 4 tool calls;
execution timeout 120 seconds; `debug=False`. Limits can be configured directly.
Ollama thinking is disabled by default (`reasoning=False`) for faster responses;
set `AgentConfig(reasoning=True)` to enable it. Logs report model load, prompt
processing and generation times separately. Embedding libraries load when web
search or RAG is first used.
DeepAgent uses local `skills=["/skills/"]` and `memory=["/memory/AGENTS.md"]`
relative to `backend_root` (the `.platon/agent` directory by default). Add skills as
`.platon/agent/skills/<name>/SKILL.md`. Memory is file-backed and survives restarts;
conversation state still requires a checkpointer. Empty source lists disable loading.

## Verification

```powershell
uv run --locked python -m unittest discover -s tests -v
```

Tests use real LangGraph execution with scripted models and temporary SQLite:
context bounds, dependency evidence, error reports, clarification/approval resume,
restart, post-error continuation without repeated tools, process isolation and
HTTP streaming responsiveness. They do not benchmark a live model's task quality.
