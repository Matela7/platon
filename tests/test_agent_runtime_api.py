"""Check the direct runtime router without external model services."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import Mock

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from platon.agent.base_agent import BaseAgent
from platon.backend.app import create_app
from platon.backend.services.agent_runtime_service import AgentRuntimeService
from tests.test_agent_workflows import ScriptedModel

BASE = "/api/v1/agent-runtime"


class AgentRuntimeAPITests(unittest.TestCase):
    def test_direct_stream_and_sqlite_history(self):
        def factory(orchestrator_config, agent_config, thread_id=None):
            agent = BaseAgent(ScriptedModel(responses=[AIMessage(content="Answer")]),
                              config=agent_config, prompt="test")
            return AgentRuntimeService(orchestrator_config, agent_config, agent, thread_id)

        with TemporaryDirectory() as directory:
            with TestClient(create_app(factory)) as client:
                self.assertEqual(client.get(BASE + "/history").status_code, 409)
                body = {"thread_id": "test-thread", "orchestrator_config": {
                    "sqlite_path": str(Path(directory) / "chat.sqlite3"),
                }, "agent_config": {"backend_root": directory}}
                self.assertEqual(client.post(BASE + "/initialize", json=body).status_code, 200)
                response = client.post(BASE + "/chat", json={"message": "Hello"})
                self.assertEqual(response.status_code, 200, response.text)
                events = [json.loads(line) for line in response.text.splitlines()]
                self.assertEqual(events[-1]["data"]["answer"], "Answer")
                self.assertNotIn("result", events[-1]["data"])
                history = client.get(BASE + "/history").json()["data"]
                self.assertEqual([item["content"] for item in history], ["Hello", "Answer"])
                self.assertEqual(client.post(BASE + "/chat", json={"message": " "}).status_code, 422)
                self.assertEqual(client.get(BASE + "/snapshot").json()["data"]["interrupts"], [])

    def test_threads_endpoint_returns_all_saved_threads(self):
        service = Mock(spec=AgentRuntimeService)
        service.thread_id = "current"
        service.get_config.return_value = {}
        service.list_threads.return_value = [
            {"thread_id": "current", "title": "Current"},
            {"thread_id": "older", "title": "Older"},
        ]
        with TestClient(create_app(lambda **kwargs: service)) as client:
            self.assertEqual(client.post(BASE + "/initialize", json={}).status_code, 200)
            response = client.get(BASE + "/threads")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                [item["thread_id"] for item in response.json()["data"]],
                ["current", "older"],
            )

    def test_delete_threads_endpoints(self):
        service = Mock(spec=AgentRuntimeService)
        service.thread_id = "current"
        service.get_config.return_value = {}
        service.thread_exists.side_effect = lambda tid: tid in {"current", "older"}
        service.delete_thread.return_value = True

        with TestClient(create_app(lambda **kwargs: service)) as client:
            client.post(BASE + "/initialize", json={})

            # 404 for non-existent thread
            resp_404 = client.delete(BASE + "/threads/nonexistent")
            self.assertEqual(resp_404.status_code, 404)
            self.assertIn("Thread not found", resp_404.json()["detail"])

            # Delete specific thread
            resp = client.delete(BASE + "/threads/older")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["data"]["deleted"], True)
            self.assertEqual(resp.json()["data"]["thread_id"], "older")
            service.delete_thread.assert_called_with("older")

            # Delete current active thread
            resp_cur = client.delete(BASE + "/threads")
            self.assertEqual(resp_cur.status_code, 200)
            self.assertEqual(resp_cur.json()["data"]["deleted"], True)
            self.assertEqual(resp_cur.json()["data"]["thread_id"], "current")
            service.delete_thread.assert_called_with("current")

            # 409 conflict when runtime error (e.g. active run)
            service.delete_thread.side_effect = RuntimeError("Stop the active run before deleting")
            resp_409 = client.delete(BASE + "/threads/current")
            self.assertEqual(resp_409.status_code, 409)
            self.assertIn("Stop the active run", resp_409.json()["detail"])

    def test_config_is_passed_directly_and_busy_stream_can_be_stopped(self):
        entered, release = Event(), Event()
        service = Mock(spec=AgentRuntimeService)
        service.thread_id = "thread"
        config = {"orchestrator_config": {}, "agent_config": {"model_temperature": 0.4}}
        service.get_config.return_value = config
        service.replace_config.return_value = config
        service.stop.side_effect = lambda: release.set() or True

        def stream(message):
            yield {"type": "delta", "data": "hello"}
            entered.set()
            if not release.wait(3):
                raise TimeoutError("Stop did not reach the runtime")
            yield {"type": "result", "data": {"status": "stopped"}}

        service.stream.side_effect = stream
        factory = Mock(return_value=service)
        with TestClient(create_app(factory)) as client:
            self.assertEqual(client.post(BASE + "/initialize", json=config).status_code, 200)
            self.assertEqual(factory.call_args.kwargs["agent_config"].model_temperature, 0.4)
            self.assertEqual(client.put(BASE + "/config", json=config).status_code, 200)
            self.assertEqual(service.replace_config.call_args.args[1].model_temperature, 0.4)
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(client.post, BASE + "/chat", json={"message": "Hello"})
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(client.put(BASE + "/config", json=config).status_code, 409)
                    self.assertEqual(client.post(BASE + "/stop").status_code, 200)
                    self.assertIn('"stopped"', future.result(timeout=2).text)
                finally:
                    release.set()
            self.assertEqual(client.get(BASE + "/config").status_code, 200)
        service.close.assert_called_once()

    def test_stream_exceptions_are_logged_and_reported(self):
        service = Mock(spec=AgentRuntimeService)
        service.thread_id = "thread"
        service.get_config.return_value = {}

        def stream(message):
            yield {"type": "delta", "data": "hello"}
            raise RuntimeError("test failure")

        service.stream.side_effect = stream
        with TestClient(create_app(lambda **kwargs: service)) as client:
            client.post(BASE + "/initialize", json={})
            with self.assertLogs("platon", level="ERROR") as logged:
                response = client.post(BASE + "/chat", json={"message": "Hello"})
            stream_error = json.loads(response.text.splitlines()[-1])
            self.assertEqual(stream_error["type"], "error")
            self.assertIn("test failure", stream_error["data"]["message"])
            self.assertTrue(any(record.exc_info for record in logged.records))
            service.retry_stream.side_effect = ValueError("Nothing to retry")
            with self.assertLogs("platon", level="ERROR"):
                self.assertEqual(client.post(BASE + "/retry").status_code, 409)

    def test_chat_attachments_are_resolved_before_streaming(self):
        service = Mock(spec=AgentRuntimeService)
        service.thread_id = "thread"
        service.get_config.return_value = {}

        def stream(message):
            yield {"type": "delta", "data": message}

        service.stream.side_effect = stream
        app = create_app(lambda **kwargs: service)
        with TestClient(app) as client:
            client.post(BASE + "/initialize", json={})
            documents = Mock()
            app.state.document_service = documents
            documents.build_attachment_context.return_value = "Attached document: important content"
            response = client.post(BASE + "/chat", json={
                "message": "Summarize", "document_ids": ["document-one"],
            })
            self.assertEqual(response.status_code, 200, response.text)
            documents.build_attachment_context.assert_called_once_with(["document-one"])
            service.stream.assert_called_once_with("Summarize\n\nAttached document: important content")

            for exception, status in [(FileNotFoundError("Unknown document"), 404),
                                      (ValueError("Attachment context too large"), 422),
                                      (RuntimeError("storage unavailable"), 503)]:
                service.stream.reset_mock()
                documents.build_attachment_context.side_effect = exception
                response = client.post(BASE + "/chat", json={
                    "message": "Summarize", "document_ids": ["missing"],
                })
                self.assertEqual(response.status_code, status, response.text)
                service.stream.assert_not_called()

            documents.reset_mock()
            response = client.post(BASE + "/chat", json={"message": "Without attachments"})
            self.assertEqual(response.status_code, 200, response.text)
            documents.build_attachment_context.assert_not_called()
            service.stream.assert_called_once_with("Without attachments")

    def test_chat_rejects_invalid_attachment_lists(self):
        service = Mock(spec=AgentRuntimeService)
        service.thread_id = "thread"
        service.get_config.return_value = {}
        with TestClient(create_app(lambda **kwargs: service)) as client:
            client.post(BASE + "/initialize", json={})
            for ids in [[""], [" "], ["a", "a"], ["x" * 129], [str(i) for i in range(11)]]:
                response = client.post(BASE + "/chat", json={"message": "Hello", "document_ids": ids})
                self.assertEqual(response.status_code, 422, response.text)
            service.stream.assert_not_called()

    def test_shutdown_stops_active_runtime_before_closing_it(self):
        entered, release = Event(), Event()
        service = Mock(spec=AgentRuntimeService)
        service.thread_id = "thread"
        service.get_config.return_value = {}
        service.stop.side_effect = release.set
        app = create_app(lambda **kwargs: service)

        def hold_runtime_lock():
            with app.state.runtime_lock:
                entered.set()
                self.assertTrue(release.wait(3))

        with ThreadPoolExecutor(max_workers=1) as pool:
            with TestClient(app) as client:
                self.assertEqual(client.post(BASE + "/initialize", json={}).status_code, 200)
                future = pool.submit(hold_runtime_lock)
                self.assertTrue(entered.wait(2))
            future.result(timeout=2)

        service.stop.assert_called_once()
        service.close.assert_called_once()

    def test_http_error_details_are_specific_to_the_operation(self):
        service = Mock(spec=AgentRuntimeService)
        service.thread_id = "thread"
        service.get_config.return_value = {}
        service.history.side_effect = RuntimeError("database path is private")
        service.retry_stream.side_effect = ValueError("There is no unfinished run to continue.")

        with TestClient(create_app(lambda **kwargs: service)) as client:
            self.assertEqual(client.post(BASE + "/initialize", json={}).status_code, 200)
            with self.assertLogs("platon", level="ERROR"):
                history = client.get(BASE + "/history")
            self.assertEqual(history.status_code, 500)
            self.assertIn("conversation history", history.json()["detail"])
            self.assertIn("database path is private", history.json()["detail"])

            with self.assertLogs("platon", level="ERROR"):
                retry = client.post(BASE + "/retry")
            self.assertEqual(retry.status_code, 409)
            self.assertEqual(retry.json()["detail"], "There is no unfinished run to continue.")


if __name__ == "__main__":
    unittest.main()
