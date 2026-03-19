from uuid import UUID

from pydantic import BaseModel


class OccurrenceItem(BaseModel):
    chunk_id: UUID
    chunk_position: int
    snippet: str


class OccurrencesResponse(BaseModel):
    term: str
    matches: list[OccurrenceItem]
    total_chunks: int
