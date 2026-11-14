import unittest
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from platon.backend.routers.documents import router
from platon.backend.services.document_service import DocumentService


class DocumentsAPITests(unittest.TestCase):
    def test_upload_list_delete_without_runtime(self):
        with TemporaryDirectory() as directory:
            manager = Mock()
            manager.client.get_collection.return_value.metadata = {}
            app = FastAPI()
            app.state.document_service = DocumentService(directory, manager)
            app.include_router(router)
            with TestClient(app) as client:
                response = client.post('/api/v1/documents?filename=a.txt', content=b'hello')
                self.assertEqual(response.status_code, 201, response.text)
                identifier = response.json()['data']['id']
                self.assertIn('hello', app.state.document_service.build_attachment_context([identifier]))
                response = client.get('/api/v1/documents?collection=documents')
                self.assertEqual(response.json()['data'][0]['id'], identifier)
                response = client.delete('/api/v1/documents/' + identifier)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(client.get('/api/v1/documents').json()['data'], [])
                self.assertEqual(client.delete('/api/v1/documents/' + identifier).status_code, 404)
                self.assertEqual(client.post('/api/v1/documents?filename=a.exe', content=b'a').status_code, 422)
                with patch('platon.backend.routers.documents.MAX_UPLOAD_BYTES', 2):
                    self.assertEqual(client.post('/api/v1/documents?filename=a.txt', content=b'abc').status_code, 413)
