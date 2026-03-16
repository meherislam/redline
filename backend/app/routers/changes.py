import uuid

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import (
    ApplyChangesRequest,
    ApplyChangesResponse,
    ChangeActionResponse,
    ChangeHistoryItem,
    ChangeHistoryResponse,
    ChunkContent,
)
from app.services import changes as change_service
from app.services.exceptions import (
    ChangeConflictError,
    ChangeNotFoundError,
    ChangeValidationError,
    DocumentNotFoundError,
    VersionConflictError,
)

router = APIRouter(prefix="/documents/{document_id}/changes", tags=["changes"])


@router.post("", response_model=ApplyChangesResponse)
async def apply_changes(
    document_id: uuid.UUID,
    body: ApplyChangesRequest,
    db: AsyncSession = Depends(get_db),
    if_match: str | None = Header(None),
):
    try:
        version, applied, chunks = await change_service.apply_changes(
            db, document_id, body.version, body.changes,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")
    except VersionConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ChangeValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApplyChangesResponse(
        version=version,
        applied=applied,
        chunks=[ChunkContent.model_validate(c) for c in chunks],
    )


@router.get("", response_model=ChangeHistoryResponse)
async def get_change_history(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        changes = await change_service.get_change_history(db, document_id)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")

    return ChangeHistoryResponse(
        changes=[ChangeHistoryItem.model_validate(c) for c in changes]
    )


@router.patch("/{change_id}/accept", response_model=ChangeActionResponse)
async def accept_change(
    document_id: uuid.UUID,
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        change, chunks, group_change_ids = await change_service.accept_change(db, document_id, change_id)
    except ChangeNotFoundError:
        raise HTTPException(status_code=404, detail="Change not found.")
    except ChangeValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ChangeActionResponse(
        id=change.id,
        status=change.status,
        chunks=[ChunkContent.model_validate(c) for c in chunks],
        group_change_ids=group_change_ids,
    )


@router.patch("/{change_id}/reject", response_model=ChangeActionResponse)
async def reject_change(
    document_id: uuid.UUID,
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        change, chunks, group_change_ids = await change_service.reject_change(db, document_id, change_id)
    except ChangeNotFoundError:
        raise HTTPException(status_code=404, detail="Change not found.")
    except ChangeValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ChangeConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return ChangeActionResponse(
        id=change.id,
        status=change.status,
        chunks=[ChunkContent.model_validate(c) for c in chunks],
        group_change_ids=group_change_ids,
    )
