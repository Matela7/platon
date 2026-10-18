# RAG configuration

`add_document_to_collection` accepts `chunk_size=1000`, `chunk_overlap=100`, and `reindex=False`. Sizes are characters. Start with 500/50 for short factual sections, 1000/100 for ordinary prose, or 1800/200 for longer narrative context. These are corpus-dependent starting points; evaluate retrieval on real questions and respect the embedding model's token limit.

Inspect `get_collection_info(collection_name=...)` for stored ingestion settings. Unchanged sources reuse their chunks. Changed content or settings require an explicit `reindex=True`; asking a different question does not require ingestion. Legacy documents without a fingerprint cannot be verified as unchanged automatically.

Search separates the final result count from retrieval candidates:

```python
search_collection(
    collection_name="books",
    query="How does the narrator's attitude change?",
    n_results=6,
    candidate_k=30,
    rerank=True,
)
```

`rank=True` enables embedding-based ranking. `rerank=True` scores query/passage pairs with a local cross-encoder loaded on demand. The first rerank may download its model; later calls reuse the cached model. Start with 20–40 candidates and 3–8 final passages, increasing coverage when evidence is missing. A reranker cannot recover passages absent from its candidate pool. Avoid inferring calibrated confidence from distance, cosine similarity, or reranker scores.

The Database Agent can read documents only after a successful search in the current task. `read_file` accepts 1-based PDF page ranges and modes `small` (2000 characters), `standard` (6000), `expanded` (12000), and `deep` (30000). A truncation notice is appended when needed. DOCX returns paragraphs and tables without page layout. Use returned source paths and page metadata to read surrounding context. The documents directory remains the read boundary.

## Optional subagent models

`SupervisorAgent.from_config(..., subagent_model=None)` and `DeepAgent(..., subagent_model=None)` accept an optional model instance. When omitted, subagents use the supervisor model. Set temperature on the model instance you pass.

## Sources

- [LangChain recursive splitting](https://docs.langchain.com/oss/python/integrations/splitters/recursive_text_splitter): character-based size and overlap, preserving paragraphs where possible.
- [Sentence Transformers retrieve and rerank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html): retrieve a larger candidate pool, score query/passage pairs, then return a smaller final set.
