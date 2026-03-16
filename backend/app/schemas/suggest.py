from uuid import UUID

from pydantic import BaseModel


class SuggestRequest(BaseModel):
    chunk_id: UUID
    selected_text: str
    instruction: str = "Improve clarity and conciseness"


class SuggestResponse(BaseModel):
    suggestion: str
