import uuid

from sqlalchemy import insert, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Chunk, Document, SourceType
from app.services.exceptions import DocumentNotFoundError, DocumentValidationError

BATCH_SIZE = 100


def split_into_chunks(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


async def get_document_or_raise(db: AsyncSession, document_id: uuid.UUID) -> Document:
    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one_or_none()
    if doc is None:
        raise DocumentNotFoundError()
    return doc


async def create_document(
    db: AsyncSession, title: str, filename: str | None, text: str,
) -> tuple[Document, int]:
    paragraphs = split_into_chunks(text)

    if not paragraphs:
        raise DocumentValidationError("File is empty or contains no text.")

    doc = Document(
        id=uuid.uuid4(),
        title=title,
        source_path=filename,
        source_type=SourceType.txt,
        version=1,
    )
    db.add(doc)

    chunk_records = [
        {
            "id": uuid.uuid4(),
            "document_id": doc.id,
            "position": i + 1,
            "content": paragraph,
        }
        for i, paragraph in enumerate(paragraphs)
    ]
    for i in range(0, len(chunk_records), BATCH_SIZE):
        await db.execute(insert(Chunk), chunk_records[i:i + BATCH_SIZE])

    await db.commit()
    await db.refresh(doc)

    return doc, len(paragraphs)


async def list_documents(db: AsyncSession) -> list[Document]:
    docs_result = await db.execute(
        select(Document).order_by(Document.updated_at.desc())
    )
    return list(docs_result.scalars().all())


async def get_document_with_chunk_count(
    db: AsyncSession, document_id: uuid.UUID,
) -> tuple[Document, int]:
    doc_result = await db.execute(
        select(
            Document,
            func.count(Chunk.id).label("chunk_count"),
        )
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .where(Document.id == document_id)
        .group_by(Document.id)
    )
    row = doc_result.first()

    if row is None:
        raise DocumentNotFoundError()

    return row[0], row[1]


async def get_chunks_paginated(
    db: AsyncSession, document_id: uuid.UUID, page: int, page_size: int,
) -> tuple[list, int]:
    await get_document_or_raise(db, document_id)

    count_result = await db.execute(
        select(func.count(Chunk.id)).where(Chunk.document_id == document_id)
    )
    total_chunks = count_result.scalar()

    offset = (page - 1) * page_size
    chunks_result = await db.execute(
        select(Chunk)
        .where(Chunk.document_id == document_id)
        .order_by(Chunk.position)
        .offset(offset)
        .limit(page_size)
    )
    chunks = chunks_result.scalars().all()

    return chunks, total_chunks
