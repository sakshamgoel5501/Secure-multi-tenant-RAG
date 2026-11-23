from collections.abc import Collection, Sequence

from adapters.fake_embedder import HashEmbedder
from adapters.memory_doc_state import InMemoryDocStateStore
from domain.models import (
    AclSnapshot, ChunkId, DocumentId, EmbeddedChunk, GroupId, RetrievalSource,
    SearchHit, SecurityContext, TenantId, UserId,
)  # fmt: skip
from serving.query_service import QueryService

T = TenantId("t1")
G = GroupId("g1")
CTX = SecurityContext(T, UserId("u"), frozenset({G}), 0)
DOCS = [DocumentId(f"d{i:02d}") for i in range(12)]


def hit(doc: DocumentId) -> SearchHit:
    return SearchHit(
        ChunkId(f"{doc}:1:0"), T, doc, 1, str(doc), None, 0, 1, "text", 1.0, RetrievalSource.DENSE
    )


class RankedVectors:
    """Returns the fixed ranking d00..d11, cut off at the requested size, and counts the calls."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    @property
    def index_version(self) -> str:
        return "stub"

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        return None

    async def search(self, ctx: SecurityContext, query_vector: Sequence[float], top_k: int) -> list[SearchHit]:
        self.calls.append(top_k)
        return [hit(d) for d in DOCS[:top_k]]

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        return 0


class AllowOnly:
    def __init__(self, allowed: set[str]) -> None:
        self._allowed = allowed

    async def acls_for(
        self, tenant_id: TenantId, document_ids: Collection[DocumentId], *, min_epoch: int
    ) -> AclSnapshot:
        return AclSnapshot(min_epoch, {d: frozenset({G}) for d in document_ids if d in self._allowed})


async def service(allowed: set[str], **kwargs: int) -> tuple[QueryService, RankedVectors]:
    state = InMemoryDocStateStore()
    for d in DOCS:
        await state.promote(T, d, 1)
    vectors = RankedVectors()
    svc = QueryService(state, vectors, HashEmbedder(), AllowOnly(allowed), **kwargs)
    return svc, vectors


async def test_a_user_with_few_permissions_still_gets_a_full_list() -> None:
    svc, vectors = await service({"d10", "d11"}, candidate_k=3, overfetch=1, growth=4, max_candidates=100)
    hits = await svc.retrieve(CTX, "q", top_k=2)
    assert sorted(h.document_id for h in hits) == ["d10", "d11"]
    assert vectors.calls == [3, 12]  # widened once, no further


async def test_no_widening_when_the_first_round_is_enough() -> None:
    svc, vectors = await service(set(DOCS), candidate_k=3, overfetch=1)
    assert len(await svc.retrieve(CTX, "q", top_k=2)) == 2
    assert vectors.calls == [3]


async def test_widening_stops_at_the_cap() -> None:
    svc, vectors = await service({"d11"}, candidate_k=3, overfetch=1, growth=2, max_candidates=6)
    hits = await svc.retrieve(CTX, "q", top_k=2)
    assert hits == []  # d11 sits beyond the cap of 6, so it is never reached
    assert vectors.calls == [3, 6]


async def test_widening_stops_when_the_index_has_nothing_more() -> None:
    svc, vectors = await service({"d00"}, candidate_k=50, overfetch=1)
    hits = await svc.retrieve(CTX, "q", top_k=2)
    assert [h.document_id for h in hits] == ["d00"]
    assert vectors.calls == [50]  # the search returned fewer than asked for, so it was not cut off

    