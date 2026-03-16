import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import Chunk, Document
from app.schemas import SearchResponse, SearchResultItem

router = APIRouter(tags=["search"])

_TS_OPTIONS = "StartSel=<mark>, StopSel=</mark>, MaxWords=35, MinWords=15"


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1),
    document_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    ts_query = func.plainto_tsquery("english", q)

    stmt = (
        select(
            Chunk.document_id,
            Document.title.label("document_title"),
            Chunk.id.label("chunk_id"),
            func.ts_headline("english", Chunk.content, ts_query, _TS_OPTIONS).label("snippet"),
            func.ts_rank(Chunk.search_vector, ts_query).label("rank"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.search_vector.op("@@")(ts_query))
    )

    if document_id is not None:
        stmt = stmt.where(Chunk.document_id == document_id)

    stmt = stmt.order_by(literal_column("rank").desc()).limit(50)

    result = await db.execute(stmt)
    rows = result.all()

    return SearchResponse(
        query=q,
        results=[
            SearchResultItem(
                document_id=row.document_id,
                document_title=row.document_title,
                chunk_id=row.chunk_id,
                snippet=row.snippet,
                rank=round(float(row.rank), 4),
            )
            for row in rows
        ],
    )
