"""Verify image tool integration without downloading or running a model."""

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from langchain_core.messages import AIMessage

from platon.agent.agent_orchestrator import AgentOrchestrator
from platon.agent.agents.supervisor_agent import SupervisorAgent
from platon.agent.cancellation import RunStopped
from platon.agent.models.agent_config import AgentConfig
from platon.agent.models.agent_orchestrator_config import AgentOrchestratorConfig
from platon.agent.tools.image_generation import create_image_tool
from tests.test_agent_workflows import ScriptedModel, call


class ImageGenerationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.models = self.root / "model-lora"
        self.models.mkdir()
        for name in ("sd-cli.exe", "z-image-turbo-Q5_K_M.gguf", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "ae.safetensors"):
            (self.models / name).touch()

    def test_generates_file_and_artifact_with_optional_lora(self):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            Path(command[command.index("-o") + 1]).write_bytes(b"\x89PNG\r\n\x1a\nexample")
            class Finished:
                returncode = 0
                def poll(self):
                    return 0
            return Finished()

        tool = create_image_tool(self.root)
        with patch("platon.agent.tools.image_generation.subprocess.Popen", side_effect=run):
            result = tool.invoke({"type": "tool_call", "id": "1", "name": "generate_image", "args": {"prompt": "a cat"}})
            self.assertTrue(Path(result.artifact["path"]).is_file())
            self.assertEqual(Path(result.artifact["path"]).parent, self.root / "images")
            self.assertIsNone(result.artifact["lora"])
            self.assertNotIn("--lora-model-dir", commands[-1])
            self.assertEqual(Path(commands[-1][commands[-1].index("--diffusion-model") + 1]).name, "z-image-turbo-Q5_K_M.gguf")
            (self.models / "Z-Real-v1.0.safetensors").touch()
            result = tool.invoke({"type": "tool_call", "id": "2", "name": "generate_image", "args": {"prompt": "a dog"}})
            self.assertEqual(result.artifact["lora"], "Z-Real-v1.0")
            self.assertIn("<lora:Z-Real-v1.0:1.0>", commands[-1][commands[-1].index("-p") + 1])

    def test_missing_files_return_structured_error(self):
        (self.models / "ae.safetensors").unlink()
        result = create_image_tool(self.root).invoke({"prompt": "a cat"})
        self.assertEqual(json.loads(result)["status"], "error")
        self.assertIn("ae.safetensors", result)

    def test_custom_parameters_and_explicit_realism_choice(self):
        commands = []
        (self.models / "Z-Real-v1.0.safetensors").touch()

        def run(command, **kwargs):
            commands.append(command)
            Path(command[command.index("-o") + 1]).write_bytes(b"\x89PNG\r\n\x1a\nexample")
            class Finished:
                returncode = 0
                def poll(self):
                    return 0
            return Finished()

        tool = create_image_tool(self.root)
        with patch("platon.agent.tools.image_generation.subprocess.Popen", side_effect=run):
            result = tool.invoke({"type": "tool_call", "id": "custom", "name": "generate_image", "args": {
                "prompt": "a watercolor fox", "width": 768, "height": 1024, "realism": False,
                "steps": 8, "seed": 42, "vae_tiling": True,
            }})
            args = commands[-1]
            self.assertEqual(args[args.index("-W") + 1], "768")
            self.assertEqual(args[args.index("-H") + 1], "1024")
            self.assertEqual(args[args.index("--steps") + 1], "8")
            self.assertEqual(args[args.index("--seed") + 1], "42")
            self.assertIn("--vae-tiling", args)
            self.assertNotIn("--lora-model-dir", args)
            self.assertNotIn("z-realism", args[args.index("-p") + 1])
            self.assertEqual((result.artifact["width"], result.artifact["height"], result.artifact["seed"]), (768, 1024, 42))
            self.assertIsNone(result.artifact["lora"])

            result = tool.invoke({"type": "tool_call", "id": "realistic", "name": "generate_image", "args": {
                "prompt": "a portrait", "realism": True, "lora_strength": 0.7,
            }})
            self.assertIn("<lora:Z-Real-v1.0:0.7>", commands[-1][commands[-1].index("-p") + 1])
            self.assertEqual(result.artifact["lora_strength"], 0.7)

    def test_missing_explicit_lora_and_invalid_parameters_do_not_start_process(self):
        tool = create_image_tool(self.root)
        with patch("platon.agent.tools.image_generation.subprocess.Popen") as process:
            result = tool.invoke({"prompt": "a portrait", "realism": True})
            self.assertEqual(json.loads(result)["status"], "error")
            self.assertIn("Z-Real-v1.0.safetensors", result)
            for arguments in (
                {"width": 1000}, {"height": 2048}, {"steps": 0},
                {"seed": -2}, {"lora_strength": 3},
            ):
                result = tool.invoke({"prompt": "a cat", **arguments})
                self.assertEqual(json.loads(result)["status"], "error")
            process.assert_not_called()

    def test_parameter_descriptions_are_exposed_to_the_model(self):
        schema = create_image_tool(self.root).args_schema.model_json_schema()["properties"]
        for field in ("prompt", "width", "height", "realism", "steps", "seed", "lora_strength", "vae_tiling"):
            self.assertTrue(schema[field].get("description"), field)

    def test_supervisor_graph_returns_image_artifact_in_report(self):
        def run(command, **kwargs):
            Path(command[command.index("-o") + 1]).write_bytes(b"\x89PNG\r\n\x1a\nexample")
            class Finished:
                returncode = 0
                def poll(self):
                    return 0
            return Finished()

        config = AgentConfig(backend_root=self.root, debug=False, skills=[], memory=[])
        model = ScriptedModel(responses=[
            call("generate_image", "image-call", prompt="a robot selfie"),
            AIMessage(content="Selfie generated."),
        ])
        agent = SupervisorAgent.from_config(
            config, AgentOrchestratorConfig(persist_dir=str(self.root / "chroma")), model=model,
        )
        orchestrator = AgentOrchestrator(
            config=AgentOrchestratorConfig(sqlite_path=self.root / "thread.sqlite3"),
            agent_config=config, agent=agent,
        )
        try:
            with patch("platon.agent.tools.image_generation.subprocess.Popen", side_effect=run):
                result = orchestrator.invoke("Wygeneruj sobie selfie")
            self.assertEqual(result["status"], "completed")
            image = next(item["output"] for item in result["evidence"] if item["tool"] == "generate_image")
            self.assertEqual(image["media_type"], "image/png")
            self.assertTrue(Path(image["path"]).is_file())
        finally:
            orchestrator.close()

    def test_stop_terminates_process_and_removes_partial_output(self):
        stop = Event()
        class Running:
            returncode = None
            killed = False
            def poll(self):
                return self.returncode
            def wait(self, timeout=None):
                if self.killed:
                    self.returncode = -1
                    return -1
                stop.set()
                raise subprocess.TimeoutExpired("sd-cli", timeout)
            def kill(self):
                self.killed = True
        process = Running()
        with patch("platon.agent.tools.image_generation.current_stop_event", return_value=stop), patch(
            "platon.agent.tools.image_generation.subprocess.Popen", return_value=process
        ):
            with self.assertRaises(RunStopped):
                create_image_tool(self.root).invoke({"prompt": "a cat"})
        self.assertTrue(process.killed)
        self.assertEqual(list((self.root / "images").iterdir()), [])
