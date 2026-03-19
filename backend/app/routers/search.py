import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import SearchResponse, SearchResultItem
from app.services.search import search_chunks

router = APIRouter(prefix="/documents", tags=["search"])


@router.get("/search", response_model=SearchResponse)
async def handle_search(
    query: str = Query(..., alias="q", min_length=1),
    document_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    rows = await search_chunks(db, query, document_id)

    return SearchResponse(
        query=query,
        results=[
            SearchResultItem(
                document_id=row.document_id,
                document_title=row.document_title,
                chunk_id=row.chunk_id,
                chunk_position=row.chunk_position,
                snippet=row.snippet,
                rank=round(float(row.rank), 4),
            )
            for row in rows
        ],
    )
