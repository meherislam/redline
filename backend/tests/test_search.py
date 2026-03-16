import pytest
from httpx import AsyncClient

from tests.conftest import upload_document


LEGAL_TEXT = (
    "This Agreement is entered into as of March 1st, 2026, between Acme Corporation and Globex Industries.\n\n"
    "The Provider agrees to deliver software development, system integration, and ongoing technical support.\n\n"
    "The indemnification clause shall protect the Client from any claims arising from the Provider's negligence.\n\n"
    "All intellectual property created during the performance of this Agreement shall be owned by the Client.\n\n"
    "Neither party shall be liable for any indirect, incidental, or consequential damages arising out of this Agreement."
)

NDA_TEXT = (
    "This Non-Disclosure Agreement is made between Alpha Corp and Beta LLC.\n\n"
    "Confidential Information means any non-public data shared between the parties.\n\n"
    "The indemnification obligations under this NDA shall survive termination for three years.\n\n"
    "Neither party may assign this NDA without prior written consent."
)


class TestBasicSearch:
    async def test_single_term_returns_results(self, client: AsyncClient):
        await upload_document(client, title="Legal Doc", text=LEGAL_TEXT)

        response = await client.get("/search?q=indemnification")
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "indemnification"
        assert len(data["results"]) >= 1

    async def test_multi_word_query(self, client: AsyncClient):
        await upload_document(client, title="Legal Doc", text=LEGAL_TEXT)

        response = await client.get("/search?q=intellectual+property")
        assert response.status_code == 200
        assert len(response.json()["results"]) >= 1

    async def test_no_results_for_unmatched_query(self, client: AsyncClient):
        await upload_document(client, title="Legal Doc", text=LEGAL_TEXT)

        response = await client.get("/search?q=cryptocurrency")
        assert response.status_code == 200
        assert response.json()["results"] == []


class TestSearchSnippets:
    async def test_snippet_contains_mark_tags(self, client: AsyncClient):
        await upload_document(client, title="Legal Doc", text=LEGAL_TEXT)

        response = await client.get("/search?q=indemnification")
        results = response.json()["results"]
        assert len(results) >= 1

        snippet = results[0]["snippet"]
        assert "<mark>" in snippet
        assert "</mark>" in snippet

    async def test_result_includes_document_metadata(self, client: AsyncClient):
        doc = await upload_document(client, title="My Legal Doc", text=LEGAL_TEXT)

        response = await client.get("/search?q=indemnification")
        result = response.json()["results"][0]

        assert result["document_id"] == doc["id"]
        assert result["document_title"] == "My Legal Doc"
        assert "chunk_id" in result
        assert "rank" in result


class TestSearchScoping:
    async def test_search_across_all_documents(self, client: AsyncClient):
        await upload_document(client, title="Legal Doc", text=LEGAL_TEXT)
        await upload_document(client, title="NDA Doc", text=NDA_TEXT)

        response = await client.get("/search?q=indemnification")
        results = response.json()["results"]

        # Both documents mention indemnification
        doc_ids = {r["document_id"] for r in results}
        assert len(doc_ids) == 2

    async def test_search_scoped_to_single_document(self, client: AsyncClient):
        legal = await upload_document(client, title="Legal Doc", text=LEGAL_TEXT)
        await upload_document(client, title="NDA Doc", text=NDA_TEXT)

        response = await client.get(f"/search?q=indemnification&document_id={legal['id']}")
        results = response.json()["results"]

        # Only results from the scoped document
        doc_ids = {r["document_id"] for r in results}
        assert doc_ids == {legal["id"]}

    async def test_scoped_search_no_results_in_other_doc(self, client: AsyncClient):
        legal = await upload_document(client, title="Legal Doc", text=LEGAL_TEXT)
        nda = await upload_document(client, title="NDA Doc", text=NDA_TEXT)

        # "Alpha Corp" only appears in the NDA
        response = await client.get(f"/search?q=Alpha+Corp&document_id={legal['id']}")
        assert response.json()["results"] == []

        # But found when scoped to the NDA
        response = await client.get(f"/search?q=Alpha+Corp&document_id={nda['id']}")
        assert len(response.json()["results"]) >= 1


class TestSearchRanking:
    async def test_results_ordered_by_relevance(self, client: AsyncClient):
        await upload_document(client, title="Legal Doc", text=LEGAL_TEXT)

        response = await client.get("/search?q=agreement")
        results = response.json()["results"]

        if len(results) > 1:
            ranks = [r["rank"] for r in results]
            assert ranks == sorted(ranks, reverse=True), "Results should be ordered by descending rank"
