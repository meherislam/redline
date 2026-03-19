import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas import SuggestRequest, SuggestResponse
from app.services.suggest import suggest_replacement
from app.services.exceptions import ChunkNotFoundError, DocumentNotFoundError

router = APIRouter(prefix="/documents/{document_id}/suggest", tags=["suggest"])


@router.post("", response_model=SuggestResponse)
async def handle_suggest_replacement(
    document_id: uuid.UUID,
    body: SuggestRequest,
    db: AsyncSession = Depends(get_db),
):
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="AI suggestions are not available. ANTHROPIC_API_KEY is not configured.",
        )

    try:
        suggestion = await suggest_replacement(
            db, document_id, body.chunk_id, body.selected_text, body.instruction,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")
    except ChunkNotFoundError:
        raise HTTPException(status_code=404, detail="The selected text could not be located.")

    return SuggestResponse(suggestion=suggestion)
