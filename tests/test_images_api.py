"""Exercise generated image endpoints against isolated local files."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from fastapi.testclient import TestClient

from platon.backend.app import create_app
from platon.backend.services.agent_runtime_service import AgentRuntimeService
from platon.backend.services.image_service import ImageService


class ImageAPITests(unittest.TestCase):
    def test_list_view_download_and_delete_from_active_backend(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image_dir = root / "images"
            image_dir.mkdir()
            filename = "0123456789abcdef0123456789abcdef.png"
            png = b"\x89PNG\r\n\x1a\nexample"
            (image_dir / filename).write_bytes(png)
            (image_dir / "not-generated.txt").write_text("keep", encoding="utf-8")
            service = Mock(spec=AgentRuntimeService)
            service.thread_id = "test"
            service.get_config.return_value = {"agent_config": {"backend_root": str(root)}, "orchestrator_config": {}}

            with TestClient(create_app(lambda **kwargs: service)) as client:
                self.assertEqual(client.get("/api/v1/images").status_code, 409)
                self.assertEqual(client.post("/api/v1/agent-runtime/initialize", json={}).status_code, 200)
                listing = client.get("/api/v1/images")
                self.assertEqual(listing.status_code, 200)
                self.assertEqual([item["filename"] for item in listing.json()["data"]], [filename])
                self.assertEqual(listing.json()["data"][0]["size_bytes"], len(png))
                self.assertEqual(listing.json()["status"], "success")

                schema = client.get("/openapi.json").json()
                image_get = schema["paths"]["/api/v1/images/{filename}"]["get"]
                filename_schema = next(p["schema"] for p in image_get["parameters"] if p["name"] == "filename")
                self.assertEqual(filename_schema["minLength"], 36)
                self.assertIn("pattern", filename_schema)

                view = client.get(f"/api/v1/images/{filename}")
                self.assertEqual(view.content, png)
                self.assertEqual(view.headers["content-type"], "image/png")
                self.assertTrue(view.headers["content-disposition"].startswith("inline;"))
                download = client.get(f"/api/v1/images/{filename}?download=true")
                self.assertEqual(download.content, png)
                self.assertTrue(download.headers["content-disposition"].startswith("attachment;"))

                self.assertEqual(client.get("/api/v1/images/not-an-image.png").status_code, 422)
                self.assertEqual(client.delete("/api/v1/images/%2e%2e%5cnot-generated.txt").status_code, 422)
                self.assertEqual(client.get(f"/api/v1/images/{'a' * 32}.png").status_code, 404)
                self.assertTrue(client.delete(f"/api/v1/images/{filename}").json()["data"]["deleted"])
                self.assertEqual(client.get(f"/api/v1/images/{filename}").status_code, 404)
                self.assertEqual(client.delete(f"/api/v1/images/{filename}").status_code, 404)
                self.assertTrue((image_dir / "not-generated.txt").exists())

                other = root / "other"
                other.mkdir()
                service.get_config.return_value["agent_config"]["backend_root"] = str(other)
                self.assertEqual(client.get("/api/v1/images").json()["data"], [])

    def test_service_validates_filename_even_without_router(self):
        with TemporaryDirectory() as directory:
            service = ImageService(directory)
            for filename in ("../escape.png", "a" * 32 + ".png\n", "wrong.png"):
                with self.assertRaises(ValueError):
                    service.get_image(filename)

    def test_symlink_is_not_listed_read_or_deleted(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            images = root / "images"
            images.mkdir()
            outside = root / "outside.png"
            outside.write_bytes(b"outside")
            filename = "a" * 32 + ".png"
            try:
                (images / filename).symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"Cannot create symlink on this system: {exc}")
            service = Mock(spec=AgentRuntimeService)
            service.thread_id = "test"
            service.get_config.return_value = {"agent_config": {"backend_root": str(root)}}
            with TestClient(create_app(lambda **kwargs: service)) as client:
                client.post("/api/v1/agent-runtime/initialize", json={})
                self.assertEqual(client.get("/api/v1/images").json()["data"], [])
                self.assertEqual(client.get(f"/api/v1/images/{filename}").status_code, 404)
                self.assertEqual(client.delete(f"/api/v1/images/{filename}").status_code, 404)
                self.assertEqual(outside.read_bytes(), b"outside")
