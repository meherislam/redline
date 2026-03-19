import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Change, ChangeStatus, Chunk, Document
from app.schemas import ChangeAppliedItem, ChangeRequest
from app.services.exceptions import (
    ChangeConflictError,
    ChangeNotFoundError,
    ChangeValidationError,
    DocumentNotFoundError,
    VersionConflictError,
)


def replace_nth_occurrence(text: str, old: str, new: str, n: int) -> tuple[str, int]:
    """Replace the nth (1-indexed) occurrence of `old` with `new` in `text`.

    Returns (new_text, offset) where offset is the position of the replacement.
    """
    start = 0
    for i in range(n):
        pos = text.find(old, start)
        if i == n - 1:
            return text[:pos] + new + text[pos + len(old):], pos
        start = pos + len(old)
    return text, -1


def _get_all_chunks_query(document_id: uuid.UUID):
    return select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.position)


async def _get_change_or_raise(
    db: AsyncSession, document_id: uuid.UUID, change_id: uuid.UUID,
) -> Change:
    result = await db.execute(
        select(Change).where(
            Change.id == change_id,
            Change.document_id == document_id,
        )
    )
    change = result.scalar_one_or_none()
    if change is None:
        raise ChangeNotFoundError()
    return change


async def apply_changes(
    db: AsyncSession,
    document_id: uuid.UUID,
    version: int,
    changes: list[ChangeRequest],
) -> tuple[int, list[ChangeAppliedItem], list[Chunk]]:
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if doc is None:
        raise DocumentNotFoundError()

    if doc.version != version:
        raise VersionConflictError(
            "This document has been updated since you last loaded it. Please refresh and try again."
        )

    applied = []
    change_records = []

    # Prefetch all referenced chunks in a single query
    chunk_ids = {c.chunk_id for c in changes}
    chunk_result = await db.execute(
        select(Chunk).where(Chunk.id.in_(chunk_ids), Chunk.document_id == document_id)
    )
    chunk_map = {c.id: c for c in chunk_result.scalars().all()}

    new_version = doc.version + 1

    for change_req in changes:
        chunk = chunk_map.get(change_req.chunk_id)

        if chunk is None:
            raise ChangeValidationError(
                "The selected text could not be located in this document."
            )

        occurrences = chunk.content.count(change_req.old_text)

        if occurrences == 0:
            raise ChangeValidationError(
                "The selected text could not be found in the document. It may have been modified by another change."
            )

        if change_req.occurrence > occurrences:
            raise ChangeValidationError(
                "The specified text match could not be found. The document may have changed."
            )

        chunk.content, offset = replace_nth_occurrence(
            chunk.content, change_req.old_text, change_req.new_text, change_req.occurrence,
        )

        # Every change gets a group_id. If the request provides one, use it.
        # Otherwise generate one (single-chunk change = group of one).
        group_id = change_req.group_id if change_req.group_id is not None else uuid.uuid4()

        change_records.append({
            "id": uuid.uuid4(),
            "document_id": document_id,
            "chunk_id": chunk.id,
            "old_text": change_req.old_text,
            "new_text": change_req.new_text,
            "occurrence": change_req.occurrence,
            "old_text_offset": offset,
            "document_version": new_version,
            "change_group_id": group_id,
        })

        applied.append(
            ChangeAppliedItem(
                chunk_id=change_req.chunk_id,
                old_text=change_req.old_text,
                new_text=change_req.new_text,
                change_group_id=group_id,
            )
        )

    # Bulk insert change records in batches to avoid oversized statements
    BATCH_SIZE = 100
    for i in range(0, len(change_records), BATCH_SIZE):
        await db.execute(insert(Change), change_records[i:i + BATCH_SIZE])

    doc.version = new_version
    await db.commit()

    chunks_result = await db.execute(_get_all_chunks_query(document_id))
    chunks = list(chunks_result.scalars().all())

    return doc.version, applied, chunks


async def get_change_history(
    db: AsyncSession, document_id: uuid.UUID,
) -> list[Change]:
    doc_exists = await db.execute(select(Document.id).where(Document.id == document_id))
    if doc_exists.scalar_one_or_none() is None:
        raise DocumentNotFoundError()

    stmt = (
        select(Change)
        .where(Change.document_id == document_id)
        .order_by(Change.created_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def accept_change(
    db: AsyncSession, document_id: uuid.UUID, change_id: uuid.UUID,
) -> tuple[Change, list[Chunk], list[uuid.UUID]]:
    change = await _get_change_or_raise(db, document_id, change_id)

    if change.status != ChangeStatus.pending:
        raise ChangeValidationError(
            f"This change has already been {change.status}."
        )

    # Always operate on the full group
    result = await db.execute(
        select(Change).where(
            Change.change_group_id == change.change_group_id,
            Change.document_id == document_id,
        )
    )
    group_changes = list(result.scalars().all())

    group_change_ids = []
    for gc in group_changes:
        if gc.status != ChangeStatus.pending:
            raise ChangeValidationError(
                f"A change in this group has already been {gc.status}."
            )
        gc.status = ChangeStatus.accepted
        group_change_ids.append(gc.id)

    await db.commit()

    chunks_result = await db.execute(_get_all_chunks_query(document_id))
    chunks = list(chunks_result.scalars().all())

    return change, chunks, group_change_ids


async def _reject_single_change(
    db: AsyncSession, document_id: uuid.UUID, change: Change, group_id: uuid.UUID,
    chunk: Chunk,
) -> None:
    """Revert a single change's text modification and mark it rejected.

    Does NOT commit or bump the document version — the caller handles that.
    """

    if change.new_text == '':
        # Deletion: re-insert old_text at the recorded offset.
        # Check for later pending changes on this chunk that are NOT in the
        # current group (those would have shifted the content).
        later_changes = await db.execute(
            select(Change.id).where(
                Change.chunk_id == change.chunk_id,
                Change.status == ChangeStatus.pending,
                Change.created_at > change.created_at,
                Change.change_group_id != group_id,
            )
        )
        if later_changes.scalar_one_or_none() is not None:
            raise ChangeConflictError(
                "Cannot reject: a later change on the same section may have shifted the text. Reject the later change first."
            )

        offset = change.old_text_offset if change.old_text_offset is not None else 0
        if offset > len(chunk.content):
            raise ChangeConflictError(
                "Cannot reject: the document has changed and the original position is no longer valid."
            )
        chunk.content = chunk.content[:offset] + change.old_text + chunk.content[offset:]
    else:
        offset = change.old_text_offset if change.old_text_offset is not None else 0
        expected = chunk.content[offset:offset + len(change.new_text)]
        if expected != change.new_text:
            raise ChangeConflictError(
                "Cannot reject: the changed text has been modified by a later edit. Reject the later change first."
            )
        chunk.content = chunk.content[:offset] + change.old_text + chunk.content[offset + len(change.new_text):]

    change.status = ChangeStatus.rejected


async def reject_change(
    db: AsyncSession, document_id: uuid.UUID, change_id: uuid.UUID,
) -> tuple[Change, list[Chunk], list[uuid.UUID]]:
    change = await _get_change_or_raise(db, document_id, change_id)

    if change.status != ChangeStatus.pending:
        raise ChangeValidationError(
            f"This change has already been {change.status}."
        )

    # Always operate on the full group — fetch changes with their chunks in one query
    result = await db.execute(
        select(Change, Chunk).join(
            Chunk, Change.chunk_id == Chunk.id
        ).where(
            Change.change_group_id == change.change_group_id,
            Change.document_id == document_id,
        )
    )
    rows = list(result.all())

    # Validate all are still pending
    for gc, _chunk in rows:
        if gc.status != ChangeStatus.pending:
            raise ChangeValidationError(
                f"A change in this group has already been {gc.status}."
            )

    # Sort: highest chunk position first, then highest offset first.
    # Rejecting later text first ensures earlier offsets stay valid.
    rows.sort(key=lambda r: (r[1].position, r[0].old_text_offset or 0), reverse=True)

    group_change_ids = []
    for gc, chunk in rows:
        await _reject_single_change(db, document_id, gc, change.change_group_id, chunk)
        group_change_ids.append(gc.id)

    # Bump document version once for the entire group rejection
    doc_result = await db.execute(select(Document).where(Document.id == document_id))
    doc = doc_result.scalar_one()
    doc.version += 1

    await db.commit()

    chunks_result = await db.execute(_get_all_chunks_query(document_id))
    chunks = list(chunks_result.scalars().all())

    return change, chunks, group_change_ids
