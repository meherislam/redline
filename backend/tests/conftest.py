import io
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.core.models import Base
from app.main import app


# ---------------------------------------------------------------------------
# Session-scoped: one Postgres container + engine for the whole test run.
# With asyncio_default_fixture_loop_scope = "session", all async fixtures
# share a single event loop — no cross-loop connection pool issues.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def postgres_url():
    """Spin up a real Postgres container and return an asyncpg connection URL."""
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        yield url


@pytest.fixture(scope="session")
def engine(postgres_url):
    return create_async_engine(postgres_url, echo=False)


@pytest.fixture(scope="session")
def session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
async def create_tables(engine):
    """Create all tables once for the test session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Per-test: patch the app's database module to use the test engine,
# then truncate all tables after each test for isolation.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def _cleanup(engine):
    """Truncate all tables after each test."""
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE changes, chunks, documents CASCADE"))


@pytest.fixture
async def client(engine, session_factory) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTP client backed by the test Postgres container.

    Monkey-patches the app's database module so all requests use the test engine.
    """
    import app.core.database as db_module

    original_engine = db_module.engine
    original_session = db_module.async_session

    db_module.engine = engine
    db_module.async_session = session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    db_module.engine = original_engine
    db_module.async_session = original_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_TEXT = (
    "This is the first paragraph of the document.\n\n"
    "This is the second paragraph with some important content.\n\n"
    "The third paragraph mentions indemnification and liability.\n\n"
    "The fourth paragraph talks about the term of twelve (12) months.\n\n"
    "The fifth paragraph contains duplicate words: apple apple apple."
)


async def upload_document(client: AsyncClient, title: str = "Test Document", text: str = SAMPLE_TEXT) -> dict:
    """Upload a document and return the JSON response."""
    file = io.BytesIO(text.encode("utf-8"))
    response = await client.post(
        "/documents",
        data={"title": title},
        files={"file": ("test.txt", file, "text/plain")},
    )
    assert response.status_code == 201
    return response.json()
