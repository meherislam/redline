from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.core.models import SourceType


class DocumentResponse(BaseModel):
    id: UUID
    title: str
    version: int
    source_type: SourceType
    chunk_count: int
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class DocumentCreateResponse(BaseModel):
    id: UUID
    title: str
    version: int
    source_type: SourceType
    chunk_count: int
    created_at: datetime


class DocumentListItem(BaseModel):
    id: UUID
    title: str
    version: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentListItem]
