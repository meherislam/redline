import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas import (
    DocumentCreateResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentResponse,
)
from app.services import documents as document_service
from app.services.exceptions import DocumentNotFoundError

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_CONTENT_TYPES = {"text/plain"}


@router.post("", status_code=201, response_model=DocumentCreateResponse)
async def create_document(
    title: str = Form(...),
    file: UploadFile = None,
    db: AsyncSession = Depends(get_db),
):
    if file is None:
        raise HTTPException(status_code=400, detail="A text file is required.")

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Only plain text (.txt) files are supported.",
        )

    content = await file.read()

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="File does not appear to be a valid text file.",
        )

    try:
        doc, chunk_count = await document_service.create_document(
            db, title, file.filename, text,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DocumentCreateResponse(
        id=doc.id,
        title=doc.title,
        version=doc.version,
        source_type=doc.source_type,
        chunk_count=chunk_count,
        created_at=doc.created_at,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(db: AsyncSession = Depends(get_db)):
    rows = await document_service.list_documents(db)

    return DocumentListResponse(
        documents=[
            DocumentListItem(
                id=row.id,
                title=row.title,
                version=row.version,
                chunk_count=row.chunk_count,
                updated_at=row.updated_at,
            )
            for row in rows
        ]
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    try:
        doc, chunk_count = await document_service.get_document_with_chunk_count(
            db, document_id,
        )
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")

    response.headers["ETag"] = f'"{doc.version}"'

    return DocumentResponse(
        id=doc.id,
        title=doc.title,
        version=doc.version,
        source_type=doc.source_type,
        chunk_count=chunk_count,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    try:
        await document_service.delete_document(db, document_id)
    except DocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found.")
