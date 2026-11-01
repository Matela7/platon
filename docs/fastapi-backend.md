# API AgentRuntimeService

Run `make api` (the command checks and starts local Ollama when needed).
Swagger UI is available at `http://127.0.0.1:8000/docs`.

The request flow is router → AgentRuntimeService → AgentOrchestrator.
One application owns one service instance. All endpoints use the
`/api/v1/agent-runtime` prefix.

| Method | Path | Action |
|---|---|---|
| POST | `/initialize` | Create or open a runtime with configuration |
| GET | `/snapshot` | Get history, interrupts, and retry availability |
| GET | `/history` | Get conversation history |
| GET | `/threads` | List conversations in the current database |
| GET | `/config` | Get both configurations |
| PUT | `/config` | Update configuration and rebuild the orchestrator |
| POST | `/chat` | Send a message and stream the response |
| POST | `/resume` | Respond to current interrupts |
| POST | `/retry` | Resume unfinished work |
| POST | `/stop` | Request execution to stop |
| POST | `/discard` | Discard pending work |

Initialization accepts `agent_config`, `orchestrator_config`, and an optional
`thread_id`. It uses the existing configuration models. When `thread_id` is
omitted, the orchestrator opens the most recent conversation or creates one
when the database is empty. A new conversation can be selected with a new UUID.

Fetch `GET /config`, change the values, and send the complete object to
`PUT /config`. The conversation ID is preserved. Changing the SQLite path
selects another store without moving history. Configuration is kept in memory
for the lifetime of the application.

`POST /chat` accepts `{"message":"Message text"}`. Chat, resume, and retry
return NDJSON: each orchestrator event is a separate JSON line.
`POST /resume` accepts `{"decisions":{"interrupt-id":{"answer":"..."}}}`
or approve/reject decisions matching the current interrupt. Retry, stop, and
discard do not require a request body.

The stream belongs to the current request. After a disconnect, read the
snapshot and check whether resuming is available. There is no separate task
registry or stream replay. One lock protects the orchestrator from concurrent
execution and configuration changes; a busy runtime returns `409`. Stop
bypasses the lock. FastAPI runs synchronous endpoints and streams outside the
event loop.

`@log_call` logs operation progress. Unexpected exceptions include stack traces
in the logs. An error after a stream starts is returned as an error event;
before the stream starts, it may be returned as an HTTP response. History and
checkpoints remain in SQLite.
