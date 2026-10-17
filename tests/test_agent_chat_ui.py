"""Exercise the HTTP stream, questions, lifecycle and event-loop responsiveness."""

import asyncio
import json
import shutil
import subprocess
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from langchain_core.messages import AIMessage

from agent.agent_orchestrator import AgentOrchestrator
from agent.base_agent import BaseAgent
from agent.models.agent_orchestrator_config import AgentOrchestratorConfig
from backend.agent_chat_ui import STATE, create_app, _build_ui_html
from tests.test_agent_workflows import ScriptedModel


class FakeAgent:
    def __init__(self, thread_id="one"):
        self.thread_id = thread_id or "one"
        self.messages = []
        self.closed = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.wait = False

    def load_thread_history(self):
        return list(self.messages)

    def list_threads(self):
        return [{"thread_id":self.thread_id,"title":"Example","message_count":len(self.messages)}]

    def pending_interrupts(self):
        return []

    def can_retry(self):
        return False

    def thread_exists(self, thread_id):
        return thread_id in {self.thread_id, "two"}

    def stream(self, text, *, stop_event=None):
        self.messages.append({"role":"user","content":text})
        yield {"type":"delta","data":"Hello "}
        self.entered.set()
        if self.wait:
            for _ in range(500):
                if self.release.wait(.01):
                    break
                if stop_event is not None and stop_event.is_set():
                    self.messages.append({"role":"assistant","content":"[⏹]"})
                    yield {"type":"result","data":{"answer":"","status":"stopped","errors":[],"evidence":[],
                           "interrupts":[],"can_retry":False,"thread_id":self.thread_id}}
                    return
        self.messages.append({"role":"assistant","content":"Hello world"})
        yield {"type":"delta","data":"world"}
        yield {"type":"result","data":{"answer":"Hello world","status":"completed","errors":[],"evidence":[],"interrupts":[],"can_retry":False,"thread_id":self.thread_id}}

    def resume_stream(self, decisions, *, stop_event=None):
        if decisions != {"ask":{"answer":"example.py"}}:
            raise ValueError("Responses must match pending questions.")
        yield from self.stream("continued", stop_event=stop_event)

    def retry_stream(self, *, stop_event=None):
        raise ValueError("There is no unfinished run.")
        yield

    def discard_pending_run(self):
        return False

    def close(self):
        self.closed = True


class AgentChatUiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.agent = FakeAgent()
        self.patcher = patch("backend.agent_chat_ui._build_agent", side_effect=lambda thread_id=None: self.agent if thread_id is None else FakeAgent(thread_id))
        self.patcher.start()
        self.client = TestClient(TestServer(create_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        self.agent.release.set()
        await self.client.close()
        self.patcher.stop()

    async def test_chat_streams_and_persists_the_terminal_result(self):
        response = await self.client.post("/api/chat", json={"message":"test", "thread_id":"one"})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, "application/x-ndjson")
        events = [json.loads(line) for line in (await response.text()).splitlines()]
        self.assertEqual("".join(e["data"] for e in events if e["type"] == "delta"), "Hello world")
        result = events[-1]["data"]
        self.assertEqual(result["messages"], self.agent.messages)
        history = await self.client.get("/api/history")
        self.assertEqual(await history.json(), self.agent.messages)

    async def test_stream_does_not_block_history_or_allow_thread_switch(self):
        self.agent.wait = True
        response = await self.client.post("/api/chat", json={"message":"wait"})
        first = await asyncio.wait_for(response.content.readline(), 1)
        self.assertEqual(json.loads(first)["type"], "delta")
        history = await asyncio.wait_for(self.client.get("/api/history"), 1)
        self.assertEqual(history.status, 200)
        listing = await asyncio.wait_for(self.client.get("/api/conversations"), 1)
        self.assertEqual(listing.status, 200)
        switch = await self.client.get("/api/conversations/two")
        reset = await self.client.post("/api/reset")
        duplicate = await self.client.post("/api/chat", json={"message":"another"})
        queued = json.loads(await asyncio.wait_for(duplicate.content.readline(), 1))
        self.assertEqual([switch.status, reset.status, duplicate.status], [409,409,200])
        self.assertEqual(queued["type"], "queued")
        self.assertEqual([m["content"] for m in self.agent.messages], ["wait"])
        self.assertFalse(self.agent.closed)
        self.agent.release.set()
        await response.read()
        await duplicate.read()
        self.assertEqual([m["content"] for m in self.agent.messages if m["role"] == "user"], ["wait", "another"])

    async def test_stop_is_responsive_and_next_message_can_run(self):
        self.agent.wait = True
        response = await self.client.post("/api/chat", json={"message":"wait"})
        await response.content.readline()
        wrong = await self.client.post("/api/stop", json={"thread_id":"two"})
        self.assertEqual(wrong.status, 409)
        stop = await asyncio.wait_for(self.client.post("/api/stop", json={"thread_id":"one"}), 1)
        self.assertTrue((await stop.json())["stopped"])
        events = [json.loads(line) for line in (await asyncio.wait_for(response.text(), 1)).splitlines()]
        self.assertEqual(events[-1]["data"]["status"], "stopped")
        self.assertFalse(self.client.server.app[STATE]["run_lock"].locked())
        self.agent.wait = False
        response = await self.client.post("/api/chat", json={"message":"next"})
        events = [json.loads(line) for line in (await response.text()).splitlines()]
        self.assertEqual(events[-1]["data"]["status"], "completed")

    async def test_three_requests_run_in_fifo_order(self):
        self.agent.wait = True
        first = await self.client.post("/api/chat", json={"message":"first"})
        await first.content.readline()
        second = await self.client.post("/api/chat", json={"message":"second"})
        await second.content.readline()
        third = await self.client.post("/api/chat", json={"message":"third"})
        await third.content.readline()
        listing = await (await self.client.get("/api/conversations")).json()
        self.assertTrue(listing["running"])
        self.assertEqual(listing["queue_length"], 2)
        self.agent.release.set()
        await asyncio.gather(first.read(), second.read(), third.read())
        self.assertEqual([m["content"] for m in self.agent.messages if m["role"] == "user"], ["first", "second", "third"])

    async def test_disconnect_keeps_running_and_publishes_history(self):
        self.agent.wait = True
        response = await self.client.post("/api/chat", json={"message":"wait"})
        await response.content.readline()
        response.close()
        self.agent.release.set()
        async def finished():
            async with self.client.server.app[STATE]["run_lock"]:
                return await (await self.client.get("/api/history")).json()
        saved = await asyncio.wait_for(finished(), 2)
        self.assertEqual(saved[-1], {"role":"assistant", "content":"Hello world"})

    async def test_real_graph_stream_reconciles_history(self):
        with TemporaryDirectory() as directory:
            agent = AgentOrchestrator(
                config=AgentOrchestratorConfig(sqlite_path=Path(directory)/"chat.sqlite3"),
                agent=BaseAgent(ScriptedModel(responses=[AIMessage(content="Real graph answer")]), prompt="test"),
            )
            with patch("backend.agent_chat_ui._build_agent", return_value=agent):
                client = TestClient(TestServer(create_app()))
            await client.start_server()
            try:
                response = await client.post("/api/chat", json={"message":"hello"})
                events = [json.loads(line) for line in (await response.text()).splitlines()]
                self.assertEqual(events[-1]["data"]["answer"], "Real graph answer")
                self.assertEqual(events[-1]["data"]["messages"][-1]["content"], "Real graph answer")
                self.assertEqual("".join(e["data"] for e in events if e["type"] == "delta"), "Real graph answer")
            finally:
                await client.close()

    async def test_question_resume_uses_the_stream_endpoint(self):
        response = await self.client.post("/api/resume", json={"thread_id":"one","decisions":{"ask":{"answer":"example.py"}}})
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads((await response.text()).splitlines()[-1])["data"]["status"], "completed")
        response = await self.client.post("/api/resume", json={"thread_id":"one","decisions":{}})
        self.assertEqual(response.status, 409)

    async def test_request_validation_and_unknown_thread(self):
        for message in [None, 123, " "]:
            response = await self.client.post("/api/chat", json={"message":message})
            self.assertEqual(response.status, 400)
        response = await self.client.post("/api/chat", json={"message":"test","thread_id":"missing"})
        self.assertEqual(response.status, 404)
        response = await self.client.post("/api/resume", json={"decisions":{}})
        self.assertEqual(response.status, 400)

    async def test_reset_and_switch_close_the_old_instance(self):
        response = await self.client.get("/api/conversations/two")
        self.assertEqual(response.status, 200)
        self.assertTrue(self.agent.closed)
        response = await self.client.post("/api/reset")
        result = await response.json()
        self.assertNotEqual(result["thread_id"], "two")

    def test_rendered_javascript_parses_and_consumes_streams(self):
        html = _build_ui_html()
        self.assertIn("response.body.getReader()", html)
        self.assertIn('review.value.kind === "clarification"', html)
        if shutil.which("node"):
            script = html.split("<script>")[1].split("</script>")[0]
            result = subprocess.run(["node", "--check"], input=script, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is required to execute the browser queue")
    def test_browser_queue_stop_and_resume_lifecycle(self):
        script = _build_ui_html().split("<script>")[1].split("</script>")[0]
        result = subprocess.run(["node", str(Path(__file__).with_name("agent_chat_queue.js"))],
                                input=script, capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
