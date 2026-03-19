from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import changes, chunks, documents, occurrences, search, suggest

app = FastAPI(title="Redline", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(documents.router)
app.include_router(chunks.router)
app.include_router(changes.router)
app.include_router(occurrences.router)
app.include_router(suggest.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
