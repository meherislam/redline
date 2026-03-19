import io

import pytest
from httpx import AsyncClient

from tests.conftest import upload_document


class TestCreateDocument:
    async def test_upload_creates_document_with_chunks(self, client: AsyncClient):
        data = await upload_document(client)

        assert data["title"] == "Test Document"
        assert data["version"] == 1
        assert data["source_type"] == "txt"
        assert data["chunk_count"] == 5
        assert "id" in data
        assert "created_at" in data

    async def test_upload_without_file_returns_400(self, client: AsyncClient):
        response = await client.post("/documents", data={"title": "No File"})
        assert response.status_code == 400

    async def test_upload_empty_file_returns_400(self, client: AsyncClient):
        file = io.BytesIO(b"")
        response = await client.post(
            "/documents",
            data={"title": "Empty"},
            files={"file": ("empty.txt", file, "text/plain")},
        )
        assert response.status_code == 400

    async def test_upload_whitespace_only_returns_400(self, client: AsyncClient):
        file = io.BytesIO(b"   \n\n   \n\n   ")
        response = await client.post(
            "/documents",
            data={"title": "Whitespace"},
            files={"file": ("ws.txt", file, "text/plain")},
        )
        assert response.status_code == 400

    async def test_upload_non_txt_file_returns_400(self, client: AsyncClient):
        file = io.BytesIO(b"%PDF-1.4 fake pdf content")
        response = await client.post(
            "/documents",
            data={"title": "PDF"},
            files={"file": ("doc.pdf", file, "application/pdf")},
        )
        assert response.status_code == 400
        assert "plain text" in response.json()["detail"].lower()


class TestListDocuments:
    async def test_list_empty(self, client: AsyncClient):
        response = await client.get("/documents")
        assert response.status_code == 200
        data = response.json()
        assert data["documents"] == []

    async def test_list_after_upload(self, client: AsyncClient):
        await upload_document(client, title="Doc A")
        await upload_document(client, title="Doc B")

        response = await client.get("/documents")
        assert response.status_code == 200
        docs = response.json()["documents"]
        assert len(docs) == 2
        titles = {d["title"] for d in docs}
        assert titles == {"Doc A", "Doc B"}

class TestGetDocument:
    async def test_get_returns_document(self, client: AsyncClient):
        created = await upload_document(client)

        response = await client.get(f"/documents/{created['id']}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == created["id"]
        assert data["title"] == "Test Document"
        assert data["version"] == 1
        assert data["chunk_count"] == 5

    async def test_get_nonexistent_returns_404(self, client: AsyncClient):
        response = await client.get("/documents/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404


class TestGetChunks:
    async def test_get_chunks_returns_ordered_content(self, client: AsyncClient):
        created = await upload_document(client)

        response = await client.get(f"/documents/{created['id']}/chunks")
        assert response.status_code == 200

        data = response.json()
        assert data["total_chunks"] == 5
        assert data["page"] == 1
        assert len(data["chunks"]) == 5

        # Verify ordering
        positions = [c["position"] for c in data["chunks"]]
        assert positions == [1, 2, 3, 4, 5]

        # First chunk content
        assert "first paragraph" in data["chunks"][0]["content"]

    async def test_pagination(self, client: AsyncClient):
        created = await upload_document(client)

        response = await client.get(f"/documents/{created['id']}/chunks?page=1&page_size=2")
        data = response.json()
        assert len(data["chunks"]) == 2
        assert data["total_chunks"] == 5
        assert data["page"] == 1

        response = await client.get(f"/documents/{created['id']}/chunks?page=3&page_size=2")
        data = response.json()
        assert len(data["chunks"]) == 1  # 5th chunk
