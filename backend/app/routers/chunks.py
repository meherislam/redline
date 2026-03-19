import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import ChunkListResponse, ChunkResponse
from app.services.documents import get_chunks_paginated
from app.services.exceptions import DocumentNotFoundError

router = APIRouter(prefix="/documents/{document_id}/chunks", tags=["chunks"])


@router.get("", response_model=ChunkListResponse)
async def handle_get_chunks(
    document_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    try:
        chunks, total_chunks = await get_chunks_paginated(
            db, document_id, page, page_size,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")

    return ChunkListResponse(
        chunks=[ChunkResponse.model_validate(c) for c in chunks],
        page=page,
        page_size=page_size,
        total_chunks=total_chunks,
    )
