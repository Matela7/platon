import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from platon.backend.app import create_app
from platon.backend.desktop_runtime import image_generation_available, prepare_data_directory
from platon.agent.tools.execution import execution_python
from platon.backend import desktop_setup
from unittest.mock import MagicMock


class DesktopRuntimeTests(unittest.TestCase):
    def setUp(self):
        platform = patch.object(desktop_setup.sys, "platform", "linux")
        platform.start()
        self.addCleanup(platform.stop)

    def test_windows_setup_installs_image_files_after_gemma(self):
        from platon.backend import image_setup
        response = MagicMock()
        response.__enter__.return_value.read.return_value = '{"models":[{"name":"gemma4:e2b-it-qat"},{"name":"gemma4:26b-a4b-it-qat"}]}'
        with TemporaryDirectory() as directory, patch.object(desktop_setup.sys, "platform", "win32"), patch.object(desktop_setup.Path, "cwd", return_value=Path(directory)), patch.object(desktop_setup.ollama_setup, "wait_for_server"), patch.object(desktop_setup.urllib.request, "urlopen", return_value=response), patch.object(image_setup, "download", side_effect=lambda item, root, **kw: root / item.name) as download, patch.object(image_setup, "install_archive") as extract:
            desktop_setup.run_setup()
        self.assertEqual(desktop_setup._state["status"], "completed")
        self.assertEqual(download.call_count, len(image_setup.DOWNLOADS))
        self.assertEqual(extract.call_count, 2)

    def tearDown(self):
        desktop_setup._update(status="pending", message="", model=None, completed=0, total=0, error=None)

    def test_setup_truncated_pull_is_error_and_can_retry(self):
        tags = MagicMock()
        tags.__enter__.return_value.read.return_value = '{"models":[]}'
        pull = MagicMock()
        pull.__enter__.return_value.__iter__.return_value = iter([b'{"status":"downloading","completed":2,"total":10}\n'])
        with patch.object(desktop_setup.ollama_setup, "wait_for_server"), patch.object(desktop_setup.urllib.request, "urlopen", side_effect=[tags, pull]):
            desktop_setup.run_setup()
        self.assertEqual(desktop_setup._state["status"], "error")
        self.assertIn("before success", desktop_setup._state["error"])
        with patch.dict(os.environ, {"PLATON_SETUP_TOKEN": "token"}), patch.object(desktop_setup.threading, "Thread") as thread:
            result = desktop_setup.start("token")
            self.assertEqual(result["status"], "running")
            thread.assert_called_once()

    def test_setup_reports_pull_error(self):
        tags = MagicMock()
        tags.__enter__.return_value.read.return_value = '{"models":[]}'
        with patch.object(desktop_setup.ollama_setup, "wait_for_server"), patch.object(desktop_setup.urllib.request, "urlopen", side_effect=[tags, OSError("download failed")]):
            desktop_setup.run_setup()
        self.assertEqual(desktop_setup._state["status"], "error")
        self.assertEqual(desktop_setup._state["error"], "download failed")

    def test_setup_downloads_only_missing_model_and_verifies_both(self):
        before = MagicMock()
        before.__enter__.return_value.read.return_value = '{"models":[{"name":"gemma4:e2b-it-qat"}]}'
        pull = MagicMock()
        pull.__enter__.return_value.__iter__.return_value = iter([b'{"status":"success"}\n'])
        after = MagicMock()
        after.__enter__.return_value.read.return_value = '{"models":[{"name":"gemma4:e2b-it-qat"},{"name":"gemma4:26b-a4b-it-qat"}]}'
        with patch.object(desktop_setup.ollama_setup, "wait_for_server"), patch.object(desktop_setup.urllib.request, "urlopen", side_effect=[before, pull, after]) as request:
            desktop_setup.run_setup()
        self.assertEqual(desktop_setup._state["status"], "completed")
        self.assertIn(b'gemma4:26b-a4b-it-qat', request.call_args_list[1].args[0].data)
    def test_setup_is_authenticated_and_start_is_idempotent(self):
        with patch.dict(os.environ, {"PLATON_SETUP_TOKEN": "secret"}), patch.object(desktop_setup.threading, "Thread") as thread:
            desktop_setup._update(status="pending")
            with TestClient(create_app(document_factory=lambda: object())) as client:
                self.assertEqual(client.post("/setup/start").status_code, 403)
                headers = {"X-Platon-Setup-Token": "secret"}
                self.assertEqual(client.post("/setup/start", headers=headers).json()["status"], "running")
                client.post("/setup/start", headers=headers)
                self.assertEqual(thread.call_count, 1)
            desktop_setup._update(status="pending")

    def test_setup_skips_both_installed_models_without_pulling(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = '{"models":[{"name":"gemma4:e2b-it-qat"},{"name":"gemma4:26b-a4b-it-qat"}]}'
        with patch.object(desktop_setup.ollama_setup, "wait_for_server"), patch.object(desktop_setup.urllib.request, "urlopen", return_value=response) as request:
            desktop_setup.run_setup()
        self.assertEqual(request.call_count, 2)
        self.assertEqual(desktop_setup._state["status"], "completed")
        desktop_setup._update(status="pending")
    def test_data_directory_is_created_and_used_for_relative_paths(self):
        previous = Path.cwd()
        try:
            with TemporaryDirectory() as temporary:
                directory = (Path(temporary) / "data").resolve()
                with patch.dict(os.environ, {"PLATON_DATA_DIR": str(directory)}, clear=True):
                    self.assertEqual(prepare_data_directory(), directory.resolve())
                    self.assertEqual(Path.cwd(), directory.resolve())
                    self.assertEqual(Path(os.environ["PLATON_CHROMA_DIR"]), directory / "chroma_data")
                os.chdir(previous)
        finally:
            os.chdir(previous)

    def test_platform_capabilities(self):
        for platform, expected in (("win32", True), ("darwin", False), ("linux", False)):
            with self.subTest(platform=platform), patch.object(sys, "platform", platform):
                self.assertEqual(image_generation_available(), expected)

    def test_health_does_not_initialize_agent_or_require_ollama(self):
        def forbidden(**kwargs):
            raise AssertionError("Agent must not initialize for readiness")
        with TestClient(create_app(forbidden, lambda: object())) as client:
            self.assertEqual(client.get("/health").json(), {
                "status": "ok", "capabilities": {"image_generation": sys.platform == "win32"}})

    def test_frozen_backend_never_uses_itself_as_python(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "frozen", True, create=True):
            with self.assertRaisesRegex(RuntimeError, "PLATON_PYTHON_EXECUTABLE"):
                execution_python()
        with patch.dict(os.environ, {"PLATON_PYTHON_EXECUTABLE": sys.executable}):
            self.assertEqual(execution_python(), str(Path(sys.executable).resolve()))
