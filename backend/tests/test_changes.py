import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import upload_document


async def _setup_doc(client: AsyncClient) -> tuple[dict, list[dict]]:
    """Upload a doc and return (doc_json, chunks_list)."""
    created = await upload_document(client)
    chunks_resp = await client.get(f"/documents/{created['id']}/chunks")
    chunks = chunks_resp.json()["chunks"]
    return created, chunks


class TestSingleReplacement:
    async def test_replace_text_in_chunk(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": chunks[3]["id"],
                        "old_text": "twelve (12) months",
                        "new_text": "twenty-four (24) months",
                    }
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 2
        assert len(data["applied"]) == 1
        assert data["applied"][0]["status"] == "applied"

    async def test_response_includes_updated_chunks(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": chunks[3]["id"],
                        "old_text": "twelve (12) months",
                        "new_text": "twenty-four (24) months",
                    }
                ],
            },
        )
        data = response.json()

        assert "chunks" in data
        assert len(data["chunks"]) == 5

        # The modified chunk should have the new text
        modified = next(c for c in data["chunks"] if c["id"] == chunks[3]["id"])
        assert "twenty-four (24) months" in modified["content"]
        assert "twelve (12) months" not in modified["content"]

    async def test_replacement_persists(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": chunks[3]["id"],
                        "old_text": "twelve (12) months",
                        "new_text": "twenty-four (24) months",
                    }
                ],
            },
        )

        # Re-fetch chunks and verify
        chunks_resp = await client.get(f"/documents/{doc['id']}/chunks")
        updated_chunks = chunks_resp.json()["chunks"]
        modified = next(c for c in updated_chunks if c["id"] == chunks[3]["id"])
        assert "twenty-four (24) months" in modified["content"]


class TestBulkReplacement:
    async def test_multiple_changes_applied_atomically(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": chunks[0]["id"],
                        "old_text": "first paragraph",
                        "new_text": "opening paragraph",
                    },
                    {
                        "chunk_id": chunks[1]["id"],
                        "old_text": "important content",
                        "new_text": "critical content",
                    },
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 2
        assert len(data["applied"]) == 2

        # Both changes reflected in returned chunks
        c0 = next(c for c in data["chunks"] if c["id"] == chunks[0]["id"])
        c1 = next(c for c in data["chunks"] if c["id"] == chunks[1]["id"])
        assert "opening paragraph" in c0["content"]
        assert "critical content" in c1["content"]


class TestOccurrenceTargeting:
    async def test_target_specific_occurrence(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        # Chunk 4 has "apple apple apple" — target the 2nd occurrence
        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": chunks[4]["id"],
                        "old_text": "apple",
                        "new_text": "orange",
                        "occurrence": 2,
                    }
                ],
            },
        )
        assert response.status_code == 200
        modified = next(c for c in response.json()["chunks"] if c["id"] == chunks[4]["id"])
        assert "apple orange apple" in modified["content"]

    async def test_target_first_occurrence_by_default(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": chunks[4]["id"],
                        "old_text": "apple",
                        "new_text": "orange",
                    }
                ],
            },
        )
        assert response.status_code == 200
        modified = next(c for c in response.json()["chunks"] if c["id"] == chunks[4]["id"])
        assert "orange apple apple" in modified["content"]


class TestChangeErrors:
    async def test_text_not_found_returns_400(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": chunks[0]["id"],
                        "old_text": "nonexistent text",
                        "new_text": "replacement",
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "could not be found" in response.json()["detail"].lower()

    async def test_occurrence_out_of_range_returns_400(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": chunks[4]["id"],
                        "old_text": "apple",
                        "new_text": "orange",
                        "occurrence": 10,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "could not be found" in response.json()["detail"].lower()

    async def test_invalid_chunk_id_returns_400(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": "00000000-0000-0000-0000-000000000000",
                        "old_text": "anything",
                        "new_text": "something",
                    }
                ],
            },
        )
        assert response.status_code == 400


class TestVersionConflict:
    async def test_wrong_version_returns_409(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 999,
                "changes": [
                    {
                        "chunk_id": chunks[0]["id"],
                        "old_text": "first",
                        "new_text": "1st",
                    }
                ],
            },
        )
        assert response.status_code == 409
        assert "updated since you last loaded" in response.json()["detail"].lower()

    async def test_version_increments_correctly(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        # First change: v1 -> v2
        r1 = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"}],
            },
        )
        assert r1.json()["version"] == 2

        # Second change: v2 -> v3
        r2 = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 2,
                "changes": [{"chunk_id": chunks[1]["id"], "old_text": "second", "new_text": "2nd"}],
            },
        )
        assert r2.json()["version"] == 3

        # Using v1 again should conflict
        r3 = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[2]["id"], "old_text": "third", "new_text": "3rd"}],
            },
        )
        assert r3.status_code == 409


class TestAtomicRollback:
    async def test_partial_failure_rolls_back_all_changes(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        # First change is valid, second is not
        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": chunks[0]["id"],
                        "old_text": "first paragraph",
                        "new_text": "opening paragraph",
                    },
                    {
                        "chunk_id": chunks[1]["id"],
                        "old_text": "text that does not exist",
                        "new_text": "replacement",
                    },
                ],
            },
        )
        assert response.status_code == 400

        # The first change should NOT have been applied
        chunks_resp = await client.get(f"/documents/{doc['id']}/chunks")
        chunk_0 = chunks_resp.json()["chunks"][0]
        assert "first paragraph" in chunk_0["content"]
        assert "opening paragraph" not in chunk_0["content"]

        # Version should still be 1
        doc_resp = await client.get(f"/documents/{doc['id']}")
        assert doc_resp.json()["version"] == 1


class TestChangeHistory:
    async def test_history_records_changes(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {
                        "chunk_id": chunks[0]["id"],
                        "old_text": "first",
                        "new_text": "1st",
                    }
                ],
            },
        )

        response = await client.get(f"/documents/{doc['id']}/changes")
        assert response.status_code == 200
        changes = response.json()["changes"]
        assert len(changes) == 1
        assert changes[0]["old_text"] == "first"
        assert changes[0]["new_text"] == "1st"
        assert changes[0]["document_version"] == 2
        assert changes[0]["occurrence"] == 1

    async def test_history_is_chronological(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"}],
            },
        )
        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 2,
                "changes": [{"chunk_id": chunks[1]["id"], "old_text": "second", "new_text": "2nd"}],
            },
        )

        response = await client.get(f"/documents/{doc['id']}/changes")
        changes = response.json()["changes"]
        assert len(changes) == 2
        assert changes[0]["old_text"] == "first"
        assert changes[1]["old_text"] == "second"

    async def test_history_empty_for_new_document(self, client: AsyncClient):
        doc = await upload_document(client)

        response = await client.get(f"/documents/{doc['id']}/changes")
        assert response.status_code == 200
        assert response.json()["changes"] == []

    async def test_history_includes_status_field(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"}],
            },
        )

        response = await client.get(f"/documents/{doc['id']}/changes")
        changes = response.json()["changes"]
        assert changes[0]["status"] == "pending"


class TestAcceptChange:
    async def test_accept_pending_change(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        # Apply a change
        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"}],
            },
        )

        # Get the change id
        history = await client.get(f"/documents/{doc['id']}/changes")
        change_id = history.json()["changes"][0]["id"]

        # Accept the change
        response = await client.patch(f"/documents/{doc['id']}/changes/{change_id}/accept")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == change_id
        assert data["status"] == "accepted"
        assert "chunks" in data

    async def test_accept_does_not_modify_content(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"}],
            },
        )

        history = await client.get(f"/documents/{doc['id']}/changes")
        change_id = history.json()["changes"][0]["id"]

        # Content before accept
        chunks_before = await client.get(f"/documents/{doc['id']}/chunks")
        content_before = chunks_before.json()["chunks"][0]["content"]

        # Accept
        await client.patch(f"/documents/{doc['id']}/changes/{change_id}/accept")

        # Content after accept should be the same
        chunks_after = await client.get(f"/documents/{doc['id']}/chunks")
        content_after = chunks_after.json()["chunks"][0]["content"]
        assert content_before == content_after

    async def test_cannot_accept_already_accepted(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"}],
            },
        )

        history = await client.get(f"/documents/{doc['id']}/changes")
        change_id = history.json()["changes"][0]["id"]

        await client.patch(f"/documents/{doc['id']}/changes/{change_id}/accept")

        # Try accepting again
        response = await client.patch(f"/documents/{doc['id']}/changes/{change_id}/accept")
        assert response.status_code == 400
        assert "already" in response.json()["detail"].lower()

    async def test_accept_nonexistent_change_returns_404(self, client: AsyncClient):
        doc, _ = await _setup_doc(client)

        response = await client.patch(
            f"/documents/{doc['id']}/changes/00000000-0000-0000-0000-000000000000/accept"
        )
        assert response.status_code == 404


class TestRejectChange:
    async def test_reject_reverts_text(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"}],
            },
        )

        history = await client.get(f"/documents/{doc['id']}/changes")
        change_id = history.json()["changes"][0]["id"]

        # Reject
        response = await client.patch(f"/documents/{doc['id']}/changes/{change_id}/reject")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"

        # The text should be reverted back to "first"
        chunks_resp = await client.get(f"/documents/{doc['id']}/chunks")
        content = chunks_resp.json()["chunks"][0]["content"]
        assert "first" in content
        assert "1st" not in content

    async def test_reject_bumps_version(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"}],
            },
        )

        history = await client.get(f"/documents/{doc['id']}/changes")
        change_id = history.json()["changes"][0]["id"]

        await client.patch(f"/documents/{doc['id']}/changes/{change_id}/reject")

        doc_resp = await client.get(f"/documents/{doc['id']}")
        # Was v1, changed to v2 by apply, then v3 by reject
        assert doc_resp.json()["version"] == 3

    async def test_cannot_reject_already_rejected(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"}],
            },
        )

        history = await client.get(f"/documents/{doc['id']}/changes")
        change_id = history.json()["changes"][0]["id"]

        await client.patch(f"/documents/{doc['id']}/changes/{change_id}/reject")

        response = await client.patch(f"/documents/{doc['id']}/changes/{change_id}/reject")
        assert response.status_code == 400
        assert "already" in response.json()["detail"].lower()

    async def test_reject_superseded_change_returns_409(self, client: AsyncClient):
        doc, chunks = await _setup_doc(client)

        # Change 1: "first" -> "1st"
        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"}],
            },
        )

        history = await client.get(f"/documents/{doc['id']}/changes")
        change1_id = history.json()["changes"][0]["id"]

        # Change 2: overwrite "1st" with "first-ever" (supersedes change 1)
        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 2,
                "changes": [{"chunk_id": chunks[0]["id"], "old_text": "1st", "new_text": "first-ever"}],
            },
        )

        # Try to reject change 1 — "1st" no longer exists in the chunk
        response = await client.patch(f"/documents/{doc['id']}/changes/{change1_id}/reject")
        assert response.status_code == 409
        assert "modified by a later edit" in response.json()["detail"].lower()

    async def test_reject_deletion_blocked_by_later_pending_change(self, client: AsyncClient):
        """Two deletions on the same chunk — rejecting the earlier one should 409
        because the later pending change may have shifted offsets."""
        doc, chunks = await _setup_doc(client)
        chunk_id = chunks[4]["id"]  # "... duplicate words: apple apple apple."

        # Deletion 1: delete first "apple "
        r1 = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [{"chunk_id": chunk_id, "old_text": "apple ", "new_text": "", "occurrence": 1}],
            },
        )
        assert r1.status_code == 200

        # Deletion 2: delete another "apple " from the same chunk
        r2 = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 2,
                "changes": [{"chunk_id": chunk_id, "old_text": "apple ", "new_text": "", "occurrence": 1}],
            },
        )
        assert r2.status_code == 200

        # Get change IDs (chronological order)
        history = await client.get(f"/documents/{doc['id']}/changes")
        changes = history.json()["changes"]
        change1_id = changes[0]["id"]
        change2_id = changes[1]["id"]

        # Trying to reject change 1 should fail — change 2 is still pending on the same chunk
        response = await client.patch(f"/documents/{doc['id']}/changes/{change1_id}/reject")
        assert response.status_code == 409
        assert "later change" in response.json()["detail"].lower()

        # But rejecting change 2 (the later one) should succeed
        response = await client.patch(f"/documents/{doc['id']}/changes/{change2_id}/reject")
        assert response.status_code == 200

        # Now rejecting change 1 should also succeed
        response = await client.patch(f"/documents/{doc['id']}/changes/{change1_id}/reject")
        assert response.status_code == 200

    async def test_reject_nonexistent_change_returns_404(self, client: AsyncClient):
        doc, _ = await _setup_doc(client)

        response = await client.patch(
            f"/documents/{doc['id']}/changes/00000000-0000-0000-0000-000000000000/reject"
        )
        assert response.status_code == 404


class TestChangeGroups:
    """Cross-chunk change groups: every change gets a group_id, groups accept/reject as a unit."""

    async def test_apply_grouped_changes(self, client: AsyncClient):
        """Changes with a shared group_id are linked together."""
        doc, chunks = await _setup_doc(client)
        group_id = str(uuid.uuid4())

        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st", "group_id": group_id},
                    {"chunk_id": chunks[1]["id"], "old_text": "second", "new_text": "2nd", "group_id": group_id},
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        # Both applied items carry the same group_id
        for item in data["applied"]:
            assert item["change_group_id"] == group_id

    async def test_single_change_gets_auto_group_id(self, client: AsyncClient):
        """A change without an explicit group_id gets one auto-generated."""
        doc, chunks = await _setup_doc(client)

        response = await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st"},
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["applied"][0]["change_group_id"] is not None

    async def test_accept_group_accepts_all(self, client: AsyncClient):
        """Accepting any change in a group accepts all changes in the group."""
        doc, chunks = await _setup_doc(client)
        group_id = str(uuid.uuid4())

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st", "group_id": group_id},
                    {"chunk_id": chunks[1]["id"], "old_text": "second", "new_text": "2nd", "group_id": group_id},
                ],
            },
        )

        history = await client.get(f"/documents/{doc['id']}/changes")
        changes = history.json()["changes"]
        assert len(changes) == 2
        change_ids = {c["id"] for c in changes}

        # Accept just the first change — both should be accepted
        response = await client.patch(f"/documents/{doc['id']}/changes/{changes[0]['id']}/accept")
        assert response.status_code == 200
        data = response.json()
        assert set(data["group_change_ids"]) == change_ids

        # Verify both are now accepted
        history = await client.get(f"/documents/{doc['id']}/changes")
        for c in history.json()["changes"]:
            assert c["status"] == "accepted"

    async def test_reject_group_rejects_all_and_reverts(self, client: AsyncClient):
        """Rejecting any change in a group rejects and reverts all."""
        doc, chunks = await _setup_doc(client)
        group_id = str(uuid.uuid4())

        # Apply replacements to two chunks
        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st", "group_id": group_id},
                    {"chunk_id": chunks[1]["id"], "old_text": "second", "new_text": "2nd", "group_id": group_id},
                ],
            },
        )

        history = await client.get(f"/documents/{doc['id']}/changes")
        changes = history.json()["changes"]
        change_ids = {c["id"] for c in changes}

        # Reject the second change — both should be rejected
        response = await client.patch(f"/documents/{doc['id']}/changes/{changes[1]['id']}/reject")
        assert response.status_code == 200
        assert set(response.json()["group_change_ids"]) == change_ids

        # Both chunks should be reverted
        chunks_resp = await client.get(f"/documents/{doc['id']}/chunks")
        updated = chunks_resp.json()["chunks"]
        assert "first" in updated[0]["content"]
        assert "1st" not in updated[0]["content"]
        assert "second" in updated[1]["content"]
        assert "2nd" not in updated[1]["content"]

    async def test_reject_group_with_deletions(self, client: AsyncClient):
        """Group rejection correctly reverts deletions across chunks (reverse order)."""
        doc, chunks = await _setup_doc(client)
        group_id = str(uuid.uuid4())

        # Delete text from two chunks
        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {"chunk_id": chunks[0]["id"], "old_text": "first paragraph", "new_text": "", "group_id": group_id},
                    {"chunk_id": chunks[2]["id"], "old_text": "third paragraph", "new_text": "", "group_id": group_id},
                ],
            },
        )

        history = await client.get(f"/documents/{doc['id']}/changes")
        change_id = history.json()["changes"][0]["id"]

        # Reject the group
        response = await client.patch(f"/documents/{doc['id']}/changes/{change_id}/reject")
        assert response.status_code == 200

        # Both deletions should be reverted
        chunks_resp = await client.get(f"/documents/{doc['id']}/chunks")
        updated = chunks_resp.json()["chunks"]
        assert "first paragraph" in updated[0]["content"]
        assert "third paragraph" in updated[2]["content"]

    async def test_history_includes_change_group_id(self, client: AsyncClient):
        """Change history returns change_group_id for each change."""
        doc, chunks = await _setup_doc(client)
        group_id = str(uuid.uuid4())

        await client.post(
            f"/documents/{doc['id']}/changes",
            json={
                "version": 1,
                "changes": [
                    {"chunk_id": chunks[0]["id"], "old_text": "first", "new_text": "1st", "group_id": group_id},
                    {"chunk_id": chunks[1]["id"], "old_text": "second", "new_text": "2nd", "group_id": group_id},
                ],
            },
        )

        history = await client.get(f"/documents/{doc['id']}/changes")
        for c in history.json()["changes"]:
            assert c["change_group_id"] == group_id
