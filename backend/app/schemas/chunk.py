from uuid import UUID

from pydantic import BaseModel


class ChunkResponse(BaseModel):
    id: UUID
    position: int
    content: str

    model_config = {"from_attributes": True}


class ChunkListResponse(BaseModel):
    chunks: list[ChunkResponse]
    page: int
    page_size: int
    total_chunks: int
