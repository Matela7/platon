from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep
import unittest
from unittest.mock import Mock, patch

import numpy as np

from agent.tools.tools import create_web_search_tools
from embedding_models import (
    clear_embedding_model_cache,
    get_embedding_model,
)
from websearch.utils import canonicalize_url
from websearch.websearch_module import WebSearch, rank_results
from websearch.websearch_parameters import WebSearchParameters


class FakeEmbeddingModel:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[tuple[list[str], bool]] = []

    def encode(
        self,
        texts: list[str],
        *,
        normalize_embeddings: bool,
    ) -> np.ndarray:
        self.calls.append((texts, normalize_embeddings))
        return np.asarray(self.vectors, dtype=float)


class WebSearchTests(unittest.TestCase):
    def test_canonicalize_url_removes_tracking_and_fragment(self) -> None:
        url = "HTTPS://www.Example.com/article/?utm_source=x&id=7#section"
        self.assertEqual(
            canonicalize_url(url),
            "https://example.com/article?id=7",
        )

    def test_rank_results_deduplicates_and_uses_hybrid_score(self) -> None:
        model = FakeEmbeddingModel(
            [
                [1.0, 0.0],
                [0.8, 0.6],
                [1.0, 0.0],
                [0.999, 0.001],
            ]
        )
        results = [
            {
                "title": "General guide",
                "link": "https://example.com/guide?utm_source=test",
                "snippet": "A related guide.",
            },
            {
                "title": "Best answer",
                "link": "https://docs.example.org/answer",
                "snippet": "The direct answer.",
            },
            {
                "title": "Best answer mirror",
                "link": "https://mirror.example.org/answer",
                "snippet": "The direct answer copied elsewhere.",
            },
            {
                "title": "Duplicate URL",
                "link": "https://www.example.com/guide/#copy",
                "snippet": "This result is removed before embedding.",
            },
        ]

        with patch(
            "websearch.websearch_module.get_embedding_model",
            return_value=model,
        ):
            ranked = rank_results("direct answer", results, top_k=5)

        self.assertEqual([result["title"] for result in ranked], ["Best answer", "General guide"])
        self.assertEqual([result["rank"] for result in ranked], [1, 2])
        self.assertEqual(ranked[0]["original_position"], 1)
        self.assertGreater(ranked[0]["final_score"], ranked[1]["final_score"])
        self.assertEqual(len(model.calls), 1)
        self.assertTrue(model.calls[0][1])
        self.assertEqual(len(model.calls[0][0]), 4)

    def test_embedding_model_first_load_is_thread_safe(self) -> None:
        construction_lock = Lock()
        constructions = 0
        fake_model = Mock()
        fake_model.named_parameters.return_value = []

        def construct_model(*args: object, **kwargs: object) -> Mock:
            nonlocal constructions
            with construction_lock:
                constructions += 1
            sleep(0.02)
            return fake_model

        clear_embedding_model_cache()
        try:
            with patch(
                "embedding_models.SentenceTransformer",
                side_effect=construct_model,
            ) as constructor:
                with ThreadPoolExecutor(max_workers=8) as executor:
                    models = list(
                        executor.map(
                            lambda _: get_embedding_model(),
                            range(16),
                        )
                    )

            self.assertEqual(constructions, 1)
            constructor.assert_called_once_with(
                "sentence-transformers/all-MiniLM-L6-v2",
                device="cpu",
                revision="1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
            )
            self.assertTrue(all(model is fake_model for model in models))
        finally:
            clear_embedding_model_cache()

    def test_embedding_model_retries_transient_meta_tensor_failure(self) -> None:
        fake_model = Mock()
        fake_model.named_parameters.return_value = []
        meta_error = NotImplementedError(
            "Cannot copy out of meta tensor; no data!"
        )

        clear_embedding_model_cache()
        try:
            with patch(
                "embedding_models.SentenceTransformer",
                side_effect=[meta_error, fake_model],
            ) as constructor:
                loaded_model = get_embedding_model()

            self.assertIs(loaded_model, fake_model)
            self.assertEqual(constructor.call_count, 2)
        finally:
            clear_embedding_model_cache()

    def test_web_search_retrieves_candidates_from_duckduckgo(self) -> None:
        parameters = WebSearchParameters(query="LangChain reranking", top_k=2)
        web_search = WebSearch(parameters)
        web_search.wrapper = Mock()
        web_search.wrapper.results.return_value = [
            {"title": "One", "link": "https://one.test", "snippet": "First"}
        ]

        with patch(
            "websearch.websearch_module.rank_results",
            return_value=[{"title": "One", "rank": 1}],
        ) as rerank:
            results = web_search.search()

        self.assertEqual(results, [{"title": "One", "rank": 1}])
        web_search.wrapper.results.assert_called_once_with(
            "LangChain reranking",
            max_results=15,
            source="text",
        )
        rerank.assert_called_once()

    def test_agent_search_tool_uses_websearch_module(self) -> None:
        search_tool = create_web_search_tools()[0]
        with patch("agent.tools.tools.WebSearch") as web_search_class:
            web_search_class.return_value.search.return_value = [{"rank": 1}]
            response = search_tool.invoke({"query": "current LangChain release"})

        self.assertEqual(
            response,
            {"query": "current LangChain release", "results": [{"rank": 1}]},
        )
        parameters = web_search_class.call_args.args[0]
        self.assertEqual(parameters.query, "current LangChain release")
        self.assertEqual(parameters.max_results, 15)
        self.assertEqual(parameters.top_k, 5)

    def test_agent_search_tool_explains_duckduckgo_time_window(self) -> None:
        search_tool = create_web_search_tools()[0]

        time_schema = search_tool.args_schema.model_json_schema()["properties"]["time"]

        self.assertIn("DuckDuckGo result-age window", time_schema["description"])
        self.assertIn("not a date, current time", time_schema["description"])


if __name__ == "__main__":
    unittest.main()
