import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import OccurrenceItem, OccurrencesResponse
from app.services.occurrences import find_occurrences
from app.services.exceptions import DocumentNotFoundError

router = APIRouter(prefix="/documents/{document_id}/occurrences", tags=["occurrences"])


@router.get("", response_model=OccurrencesResponse)
async def handle_get_occurrences(
    document_id: uuid.UUID,
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await find_occurrences(db, document_id, q.strip())
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")

    return OccurrencesResponse(
        term=q.strip(),
        matches=[
            OccurrenceItem(**row)
            for row in rows
        ],
        total_chunks=len(rows),
    )
