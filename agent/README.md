# Agent architecture

`BaseAgent` stores the shared `AgentConfig`, model, prompt, tools, and an optional
checkpointer. It does not create infrastructure or choose capabilities.

The composition flow is:

```text
AgentOrchestrator
  -> SupervisorAgent.from_config(...)
      -> answers general requests directly
      -> delegate_research -> ResearchAgent (web + HTTP)
      -> delegate_coding   -> CodingAgent (files + shell + Python)
      -> delegate_database -> DatabaseAgent (Chroma/RAG)
```

Delegation tools are `AgentToolAdapter` instances exposed as LangChain tools.
They do not inherit from `BaseAgent`. The supervisor receives only `delegate_*`
tools, and rejects direct RAG tools at construction time. `ClientManager` is
created privately by `DatabaseAgent`; the supervisor never receives it.
