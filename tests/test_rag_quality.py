"""Checks that RAG evidence remains readable and has clear provenance."""

import unittest
from unittest.mock import Mock, patch

from platon.agent.tools.rag import create_rag_tools
from platon.vectorstore.chroma_utils import add_pdf_document_to_vector_store, format_search_results


class RagQualityTests(unittest.TestCase):
    def test_output_budget_keeps_complete_passages_and_reports_omissions(self):
        manager = Mock()
        passages = [
            {"document": f"Complete passage {index}." * 12,
             "metadata": {"name": "book.pdf", "page": index},
             "distance": index / 10, "similarity": 1 - index / 10}
            for index in range(8)
        ]
        manager.search.return_value = passages
        tool = next(tool for tool in create_rag_tools(manager, max_output_chars=900)
                    if tool.name == "search_collection")

        result = tool.invoke({"collection_name": "books", "query": "query", "n_results": 8})

        self.assertGreater(len(result), 0)
        self.assertLess(len(result), len(passages))
        self.assertEqual(result[-1]["omitted_results"], len(passages) - len(result))
        self.assertEqual([item["document"] for item in result],
                         [item["document"] for item in passages[:len(result)]])
        self.assertTrue(all("similarity" in item for item in result))

    def test_existing_pdf_page_index_gains_readable_page_number(self):
        raw = {"documents": [["Quoted source text"]],
               "metadatas": [[{"name": "book.pdf", "page": 14}]],
               "distances": [[1.4]]}

        result = format_search_results(raw)

        self.assertEqual(result[0]["metadata"]["page"], 14)
        self.assertEqual(result[0]["metadata"]["page_number"], 15)
        self.assertEqual(result[0]["distance"], 1.4)
        self.assertAlmostEqual(result[0]["similarity"], -0.4)

    def test_new_pdf_chunks_record_file_page_number(self):
        collection = Mock()
        model = Mock()
        model.encode.return_value.tolist.return_value = [[0.1, 0.2]]
        splitter = Mock()
        splitter.split_text.return_value = ["source text"]
        with patch("platon.vectorstore.chroma_utils.get_model", return_value=model), \
             patch("platon.vectorstore.chroma_utils.get_text_splitter", return_value=splitter):
            add_pdf_document_to_vector_store(collection, [(14, "source text")], "book.pdf")

        metadata = collection.add.call_args.kwargs["metadatas"][0]
        self.assertEqual(metadata["page"], 14)
        self.assertEqual(metadata["page_number"], 15)


if __name__ == "__main__":
    unittest.main()
