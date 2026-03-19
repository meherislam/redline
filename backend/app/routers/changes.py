import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import (
    ApplyChangesRequest,
    ApplyChangesResponse,
    ChangeActionResponse,
    ChangeHistoryItem,
    ChangeHistoryResponse,
)
from app.services.changes import (
    accept_change,
    apply_changes,
    get_change_history,
    reject_change,
)
from app.services.exceptions import (
    ChangeConflictError,
    ChangeNotFoundError,
    ChangeValidationError,
    DocumentNotFoundError,
)

router = APIRouter(prefix="/documents/{document_id}/changes", tags=["changes"])


@router.post("", response_model=ApplyChangesResponse)
async def handle_apply_changes(
    document_id: uuid.UUID,
    body: ApplyChangesRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        applied = await apply_changes(
            db, document_id, body.changes,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")
    except ChangeValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ApplyChangesResponse(
        applied=applied,
    )


@router.get("", response_model=ChangeHistoryResponse)
async def handle_get_change_history(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        changes = await get_change_history(db, document_id)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")

    return ChangeHistoryResponse(
        changes=[ChangeHistoryItem.model_validate(c) for c in changes]
    )


@router.patch("/{change_id}/accept", response_model=ChangeActionResponse)
async def handle_accept_change(
    document_id: uuid.UUID,
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        change, group_change_ids = await accept_change(db, document_id, change_id)
    except ChangeNotFoundError:
        raise HTTPException(status_code=404, detail="Change not found.")
    except ChangeValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ChangeActionResponse(
        id=change.id,
        status=change.status,
        group_change_ids=group_change_ids,
    )


@router.patch("/{change_id}/reject", response_model=ChangeActionResponse)
async def handle_reject_change(
    document_id: uuid.UUID,
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        change, group_change_ids = await reject_change(db, document_id, change_id)
    except ChangeNotFoundError:
        raise HTTPException(status_code=404, detail="Change not found.")
    except ChangeValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ChangeConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return ChangeActionResponse(
        id=change.id,
        status=change.status,
        group_change_ids=group_change_ids,
    )
