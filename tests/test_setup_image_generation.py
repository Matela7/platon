"""Offline checks for image setup helpers; the installer is not executed."""

import hashlib
import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from setup_image_generation import Download, download, install_archive


class SetupImageGenerationTests(unittest.TestCase):
    def test_resumes_partial_download_and_checks_hash(self):
        data = b"model data"
        item = Download("model.gguf", "https://example.test/model", hashlib.sha256(data).hexdigest())
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "model.gguf.part").write_bytes(data[:5])
            response = io.BytesIO(data[5:])
            response.status = 206
            response.headers = {"Content-Range": "bytes 5-9/10"}
            with patch("setup_image_generation.urllib.request.urlopen", return_value=response) as fetch:
                result = download(item, root)
            self.assertEqual(result.read_bytes(), data)
            self.assertEqual(fetch.call_args.args[0].get_header("Range"), "bytes=5-")

    def test_existing_file_conflict_is_preserved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "model.gguf"
            target.write_bytes(b"user data")
            item = Download(target.name, "https://example.test/model", hashlib.sha256(b"other").hexdigest())
            with self.assertRaises(RuntimeError):
                download(item, root)
            self.assertEqual(target.read_bytes(), b"user data")

    def test_interrupted_transfer_retries_from_last_byte(self):
        data = b"model data"
        item = Download("model.gguf", "https://example.test/model", hashlib.sha256(data).hexdigest())
        first = io.BytesIO(data[:5])
        first.status = 200
        first.headers = {"Content-Length": "10"}
        second = io.BytesIO(data[5:])
        second.status = 206
        second.headers = {"Content-Range": "bytes 5-9/10", "Content-Length": "5"}
        with TemporaryDirectory() as directory, patch(
            "setup_image_generation.urllib.request.urlopen", side_effect=[first, second]
        ) as fetch, patch("setup_image_generation.time.sleep"):
            result = download(item, Path(directory))
            self.assertEqual(result.read_bytes(), data)
            self.assertEqual(fetch.call_args.args[0].get_header("Range"), "bytes=5-")

    def test_archive_rejects_traversal_and_conflicts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "release.zip"
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("../escape.dll", b"x")
            with self.assertRaises(RuntimeError):
                install_archive(archive, root)
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("sd-cli.exe", b"new")
            (root / "sd-cli.exe").write_bytes(b"existing")
            with self.assertRaises(RuntimeError):
                install_archive(archive, root)
            self.assertEqual((root / "sd-cli.exe").read_bytes(), b"existing")
