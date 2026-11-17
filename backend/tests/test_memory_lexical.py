from adapters.memory_lexical import InMemoryLexicalStore
from domain.models import (
    Chunk,
    DocumentId,
    GroupId,
    SecurityContext,
    TenantId,
    UserId,
    make_chunk_id,
)
from domain.ports import LexicalStore


def make_store() -> LexicalStore:
    return InMemoryLexicalStore()


def ctx(tenant: str) -> SecurityContext:
    return SecurityContext(TenantId(tenant), UserId("u1"), frozenset({GroupId("g1")}), 1)


def chunk(tenant: str, doc: str, version: int, text: str) -> Chunk:
    d = DocumentId(doc)
    return Chunk(
        chunk_id=make_chunk_id(d, version, 0),
        tenant_id=TenantId(tenant),
        document_id=d,
        version=version,
        ordinal=0,
        text=text,
        title=doc,
        section=None,
        start_offset=0,
        end_offset=len(text),
    )


async def test_exact_term_match_ranks_first() -> None:
    store = make_store()
    await store.upsert(
        [
            chunk("t1", "a", 1, "the quarterly report covers revenue"),
            chunk("t1", "b", 1, "ticket ENG-4821 was escalated to security"),
            chunk("t1", "c", 1, "the cafeteria menu changes weekly"),
        ]
    )
    hits = await store.search(ctx("t1"), "ENG-4821", top_k=3)
    assert [h.document_id for h in hits] == ["b"]


async def test_rarer_terms_score_higher() -> None:
    store = make_store()
    await store.upsert(
        [
            chunk("t1", "a", 1, "policy policy policy"),
            chunk("t1", "b", 1, "policy for zebra handling"),
            chunk("t1", "c", 1, "policy update"),
        ]
    )
    hits = await store.search(ctx("t1"), "zebra policy", top_k=3)
    assert hits[0].document_id == "b"


async def test_search_never_crosses_tenants() -> None:
    store = make_store()
    await store.upsert([chunk("t1", "a", 1, "alpha"), chunk("t2", "secret", 1, "alpha alpha")])
    hits = await store.search(ctx("t1"), "alpha", top_k=10)
    assert {h.tenant_id for h in hits} == {"t1"}


async def test_no_match_and_empty_query_return_nothing() -> None:
    store = make_store()
    await store.upsert([chunk("t1", "a", 1, "alpha")])
    assert await store.search(ctx("t1"), "zzz", top_k=5) == []
    assert await store.search(ctx("t1"), "   ", top_k=5) == []


async def test_upsert_is_idempotent_and_may_return_stale_versions() -> None:
    store = make_store()
    c1 = chunk("t1", "a", 1, "alpha")
    await store.upsert([c1])
    await store.upsert([c1])
    await store.upsert([chunk("t1", "a", 2, "alpha")])
    hits = await store.search(ctx("t1"), "alpha", top_k=10)
    assert sorted(h.version for h in hits) == [1, 2]


async def test_delete_old_versions_only() -> None:
    store = make_store()
    await store.upsert([chunk("t1", "a", 1, "alpha"), chunk("t1", "a", 2, "alpha")])
    removed = await store.delete_document_versions(TenantId("t1"), DocumentId("a"), below_version=2)
    assert removed == 1
    hits = await store.search(ctx("t1"), "alpha", top_k=10)
    assert [h.version for h in hits] == [2]


async def test_rare_term_outscores_common_term_with_equal_tf() -> None:
    store = make_store()
    await store.upsert(
        [
            chunk("t1", "x", 1, "zebra"),
            chunk("t1", "y", 1, "policy"),
            chunk("t1", "z", 1, "policy memo"),
            chunk("t1", "w", 1, "policy note"),
        ]
    )
    scores = {h.document_id: h.score for h in await store.search(ctx("t1"), "zebra policy", 4)}
    assert scores[DocumentId("x")] > scores[DocumentId("y")]  # same tf and length, so only idf separates them




    
    