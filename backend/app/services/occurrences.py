import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Chunk
from app.services.documents import get_document_or_raise

SNIPPET_WINDOW = 60


def _build_snippet(content: str, term: str) -> str:
    """Extract a short window of text around the first occurrence of term."""
    idx = content.find(term)
    if idx == -1:
        return content[:SNIPPET_WINDOW * 2]
    start = max(0, idx - SNIPPET_WINDOW)
    end = min(len(content), idx + len(term) + SNIPPET_WINDOW)
    snippet = content[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    return snippet


async def find_occurrences(
    db: AsyncSession,
    document_id: uuid.UUID,
    term: str,
) -> list:
    """Find chunks containing the exact term (case-sensitive) using SQL LIKE.

    Database filters with LIKE — only matching rows are returned.
    Snippets are built from the returned content.
    """
    await get_document_or_raise(db, document_id)

    stmt = (
        select(Chunk.id, Chunk.position, Chunk.content)
        .where(
            Chunk.document_id == document_id,
            Chunk.content.contains(term),
        )
        .order_by(Chunk.position)
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {"chunk_id": row.id, "chunk_position": row.position, "snippet": _build_snippet(row.content, term)}
        for row in rows
    ]
