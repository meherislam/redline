import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Change, ChangeStatus, Chunk
from app.schemas import ChangeAppliedItem, ChangeRequest
from app.services.documents import get_document_or_raise
from app.services.exceptions import (
    ChangeConflictError,
    ChangeNotFoundError,
    ChangeValidationError,
)

BATCH_SIZE = 100


def replace_nth_occurrence(full_text: str, old_text: str, new_text: str, occurrence: int) -> tuple[str, int]:
    """Replace the nth (1-indexed) occurrence of `old_text` with `new_text` in `full_text`.

    Returns (updated_text, offset) where offset is the position of the replacement.
    """
    start = 0
    for i in range(occurrence):
        pos = full_text.find(old_text, start)
        if i == occurrence - 1:
            return full_text[:pos] + new_text + full_text[pos + len(old_text):], pos
        start = pos + len(old_text)
    return full_text, -1


async def _get_change_or_raise(
    db: AsyncSession, document_id: uuid.UUID, change_id: uuid.UUID,
) -> Change:
    change_result = await db.execute(
        select(Change).where(
            Change.id == change_id,
            Change.document_id == document_id,
        )
    )
    change = change_result.scalar_one_or_none()
    if change is None:
        raise ChangeNotFoundError()
    return change


async def apply_changes(
    db: AsyncSession,
    document_id: uuid.UUID,
    changes: list[ChangeRequest],
) -> list[ChangeAppliedItem]:
    await get_document_or_raise(db, document_id)

    applied = []
    change_records = []

    # Prefetch all referenced chunks in a single query
    chunk_ids = {c.chunk_id for c in changes}
    chunk_result = await db.execute(
        select(Chunk).where(Chunk.id.in_(chunk_ids), Chunk.document_id == document_id)
    )
    chunk_map = {c.id: c for c in chunk_result.scalars().all()}

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
            "document_version": 0,
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

    for i in range(0, len(change_records), BATCH_SIZE):
        await db.execute(insert(Change), change_records[i:i + BATCH_SIZE])

    await db.commit()

    return applied


async def get_change_history(
    db: AsyncSession, document_id: uuid.UUID,
) -> list[Change]:
    await get_document_or_raise(db, document_id)

    changes_result = await db.execute(
        select(Change)
        .where(Change.document_id == document_id)
        .order_by(Change.created_at)
    )
    return list(changes_result.scalars().all())


async def accept_change(
    db: AsyncSession, document_id: uuid.UUID, change_id: uuid.UUID,
) -> tuple[Change, list[uuid.UUID]]:
    change = await _get_change_or_raise(db, document_id, change_id)

    if change.status != ChangeStatus.pending:
        raise ChangeValidationError(
            f"This change has already been {change.status}."
        )

    # Always operate on the full group
    group_result = await db.execute(
        select(Change).where(
            Change.change_group_id == change.change_group_id,
            Change.document_id == document_id,
        )
    )
    group_changes = list(group_result.scalars().all())

    group_change_ids = []
    for group_change in group_changes:
        if group_change.status != ChangeStatus.pending:
            raise ChangeValidationError(
                f"A change in this group has already been {group_change.status}."
            )
        group_change.status = ChangeStatus.accepted
        group_change_ids.append(group_change.id)

    await db.commit()

    return change, group_change_ids


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
) -> tuple[Change, list[uuid.UUID]]:
    await get_document_or_raise(db, document_id)
    change = await _get_change_or_raise(db, document_id, change_id)

    if change.status != ChangeStatus.pending:
        raise ChangeValidationError(
            f"This change has already been {change.status}."
        )

    # Always operate on the full group — fetch changes with their chunks in one query
    group_result = await db.execute(
        select(Change, Chunk).join(
            Chunk, Change.chunk_id == Chunk.id
        ).where(
            Change.change_group_id == change.change_group_id,
            Change.document_id == document_id,
        )
    )
    change_chunk_pairs = list(group_result.all())

    # Validate all are still pending
    for group_change, chunk in change_chunk_pairs:
        if group_change.status != ChangeStatus.pending:
            raise ChangeValidationError(
                f"A change in this group has already been {group_change.status}."
            )

    # Sort: highest chunk position first, then highest offset first.
    # Rejecting later text first ensures earlier offsets stay valid.
    change_chunk_pairs.sort(
        key=lambda pair: (pair[1].position, pair[0].old_text_offset or 0),
        reverse=True,
    )

    group_change_ids = []
    for group_change, chunk in change_chunk_pairs:
        await _reject_single_change(db, document_id, group_change, change.change_group_id, chunk)
        group_change_ids.append(group_change.id)

    await db.commit()

    return change, group_change_ids
