import time

from httpx import AsyncClient

from tests.conftest import upload_document


def generate_large_document(num_paragraphs: int = 1000) -> str:
    """Generate a ~10MB document with realistic paragraph content."""
    paragraphs = []
    topics = [
        "The indemnification clause shall protect all parties from claims arising out of negligence, willful misconduct, or breach of contractual obligations. This protection extends to affiliates, subsidiaries, and their respective officers, directors, and employees.",
        "Confidential Information includes all non-public business data, technical specifications, financial records, customer lists, and proprietary methodologies disclosed during the course of this engagement.",
        "The service provider agrees to maintain commercially reasonable security measures including encryption at rest and in transit, multi-factor authentication, regular vulnerability assessments, and comprehensive audit logging.",
        "Payment terms require settlement within forty-five days of invoice receipt. Late payments accrue interest at one and one-half percent per month. All fees are denominated in United States Dollars.",
        "Force majeure events including natural disasters, pandemics, acts of war, terrorism, government actions, and telecommunications failures shall excuse performance delays for the duration of the event.",
        "Intellectual property rights in all deliverables shall vest in the client upon full payment. The provider retains rights to pre-existing tools, frameworks, and methodologies used in service delivery.",
        "The governing law of this agreement shall be the laws of the State of Delaware without regard to conflict of laws provisions. Disputes shall be resolved through binding arbitration.",
        "Data protection obligations require compliance with GDPR, CCPA, and all applicable privacy regulations. Personal data must be processed lawfully, stored securely, and deleted upon request.",
        "The warranty period extends for ninety days following acceptance of each deliverable. Defects reported during this period shall be corrected at no additional cost to the client.",
        "Non-solicitation provisions prevent either party from recruiting employees or contractors of the other party for a period of twelve months following termination of this agreement.",
    ]

    for i in range(num_paragraphs):
        topic = topics[i % len(topics)]
        paragraphs.append(f"Section {i + 1}. {topic}")

    return "\n\n".join(paragraphs)


class TestLargeDocumentIngestion:
    async def test_ingest_large_document(self, client: AsyncClient):
        """A ~10MB document with ~1000 paragraphs should ingest successfully."""
        text = generate_large_document(1000)
        assert len(text) > 200_000  # Sanity check it's substantial

        start = time.perf_counter()
        doc = await upload_document(client, title="Large Document", text=text)
        elapsed = time.perf_counter() - start

        assert doc["chunk_count"] == 1000
        print(f"\nIngestion: {doc['chunk_count']} chunks in {elapsed:.2f}s")

    async def test_paginated_read_of_large_document(self, client: AsyncClient):
        """Reading paginated chunks from a large document should be fast."""
        text = generate_large_document(500)
        doc = await upload_document(client, title="Paginated Doc", text=text)

        start = time.perf_counter()
        response = await client.get(f"/documents/{doc['id']}/chunks?page=1&page_size=50")
        elapsed = time.perf_counter() - start

        data = response.json()
        assert len(data["chunks"]) == 50
        assert data["total_chunks"] == 500
        print(f"\nPaginated read (50 chunks): {elapsed:.3f}s")


class TestSearchPerformance:
    async def test_search_across_large_document(self, client: AsyncClient):
        """Full-text search over 1000 chunks should use the GIN index and be fast."""
        text = generate_large_document(1000)
        await upload_document(client, title="Search Perf Doc", text=text)

        start = time.perf_counter()
        response = await client.get("/documents/search?q=indemnification")
        elapsed = time.perf_counter() - start

        results = response.json()["results"]
        assert len(results) > 0
        print(f"\nSearch across 1000 chunks: {len(results)} results in {elapsed:.3f}s")

    async def test_search_across_multiple_documents(self, client: AsyncClient):
        """Search across several large documents."""
        text = generate_large_document(100)
        for i in range(5):
            await upload_document(client, title=f"Multi Doc {i}", text=text)

        start = time.perf_counter()
        response = await client.get("/documents/search?q=arbitration")
        elapsed = time.perf_counter() - start

        results = response.json()["results"]
        doc_ids = {r["document_id"] for r in results}
        assert len(doc_ids) == 5
        print(f"\nSearch across 5 docs (500 total chunks): {len(results)} results in {elapsed:.3f}s")


class TestBulkChangePerformance:
    async def test_bulk_replace_50_changes(self, client: AsyncClient):
        """Apply 50 changes in a single atomic request."""
        text = generate_large_document(200)
        doc = await upload_document(client, title="Bulk Change Doc", text=text)

        # Get chunks to build change requests
        chunks_resp = await client.get(f"/documents/{doc['id']}/chunks?page=1&page_size=100")
        chunks = chunks_resp.json()["chunks"]

        # Build 50 changes targeting different chunks
        changes = []
        for i in range(50):
            chunk = chunks[i % len(chunks)]
            # Each generated paragraph starts with "Section N."
            section_num = chunk["position"]
            changes.append({
                "chunk_id": chunk["id"],
                "old_text": f"Section {section_num}.",
                "new_text": f"Article {section_num}.",
            })

        start = time.perf_counter()
        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={"version": 1, "changes": changes},
        )
        elapsed = time.perf_counter() - start

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 2
        assert len(data["applied"]) == 50
        print(f"\nBulk replace (50 changes): {elapsed:.3f}s")

        # Verify changes actually applied
        assert any("Article" in c["content"] for c in data["chunks"])
