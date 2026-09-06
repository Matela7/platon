from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from unittest.mock import patch

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage

from agent.agent_orchestrator import AgentOrchestrator
from agent.base_agent import BaseAgent
from agent.models.agent_orchestrator_config import AgentOrchestratorConfig


class RecordingGraph:
    def __init__(self) -> None:
        self.inputs: list[dict[str, Any]] = []

    def invoke(
        self,
        payload: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.inputs.append(payload)
        return {"messages": [*payload["messages"], AIMessage(content="done")]}


class GraphAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(cast(BaseChatModel, object()), prompt="stub")
        self.graph = RecordingGraph()

    def create_agent(self, prompt: str | None = None) -> RecordingGraph:
        return self.graph


class AgentOrchestratorTests(unittest.TestCase):
    @staticmethod
    def _config(directory: str) -> AgentOrchestratorConfig:
        return AgentOrchestratorConfig(
            working_dir=Path(directory),
            sqlite_path=Path(directory) / "threads.sqlite3",
        )

    def test_lists_saved_threads_and_reopens_the_latest_one(self) -> None:
        with TemporaryDirectory() as directory:
            config = self._config(directory)
            first = AgentOrchestrator(
                config=config,
                agent=GraphAgent(),
                thread_id="thread-one",
            )
            first._save_thread([{"role": "user", "content": "Pierwszy temat"}])
            first.close()

            second = AgentOrchestrator(
                config=config,
                agent=GraphAgent(),
                thread_id="thread-two",
            )
            second._save_thread([{"role": "user", "content": "Drugi temat"}])
            summaries = second.list_threads()
            second.close()

            reopened = AgentOrchestrator(config=config, agent=GraphAgent())
            try:
                self.assertEqual(reopened.thread_id, "thread-two")
                self.assertEqual(
                    [item["thread_id"] for item in summaries],
                    ["thread-two", "thread-one"],
                )
                self.assertEqual(summaries[0]["title"], "Drugi temat")
            finally:
                reopened.close()

    def test_existing_checkpoint_receives_only_the_new_message(self) -> None:
        with TemporaryDirectory() as directory:
            graph_agent = GraphAgent()
            orchestrator = AgentOrchestrator(
                config=self._config(directory),
                agent=graph_agent,
                thread_id="thread-one",
            )
            history = [
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
            ]
            try:
                with patch.object(orchestrator, "_has_checkpoint", return_value=True):
                    orchestrator.invoke("New question", history)

                sent_messages = graph_agent.graph.inputs[0]["messages"]
                self.assertEqual(len(sent_messages), 1)
                self.assertIsInstance(sent_messages[0], HumanMessage)
                self.assertEqual(sent_messages[0].content, "New question")
                self.assertEqual(len(orchestrator.load_thread_history()), 4)
            finally:
                orchestrator.close()

    def test_thread_without_checkpoint_is_bootstrapped_from_visible_history(self) -> None:
        with TemporaryDirectory() as directory:
            graph_agent = GraphAgent()
            orchestrator = AgentOrchestrator(
                config=self._config(directory),
                agent=graph_agent,
                thread_id="legacy-thread",
            )
            history = [
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
            ]
            try:
                with patch.object(orchestrator, "_has_checkpoint", return_value=False):
                    orchestrator.invoke("New question", history)

                sent_messages = graph_agent.graph.inputs[0]["messages"]
                self.assertEqual(len(sent_messages), 3)
                self.assertEqual(sent_messages[-1].content, "New question")
            finally:
                orchestrator.close()


if __name__ == "__main__":
    unittest.main()
