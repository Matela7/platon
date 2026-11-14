"""Exercise real workspace virtual environments and bounded deletion."""

import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from platon.agent.tools.execution import create_execution_tools


class ExecutionVenvTests(unittest.TestCase):
    def test_create_reuse_delete_and_recreate_with_shell_and_python(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "workspace with spaces"
            tools = {t.name: t for t in create_execution_tools(root)}
            original_env = dict(os.environ)
            original_cwd = Path.cwd()
            self.assertFalse((root / "venv").exists())
            output = tools["run_python"].invoke({"code": (
                "import json, os, sys; from pathlib import Path; "
                "print(json.dumps([sys.prefix, str(Path.cwd()), os.environ['VIRTUAL_ENV']]))"
            )})
            prefix, cwd, virtual_env = json.loads(output)
            self.assertEqual(Path(prefix), root / "venv")
            self.assertEqual(Path(cwd), root)
            self.assertEqual(Path(virtual_env), root / "venv")
            marker = root / "venv" / "reuse-marker"
            marker.write_text("preserve", encoding="utf-8")
            tools["create_venv"].invoke({})
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
            output = tools["run_shell"].invoke({"command": 'python -c "import sys; print(sys.prefix)"'})
            self.assertEqual(Path(output.strip()), root / "venv")
            pip = tools["run_shell"].invoke({"command": "pip --version"})
            self.assertIn(str(root / "venv").lower(), pip.lower())
            keep = root / "keep.txt"
            keep.write_text("keep", encoding="utf-8")
            tools["delete_venv"].invoke({})
            self.assertFalse((root / "venv").exists())
            self.assertEqual(keep.read_text(encoding="utf-8"), "keep")
            self.assertIn("No Python virtual environment", tools["delete_venv"].invoke({}))
            output = tools["run_shell"].invoke({"command": 'python -c "import sys; print(sys.prefix)"'})
            self.assertEqual(Path(output.strip()), root / "venv")
            self.assertFalse(marker.exists())
            self.assertEqual(dict(os.environ), original_env)
            self.assertEqual(Path.cwd(), original_cwd)

    def test_does_not_overwrite_or_delete_an_unrelated_directory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            venv = root / "venv"
            venv.mkdir()
            marker = venv / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            tools = {t.name: t for t in create_execution_tools(root)}
            for name in ("create_venv", "delete_venv", "run_python"):
                args = {"code": "raise RuntimeError('must not run')"} if name == "run_python" else {}
                message = tools[name].invoke({"name": name, "args": args, "id": name, "type": "tool_call"})
                self.assertEqual(message.status, "error")
                self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_refuses_linked_environment_outside_workspace(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.mkdir()
            marker = outside / "pyvenv.cfg"
            marker.write_text("keep", encoding="utf-8")
            link = root / "venv"
            if os.name == "nt":
                subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                               check=True, capture_output=True)
            else:
                link.symlink_to(outside, target_is_directory=True)
            tools = {t.name: t for t in create_execution_tools(root)}
            for name in ("create_venv", "delete_venv"):
                message = tools[name].invoke({"name": name, "args": {}, "id": name, "type": "tool_call"})
                self.assertEqual(message.status, "error")
                self.assertIn("linked venv directory", message.content)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_creation_failure_prevents_user_code_execution(self):
        with TemporaryDirectory() as directory:
            tools = {t.name: t for t in create_execution_tools(Path(directory))}
            with patch("platon.agent.tools.execution.subprocess.run", return_value=
                       subprocess.CompletedProcess([], 1, "creation failed", "")) as run:
                message = tools["run_python"].invoke({
                    "name": "run_python", "args": {"code": "print('must not run')"},
                    "id": "python", "type": "tool_call",
                })
            self.assertEqual(message.status, "error")
            self.assertIn("creation failed", message.content)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][1:], ["-m", "venv", "venv"])


if __name__ == "__main__":
    unittest.main()
