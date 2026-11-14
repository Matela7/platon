import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from platon.backend.services.document_service import DocumentService, MAX_ATTACHMENT_CHARS


class DocumentServiceTests(unittest.TestCase):
    def test_persistence_context_and_delete(self):
        with TemporaryDirectory() as directory:
            manager = Mock()
            service = DocumentService(directory, manager)
            document = service.upload('../notes.txt', b'important content')
            self.assertEqual(document['filename'], 'notes.txt')
            reopened = DocumentService(directory, manager)
            self.assertIn('important content', reopened.build_attachment_context([document['id']]))
            self.assertEqual(reopened.list_documents("documents"), [document])
            manager.client.get_collection.return_value.metadata = {}
            self.assertEqual(reopened.delete(document['id']), document)
            manager.client.get_collection.return_value.delete.assert_called_once()
            self.assertFalse(Path(document['path']).exists())
            self.assertEqual(reopened.list_documents(), [])

    def test_limits_and_invalid_documents(self):
        with TemporaryDirectory() as directory:
            service = DocumentService(directory, Mock())
            for name, content in [('a.exe', b'a'), ('a.txt', b''), ('a.txt', b' '), ('a.txt', b'\xff'), ('a.docx', b'bad')]:
                with self.assertRaises(ValueError):
                    service.upload(name, content)
            with self.assertRaises(ValueError):
                service.resolve_attachments(['../bad'])
            with self.assertRaises(FileNotFoundError):
                service.resolve_attachments(['00000000-0000-0000-0000-000000000000'])
            document = service.upload('long.txt', b'x' * (MAX_ATTACHMENT_CHARS + 1))
            with self.assertRaises(ValueError):
                service.build_attachment_context([document['id']])

    def test_failed_ingestion_cleanup(self):
        with TemporaryDirectory() as directory:
            manager = Mock()
            manager.add_document_to_collection.side_effect = RuntimeError('offline')
            with self.assertRaises(RuntimeError):
                DocumentService(directory, manager).upload('a.txt', b'hello')
            self.assertEqual(list(Path(directory).glob("*.txt")), [])
    def test_manifest_failure_compensates_index(self):
        with TemporaryDirectory() as directory:
            manager = Mock()
            manager.client.get_collection.return_value.metadata = {}
            with patch.object(DocumentService, '_connect', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    DocumentService(directory, manager).upload('a.txt', b'hello')
            manager.client.get_collection.return_value.delete.assert_called_once()
            self.assertEqual(list(Path(directory).glob("*.txt")), [])
