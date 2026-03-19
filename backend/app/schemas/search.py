from uuid import UUID

from pydantic import BaseModel


class SearchResultItem(BaseModel):
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_position: int
    snippet: str
    rank: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
