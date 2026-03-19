from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.models import ChangeStatus


class ChangeRequest(BaseModel):
    chunk_id: UUID
    old_text: str
    new_text: str
    occurrence: int = 1
    group_id: UUID | None = None


class ApplyChangesRequest(BaseModel):
    changes: list[ChangeRequest] = Field(min_length=1)


class ChangeAppliedItem(BaseModel):
    chunk_id: UUID
    old_text: str
    new_text: str
    status: str = "applied"  # not a ChangeStatus — "applied" is a response-only value
    change_group_id: UUID


class ApplyChangesResponse(BaseModel):
    applied: list[ChangeAppliedItem]


class ChangeHistoryItem(BaseModel):
    id: UUID
    chunk_id: UUID
    old_text: str
    new_text: str
    occurrence: int
    old_text_offset: int | None = None
    status: ChangeStatus
    change_group_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ChangeHistoryResponse(BaseModel):
    changes: list[ChangeHistoryItem]


class ChangeActionResponse(BaseModel):
    id: UUID
    status: ChangeStatus
    group_change_ids: list[UUID]
