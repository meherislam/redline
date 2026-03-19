import uuid

from sqlalchemy import select, func, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Chunk, Document

_TS_OPTIONS = "StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=15"


async def search_chunks(
    db: AsyncSession,
    query: str,
    document_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list:
    ts_query = func.plainto_tsquery("english", query)

    stmt = (
        select(
            Chunk.document_id,
            Document.title.label("document_title"),
            Chunk.id.label("chunk_id"),
            Chunk.position.label("chunk_position"),
            func.ts_headline("english", Chunk.content, ts_query, _TS_OPTIONS).label("snippet"),
            func.ts_rank(Chunk.search_vector, ts_query).label("rank"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.search_vector.op("@@")(ts_query))
    )

    if document_id is not None:
        stmt = stmt.where(Chunk.document_id == document_id)

    stmt = stmt.order_by(literal_column("rank").desc()).limit(limit)

    result = await db.execute(stmt)
    return result.all()
