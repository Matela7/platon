"""RAG ingestion lifecycle and candidate/final ranking contracts."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import chromadb
import numpy as np

from platon.agent.tools.rag import create_rag_tools
from platon.vectorstore.chroma_utils import _rank_results, rerank_results
from platon.vectorstore.client_manager import ClientManager
from platon.vectorstore.collection_store import CollectionStore
from platon.vectorstore.errors import VectorStoreError


class RagConfigurationTests(unittest.TestCase):
    def test_persisted_settings_reuse_and_explicit_reindex(self):
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            source = Path(directory) / "book.txt"
            source.write_text("One useful sentence. Another useful sentence. " * 10, encoding="utf-8")
            manager = ClientManager(str(Path(directory) / "chroma"))
            model = Mock()
            model.encode.side_effect = lambda texts: np.array([[1., 0.] for _ in texts])
            with patch("platon.vectorstore.chroma_utils.get_model", return_value=model):
                manager.add_document_to_collection("books", str(source), "book.txt", 50, 10)
                info = manager.get_collection_info("books")
                manifest = next(iter(info["documents"].values()))
                self.assertEqual(manifest["chunk_size"], 50)
                self.assertEqual(manifest["chunk_overlap"], 10)
                self.assertEqual(manifest["source_path"], str(source.resolve()))
                self.assertEqual(len(manifest["source_sha256"]), 64)
                count = info["count"]
                self.assertGreater(count, 1)
                # Fresh manager reads the persisted completion manifest.
                reopened = ClientManager(manager.persist_dir)
                with patch("platon.vectorstore.collection_store.load_document", side_effect=AssertionError("must not reload")):
                    reopened.add_document_to_collection("books", str(source), "book.txt", 50, 10)
                self.assertEqual(reopened.get_collection_info("books")["count"], count)
                with self.assertRaises(VectorStoreError) as changed:
                    reopened.add_document_to_collection("books", str(source), "book.txt", 70, 5)
                self.assertIn("reindex=True", str(changed.exception))
                old_ids = manager.client.get_collection("books").get()["ids"]
                reopened.add_document_to_collection("books", str(source), "renamed.txt", 70, 5, reindex=True)
                records = manager.client.get_collection("books").get()
                self.assertFalse(set(old_ids) & set(records["ids"]))
                self.assertTrue(all(item["chunk_size"] == 70 for item in records["metadatas"]))
                source.write_text("Changed content.", encoding="utf-8")
                with self.assertRaises(VectorStoreError):
                    reopened.add_document_to_collection("books", str(source), "renamed.txt", 70, 5)

    def test_partial_writer_rolls_back_only_new_chunks(self):
        client = chromadb.EphemeralClient()
        collection = client.get_or_create_collection("rollback-test")
        collection.add(ids=["old"], documents=["original"], embeddings=[[1., 0.]], metadatas=[{"name": "book.txt"}])
        with TemporaryDirectory() as directory:
            source = Path(directory) / "book.txt"
            source.write_text("Replacement", encoding="utf-8")
            def failing_writer(coll, text, name, **kwargs):
                coll.add(ids=["partial"], documents=[text], embeddings=[[1., 0.]], metadatas=[kwargs["source_metadata"]])
                raise TimeoutError("write failed")
            with patch("platon.vectorstore.collection_store.add_document_to_vector_store", side_effect=failing_writer):
                with self.assertRaises(VectorStoreError):
                    CollectionStore(client, "rollback-test").add_document(str(source), "book.txt", reindex=True)
        self.assertEqual(collection.get()["ids"], ["old"])
        client.delete_collection("rollback-test")

    def test_tool_propagates_chunking_and_search_options(self):
        manager = Mock()
        manager.search.return_value = []
        tools = {item.name: item for item in create_rag_tools(manager)}
        tools["add_document_to_collection"].invoke({"collection_name": "books", "file_path": "book.txt",
                                                  "doc_name": "book", "chunk_size": 700, "chunk_overlap": 70, "reindex": True})
        manager.add_document_to_collection.assert_called_once_with("books", "book.txt", "book", chunk_size=700, chunk_overlap=70, reindex=True)
        tools["search_collection"].invoke({"collection_name": "books", "query": "answer", "n_results": 3,
                                         "candidate_k": 30, "rank": True, "rerank": True})
        self.assertEqual(manager.search.call_args.kwargs["candidate_k"], 30)
        self.assertTrue(manager.search.call_args.kwargs["rank"])
        self.assertTrue(manager.search.call_args.kwargs["rerank"])

    def test_ranking_uses_documents_and_preserves_distinct_sources(self):
        results = [
            {"document": "wrong", "metadata": {"name": "a"}},
            {"document": "answer", "metadata": {"name": "a"}},
            {"document": "answer", "metadata": {"name": "b"}},
            {"document": "answer", "metadata": {"name": "b"}},
        ]
        model = Mock()
        model.encode.return_value = np.array([[1., 0.], [0., 1.], [1., 0.], [1., 0.]])
        with patch("platon.vectorstore.chroma_utils.get_embedding_model", return_value=model):
            ranked = _rank_results("query", results, top_k=3, embedding_weight=1, semantic_dedup_threshold=.95)
        self.assertEqual([item["metadata"]["name"] for item in ranked[:2]], ["a", "b"])
        self.assertNotIn("ddg_score", ranked[0])
        self.assertEqual(model.encode.call_args.args[0], ["query", "wrong", "answer", "answer"])
        self.assertEqual(ranked[0]["rank"], 1)

    def test_reranker_scores_full_pool_before_final_k(self):
        reranker = Mock()
        reranker.predict.return_value = [.1, .9, .2]
        candidates = [{"document": value} for value in ["first", "best", "last"]]
        with patch("platon.vectorstore.chroma_utils.get_reranking_model", return_value=reranker):
            result = rerank_results("query", candidates, 1)
        self.assertEqual(result[0]["document"], "best")
        self.assertEqual(len(reranker.predict.call_args.args[0]), 3)

    def test_collection_retrieves_candidate_k_not_final_k(self):
        model = Mock()
        model.predict.return_value = [.1, .8, .3]
        raw = {"documents": [["first", "best", "last"]], "metadatas": [[{}, {}, {}]], "distances": [[.1, .2, .3]]}
        with patch("platon.vectorstore.collection_store.similarity_search", return_value=raw) as retrieve, \
             patch("platon.vectorstore.chroma_utils.get_reranking_model", return_value=model):
            result = CollectionStore(Mock(), "books").search("query", 1, rerank=True, candidate_k=30)
        self.assertEqual(retrieve.call_args.args[2], 30)
        self.assertEqual(result[0]["document"], "best")

    def test_search_all_uses_reciprocal_rank_across_distance_metrics(self):
        manager = ClientManager()
        a, b = Mock(), Mock()
        a.search.return_value = [{"document": "a1", "similarity": -100.}, {"document": "a2", "similarity": -200.}]
        b.search.return_value = [{"document": "b1", "similarity": .99}]
        with patch.object(manager, "get_collections", return_value=["a", "b"]), \
             patch.object(manager, "get_collection", side_effect=[a, b]):
            result = manager.search_all("query", 2)
        self.assertEqual([item["document"] for item in result], ["a1", "b1"])

    def test_invalid_overlap_does_not_create_collection(self):
        client = Mock()
        with self.assertRaises(VectorStoreError):
            CollectionStore(client, "books").add_document("unused.txt", "unused", 100, 100)
        client.get_or_create_collection.assert_not_called()


if __name__ == "__main__":
    unittest.main()
