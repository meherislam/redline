# Redline — Document Management & Redlining Service

A document management platform with targeted text replacement (redlining), change tracking with accept/reject workflows, and AI-powered suggestions. Built with FastAPI, PostgreSQL, and React.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture Overview](#architecture-overview)
- [Data Model](#data-model)
- [API Reference](#api-reference)
- [Chunking Strategy](#chunking-strategy)
- [Search Implementation](#search-implementation)
- [Concurrency Control](#concurrency-control)
- [Performance Considerations](#performance-considerations)
- [Running Tests](#running-tests)
- [Sample Requests](#sample-requests)
- [Design Rationale](#design-rationale)

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- An [Anthropic API key](https://console.anthropic.com/) (optional — needed for AI suggestions)

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd redline

# Add your Anthropic API key (optional)
echo 'ANTHROPIC_API_KEY=your-key-here' > backend/.env

# Start everything (Postgres, backend, frontend)
docker compose up --build
```

The API will be available at `http://localhost:8000` and the frontend at `http://localhost:3000`.

Database migrations run automatically on startup via Alembic.

### Environment Variables

| Variable            | Required | Description                                      |
|---------------------|----------|--------------------------------------------------|
| `DATABASE_URL`      | Yes      | PostgreSQL connection string (set by Docker)      |
| `ANTHROPIC_API_KEY` | No       | Enables AI-powered text suggestions via Claude    |

### Local Development (without Docker)

If you prefer to run services locally:

- **Backend**: Python 3.13+, [uv](https://docs.astral.sh/uv/), PostgreSQL 16+
- **Frontend**: Node.js 22+

```bash
# Backend
cd backend
uv sync
cp .env.example .env  # Add your ANTHROPIC_API_KEY here
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/redline uv run uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

---

## Architecture Overview

The system stores documents as a collection of text chunks in PostgreSQL. Documents are split into paragraph-level chunks at ingestion time. All operations — search, replacement, and retrieval — work at the chunk level rather than the full document level. This ensures consistent performance regardless of document size.

Changes follow a redlining workflow: edits are applied immediately to chunk content but tracked as "pending" changes that can be accepted or rejected. Rejection reverts the chunk text. Cross-section edits are linked by a shared `change_group_id` so they can be accepted or rejected as a unit.

```
┌──────────┐     ┌──────────────┐     ┌────────────┐     ┌───────────┐
│  React    │────▶│  FastAPI      │────▶│ PostgreSQL  │     │ Anthropic │
│  Frontend │◀────│  API Server   │◀────│            │     │ Claude    │
└──────────┘     └──────────────┘     └────────────┘     └───────────┘
                                        ├─ documents                ▲
                                        ├─ chunks (tsvector + GIN)  │
                                        └─ changes (audit log)      │
                                                                    │
                                        suggest endpoint ───────────┘
```

---

## Data Model

### documents

Stores document-level metadata. The `version` field increments with every change and is used for optimistic concurrency control.

| Column      | Type         | Description                              |
|-------------|--------------|------------------------------------------|
| id          | UUID         | Primary key                              |
| title       | VARCHAR(255) | Document title                           |
| source_path | VARCHAR(500) | Path to the original uploaded file        |
| source_type | ENUM         | File type (`txt`)                        |
| version     | INTEGER      | Incrementing version for concurrency      |
| created_at  | TIMESTAMP    | Creation timestamp                       |
| updated_at  | TIMESTAMP    | Last modification timestamp              |

### chunks

Stores the actual document content as ordered text segments. The `search_vector` column is a Postgres generated column that automatically updates when `content` changes.

| Column        | Type      | Description                                      |
|---------------|-----------|--------------------------------------------------|
| id            | UUID      | Primary key                                      |
| document_id   | UUID      | FK → documents (cascade delete)                  |
| position      | INTEGER   | Ordering within the document                     |
| content       | TEXT      | The chunk text                                   |
| search_vector | TSVECTOR  | Auto-generated from content for full-text search |
| created_at    | TIMESTAMP | Creation timestamp                               |
| updated_at    | TIMESTAMP | Last modification timestamp                      |

**Indexes:** Composite index on `(document_id, position)` for ordered retrieval. GIN index on `search_vector` for full-text search.

### changes

An append-only audit log that records every text replacement made to a document. Changes start as `pending` and transition to `accepted` or `rejected`.

| Column           | Type        | Description                                          |
|------------------|-------------|------------------------------------------------------|
| id               | UUID        | Primary key                                          |
| document_id      | UUID        | FK → documents                                       |
| chunk_id         | UUID        | FK → chunks                                          |
| old_text         | TEXT        | Text that was replaced                               |
| new_text         | TEXT        | Replacement text (empty string for deletions)        |
| occurrence       | INTEGER     | Which occurrence was targeted (default 1)            |
| old_text_offset  | INTEGER     | Character position of old_text before replacement    |
| status           | ENUM        | Change status: `pending`, `accepted`, or `rejected`  |
| document_version | INTEGER     | Document version after this change                   |
| change_group_id  | UUID        | Groups related changes for batch accept/reject       |
| created_at       | TIMESTAMP   | When the change was made                             |

**Indexes:** Composite index on `(document_id, created_at)` for chronological history retrieval. Index on `change_group_id` for group-based operations.

---

## API Reference

### Documents

#### Create a Document

```
POST /documents
Content-Type: multipart/form-data
```

Upload a text file. The server reads the file, splits the content into paragraph-level chunks, and stores them with full-text search indexing.

**Request:** Form data with `title` (string) and `file` (text file upload).

**Response (201):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Service Agreement",
  "version": 1,
  "source_type": "txt",
  "chunk_count": 24,
  "created_at": "2026-03-14T12:00:00Z"
}
```

#### List Documents

```
GET /documents
```

#### Get Document

```
GET /documents/:id
```

Returns document metadata including the current `version` used for concurrency control.

### Chunks

#### Get Document Chunks

```
GET /documents/:id/chunks?page=1&page_size=20
```

Returns chunks in order, paginated. This is the primary way to read document content.

### Changes (Redlining)

#### Apply Changes

```
POST /documents/:id/changes
Content-Type: application/json
```

Apply one or more text replacements to a document. The `version` in the request body must match the document's current version. All changes are applied atomically — if any single change fails, none are applied.

**Request:**
```json
{
  "version": 3,
  "changes": [
    {
      "chunk_id": "chunk-002",
      "old_text": "twelve (12) months",
      "new_text": "twenty-four (24) months",
      "occurrence": 1,
      "group_id": "optional-shared-uuid"
    }
  ]
}
```

The `occurrence` field is optional (default 1) and specifies which occurrence of `old_text` to replace when it appears multiple times. The `group_id` field is optional — when provided, all changes sharing the same group_id are treated as a unit for accept/reject operations.

**Response (200):**
```json
{
  "version": 4,
  "applied": [
    {
      "chunk_id": "chunk-002",
      "old_text": "twelve (12) months",
      "new_text": "twenty-four (24) months",
      "status": "applied",
      "change_group_id": "group-uuid"
    }
  ],
  "chunks": [ ... ]
}
```

**Error Responses:**
- `400` — Text not found, occurrence out of range, or invalid chunk
- `409` — Version conflict (document has been modified since last fetch)

#### Get Change History

```
GET /documents/:id/changes
```

Returns the full history of changes made to a document, ordered chronologically. Each change includes its `change_group_id` for identifying related changes.

#### Accept a Change

```
PATCH /documents/:id/changes/:change_id/accept
```

Marks a change (and all changes in its group) as accepted. This is a status-only operation — chunk content is not modified because the replacement text is already in place from when the change was applied.

**Response (200):**
```json
{
  "id": "change-uuid",
  "status": "accepted",
  "chunks": [ ... ],
  "group_change_ids": ["id-1", "id-2"]
}
```

#### Reject a Change

```
PATCH /documents/:id/changes/:change_id/reject
```

Reverts a change (and all changes in its group) by restoring the original text. Group changes are reverted in reverse order (highest position first) to preserve character offsets during revert.

**Response (200):**
```json
{
  "id": "change-uuid",
  "status": "rejected",
  "chunks": [ ... ],
  "group_change_ids": ["id-1", "id-2"]
}
```

**Error Responses:**
- `400` — Change already accepted/rejected
- `409` — A later change conflicts with the revert

### Search

#### Full-Text Search

```
GET /documents/search?q=indemnification&document_id=optional-uuid
```

Searches across all documents (or a single document if `document_id` is provided) using PostgreSQL full-text search. Returns matching chunks with highlighted snippets and relevance ranking.

### Occurrences (Exact Text Matching)

#### Find Occurrences

```
GET /documents/:id/occurrences?q=Provider
```

Finds all chunks in a document that contain the exact term (case-sensitive) using SQL `LIKE` filtering. Used by the find-and-replace feature. This is distinct from full-text search — no stemming, no ranking, just exact string matching done entirely in the database.

**Response (200):**
```json
{
  "term": "Provider",
  "matches": [
    {
      "chunk_id": "chunk-uuid",
      "chunk_position": 3,
      "snippet": "...between Meridian Technology Solutions, Inc. (\"Provider\"), and Cascadia Financial..."
    }
  ],
  "total_chunks": 1
}
```

### AI Suggestions

#### Suggest Replacement

```
POST /documents/:id/suggest
Content-Type: application/json
```

Uses Anthropic Claude to suggest an improved replacement for selected text, given the surrounding context. Requires `ANTHROPIC_API_KEY` to be configured.

**Request:**
```json
{
  "chunk_id": "chunk-uuid",
  "selected_text": "The party shall be liable",
  "instruction": "Improve clarity"
}
```

**Response (200):**
```json
{
  "suggestion": "The responsible party shall assume liability"
}
```

**Error Responses:**
- `503` — `ANTHROPIC_API_KEY` not configured

---

## Chunking Strategy

Documents are split into chunks at ingestion time using paragraph boundaries (double newlines) as the primary delimiter. This approach was chosen because:

1. **Semantic coherence** — paragraphs are natural units of meaning. Search results and edit targets align with how people read and write.
2. **Bounded size** — most paragraphs are a reasonable size for database operations and API responses.
3. **Edit scoping** — replacement operations target specific chunks, keeping the blast radius of any edit small and predictable.

Chunks are stored with sequential integer positions for ordering. The full document can be reconstructed by querying all chunks for a document ordered by position.

The `changes` table is an append-only audit log. Chunks always reflect the latest content — you never need to replay the change log to read the current document state.

---

## Search Implementation

Search is powered by PostgreSQL's built-in full-text search. Each chunk has a `search_vector` column defined as a generated column:

```sql
search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
```

This means the search index updates automatically whenever chunk content changes — no application-level reindexing is required. A GIN index on this column enables fast lookups.

At query time, the search term is converted to a `tsquery` and matched against the index. `ts_rank` provides relevance scoring and `ts_headline` extracts a snippet with the matching terms highlighted.

**Why Postgres FTS over a hand-rolled inverted index?** Postgres `tsvector`/`tsquery` with a GIN index is effectively an inverted index maintained by the database engine. It handles tokenization, stemming, stop word removal, and ranking out of the box. Building a custom inverted index would offer more control over tokenization and scoring, but at significant implementation and maintenance cost. For this use case, Postgres FTS provides the right balance of capability and simplicity.

**Why not streaming for search?** A streaming approach would read documents sequentially and match as it goes. This works for single-pass operations but requires a full scan on every query — there is no index to skip to matching content. Chunking with an indexed search vector provides O(1) lookup relative to document size, making it the better choice for repeated queries.

---

## Concurrency Control

The system uses optimistic locking via a version field on the documents table.

1. Client fetches a document and receives the current `version`.
2. Client submits a change request including the expected `version`.
3. Server verifies the version matches. If it does, the changes are applied atomically and the version increments. If not, the server returns `409 Conflict`.
4. On conflict, the client re-fetches the document to see what changed, resolves any differences, and retries.

This approach prevents lost updates without requiring pessimistic locks that would block concurrent readers. It is well-suited to a document editing workflow where conflicts are infrequent — most of the time, only one person is editing a given document at a time.

The version check and all changes within a request are wrapped in a single database transaction. If any change fails (text not found, occurrence out of range), the entire transaction rolls back and no changes are applied.

---

## Performance Considerations

### Large Documents (10MB+)

A 10MB plain text document contains roughly 500-1000 paragraphs. With chunking, this means 500-1000 rows in the chunks table. All operations are scoped to individual chunks, not the full document:

- **Search**: GIN index lookup. Performance is independent of document size.
- **Replace**: Fetch affected chunks in a single query, perform string replacements in memory, write back. O(chunk_size), not O(document_size).
- **Bulk replace**: All affected chunks prefetched in one query via `WHERE id IN (...)`. Change records bulk-inserted in batches of 100 rows per statement. Single transaction regardless of batch count.
- **Read**: Paginated chunk retrieval. The client only loads what it needs.

### Batch Write Strategy

All bulk inserts (document ingestion, change application) use batched writes with a configurable batch size of 100 rows per statement. This prevents oversized SQL statements while minimizing round-trips. All batches execute within a single transaction to maintain atomicity.

### What is NOT linear in document size

The only operation that scales with total document size is initial ingestion — reading the file and splitting into chunks. This is a single O(n) pass and happens once per document.

### Indexing cost

The GIN index on `search_vector` adds write overhead when chunk content changes. For single replacements this is negligible. For bulk operations affecting many chunks in a large corpus, index maintenance could become a factor. In that scenario, deferring index updates or batching writes would be appropriate optimizations.

---

## Running Tests

Tests use [testcontainers](https://testcontainers.com/) to spin up a real Postgres instance in Docker, so Docker must be running.

```bash
cd backend

# Run all tests
uv run pytest tests/ -v

# Run only change logic tests
uv run pytest tests/test_changes.py -v

# Run only search tests
uv run pytest tests/test_search.py -v

# Run performance benchmarks (large document tests)
uv run pytest tests/test_performance.py -v
```

---

## Sample Requests

### Create a document

```bash
curl -X POST http://localhost:8000/documents \
  -F "title=Service Agreement" \
  -F "file=@sample.txt"
```

### Apply a change with group_id

```bash
curl -X POST http://localhost:8000/documents/{id}/changes \
  -H "Content-Type: application/json" \
  -d '{
    "version": 1,
    "changes": [
      {
        "chunk_id": "chunk-id-1",
        "old_text": "twelve (12) months",
        "new_text": "twenty-four (24) months",
        "group_id": "shared-group-uuid"
      },
      {
        "chunk_id": "chunk-id-2",
        "old_text": "March 1st",
        "new_text": "April 1st",
        "group_id": "shared-group-uuid"
      }
    ]
  }'
```

### Accept a change (and its group)

```bash
curl -X PATCH http://localhost:8000/documents/{id}/changes/{change_id}/accept
```

### Reject a change (and its group)

```bash
curl -X PATCH http://localhost:8000/documents/{id}/changes/{change_id}/reject
```

### Search across all documents

```bash
curl "http://localhost:8000/documents/search?q=indemnification"
```

### Get AI suggestion

```bash
curl -X POST http://localhost:8000/documents/{id}/suggest \
  -H "Content-Type: application/json" \
  -d '{
    "chunk_id": "chunk-uuid",
    "selected_text": "The party shall be liable",
    "instruction": "Improve clarity"
  }'
```

### Get change history

```bash
curl http://localhost:8000/documents/{id}/changes
```

---

## Design Rationale

### Why chunks?

A 10MB document is too large to operate on as a single unit. Every search, replacement, or read would require loading the entire thing. Chunking at paragraph boundaries solves this by creating bounded, semantically coherent units. A search hits an index and returns specific chunks, not the whole file. A replacement targets one chunk, not a full-document scan. Pagination returns N chunks, not N bytes of a monolithic blob.

Paragraphs were chosen as the split boundary because they're the natural unit of written text. Sentence-level chunks would be too granular — a single edit could span multiple chunks constantly. Section-level chunks would be too large and reintroduce the scaling problem. Paragraphs sit in the sweet spot: small enough for targeted edits, large enough to carry context for search ranking and AI suggestions.

### Why this database schema?

The schema separates three concerns into three tables:

**Documents** hold metadata and the version counter. No content lives here — this is purely an identity and concurrency record. Keeping the version at the document level (not the chunk level) means a single integer check prevents conflicting edits across the entire document.

**Chunks** hold the authoritative content. The current state of the document is always the chunks ordered by position. There is no need to replay a change log or reconstruct state from events. This makes reads fast and simple — just `SELECT ... ORDER BY position`.

**Changes** are an append-only audit log. They record what happened but are never required to read the current document. The `status` field transitions from `pending` to `accepted` or `rejected`, but the core fields (`old_text`, `new_text`, `old_text_offset`) are immutable. This separation means the system can always answer "what is the document now?" (chunks) independently from "what happened to it?" (changes).

The `change_group_id` on changes exists because edits can span multiple chunks (cross-section selections, find-and-replace-all). Rather than adding nullable foreign keys or a separate join table, a shared UUID links related changes together. Every change gets a group ID — a single edit is a group of one. This uniform model eliminates branching between "single change" and "grouped change" paths in accept/reject logic.

`old_text_offset` stores the character position of the replaced text at the time of the edit. This is necessary specifically for deletions: when text is deleted, the `old_text` no longer exists in the chunk, so without the offset there's no way to know where to re-insert it on rejection.

### Why PostgreSQL full-text search with a GIN index?

The `search_vector` column is a Postgres generated column — the database recomputes it automatically when `content` changes. This eliminates an entire class of bugs around stale indexes. There is no application code to keep the index in sync, no background job to run, no race condition between a write and an index update.

A GIN (Generalized Inverted Index) index on this column gives O(1) lookup performance relative to document size. Under the hood, GIN is an inverted index: it maps each lexeme to the set of rows containing it. This is the same data structure you'd build in a hand-rolled inverted index, but maintained by the database engine with transactional guarantees.

The alternative would be an in-memory inverted index built at the application layer. That approach offers more control over tokenization and scoring, but introduces significant complexity: the index must be rebuilt on startup, kept in sync on writes, and doesn't survive process restarts. It also doesn't handle concurrent access without explicit locking. Postgres FTS provides tokenization, stemming, stop-word removal, relevance ranking (`ts_rank`), and snippet generation (`ts_headline`) out of the box — all transactionally consistent with the underlying data.

### Why this API structure?

The API separates reads and writes along REST conventions:

- `GET` for reads: documents, chunks, changes, search, occurrences
- `POST` for creation: document upload, applying changes, requesting suggestions
- `PATCH` for state transitions: accepting and rejecting changes

Accept and reject are `PATCH` operations on action-based endpoints (`/changes/{id}/accept`, `/changes/{id}/reject`) rather than a generic `PATCH /changes/{id}` with a status body. This is intentional — accept and reject have fundamentally different semantics. Accept is a status-only operation (the replacement text is already in the chunk). Reject is a content operation (it reverts the chunk text). Exposing them as distinct endpoints makes the API honest about what each operation does, and prevents a caller from accidentally setting an invalid status like `"re-pending"` through a generic update.

All endpoints live under `/documents` because documents are the primary resource. Changes, chunks, occurrences, and suggestions are nested under `/documents/{id}` because they operate within a specific document. Search is at `/documents/search` because it queries across the documents collection.

Search and find-and-replace are separate endpoints because they serve different purposes. Full-text search (`/documents/search`) uses PostgreSQL FTS with stemming and ranking — it's for discovery. Occurrences (`/documents/{id}/occurrences`) uses exact case-sensitive `LIKE` matching — it's for precise text targeting in find-and-replace. Different tools for different jobs.

### Why optimistic concurrency over pessimistic locking?

Document editing is a low-contention workload. Most of the time, one person is editing a document at a time. Pessimistic locks (row-level locks, `SELECT ... FOR UPDATE`) would block concurrent readers and add complexity around lock timeout and deadlock handling — overhead that doesn't pay for itself in this use case.

Optimistic locking with a version integer is simpler: read the version, submit it with your edit, get a 409 if someone else edited first. The client re-fetches and retries. The version check and all changes in a request are wrapped in a single transaction, so there's no window for a race between the check and the write.

### Why eager application with pending status?

Changes modify chunk content immediately on application, then sit as `pending` until accepted or rejected. The alternative would be to store changes as proposals and only modify chunks on accept. We chose eager application because:

1. **The document always shows the latest state.** The frontend renders pending changes as inline redline markup (strikethrough for old text, highlight for new text). This matches how redlining works in tools like Word or Google Docs — you see the proposed changes in context.
2. **Accept is a no-op on content.** Since the replacement text is already in the chunk, accepting just flips the status. No content mutation, no risk of a failed write during accept.
3. **Reject is the only content operation.** Reverting text is more complex (finding the replacement, swapping it back, checking for conflicts with later changes), but it only happens on the less common path. Most changes get accepted.
