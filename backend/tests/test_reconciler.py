from collections.abc import Collection

from adapters.fake_embedder import HashEmbedder
from adapters.memory_lexical import InMemoryLexicalStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.models import (
    DocStatus,
    DocumentEvent,
    DocumentId,
    DocumentState,
    GroupId,
    Operation,
    SecurityContext,
    TenantId,
    UserId,
)
from ingestion.reconciler import Missing, Reconciler
from ingestion.reindex import Reindexer

T = TenantId("t1")
D = DocumentId("d1")
_Key = tuple[TenantId, DocumentId]


def state(
    latest: int,
    active: int | None,
    status: DocStatus = DocStatus.ACTIVE,
    doc: DocumentId = D,
) -> DocumentState:
    return DocumentState(doc, T, latest, active, status)


class FakeScanner:
    def __init__(self, states: list[DocumentState]) -> None:
        self._states = states

    async def list_tenants(self) -> list[TenantId]:
        return sorted({s.tenant_id for s in self._states})

    async def list_states(self, tenant_id: TenantId) -> list[DocumentState]:
        return [s for s in self._states if s.tenant_id == tenant_id]


class FakeIndex:
    def __init__(self, data: dict[_Key, set[int]]) -> None:
        self.data = data

    async def list_versions(self, tenant_id: TenantId) -> dict[DocumentId, set[int]]:
        return {d: set(v) for (t, d), v in self.data.items() if t == tenant_id}

    async def delete_versions(
        self, tenant_id: TenantId, document_id: DocumentId, versions: Collection[int]
    ) -> int:
        current = self.data.get((tenant_id, document_id), set())
        gone = current & set(versions)
        remaining = current - gone
        if remaining:
            self.data[(tenant_id, document_id)] = remaining
        else:
            self.data.pop((tenant_id, document_id), None)
        return len(gone)


async def test_stale_old_version_is_deleted() -> None:
    index = FakeIndex({(T, D): {1, 2}})
    report = await Reconciler(FakeScanner([state(2, 2)]), {"dense": index}).run()
    assert index.data == {(T, D): {2}}
    assert report.orphans_deleted == 1


async def test_in_flight_version_is_protected() -> None:
    index = FakeIndex({(T, D): {1, 2}})  # v2 chunks written, promote not done yet
    report = await Reconciler(FakeScanner([state(2, 1)]), {"dense": index}).run()
    assert index.data == {(T, D): {1, 2}}
    assert report.orphans_deleted == 0


async def test_crashed_orphan_is_deleted_once_superseded() -> None:
    index = FakeIndex({(T, D): {1, 2}})  # v2 crashed; v3 has since been seen
    await Reconciler(FakeScanner([state(3, 1)]), {"dense": index}).run()
    assert index.data == {(T, D): {1}}


async def test_tombstoned_document_chunks_are_deleted() -> None:
    index = FakeIndex({(T, D): {10, 11}})
    deleted = state(12, 10, DocStatus.DELETED)
    report = await Reconciler(FakeScanner([deleted]), {"dense": index}).run()
    assert index.data == {}
    assert report.orphans_deleted == 2


async def test_chunks_of_unknown_document_are_deleted() -> None:
    other = DocumentId("other")
    index = FakeIndex({(T, D): {1}, (T, other): {1}})
    await Reconciler(FakeScanner([state(1, 1, doc=other)]), {"dense": index}).run()
    assert index.data == {(T, other): {1}}


async def test_missing_active_version_is_reported_and_repaired() -> None:
    scanner = FakeScanner([state(1, 1)])
    index = FakeIndex({})
    first = await Reconciler(scanner, {"dense": index}).run()
    assert first.missing == (Missing(T, D, 1, "dense"),)
    assert first.repaired == 0  # no repair function configured

    calls: list[tuple[TenantId, DocumentId, int]] = []

    async def repair(tenant: TenantId, doc: DocumentId, version: int) -> bool:
        calls.append((tenant, doc, version))
        return True

    second = await Reconciler(scanner, {"dense": index}, repair).run()
    assert second.repaired == 1
    assert calls == [(T, D, 1)]


async def test_second_run_is_a_noop() -> None:
    index = FakeIndex({(T, D): {1, 2}})
    reconciler = Reconciler(FakeScanner([state(2, 2)]), {"dense": index})
    assert (await reconciler.run()).orphans_deleted == 1
    assert (await reconciler.run()).orphans_deleted == 0


async def test_reindexer_writes_chunks_without_touching_state() -> None:
    vectors = InMemoryVectorStore()
    lexical = InMemoryLexicalStore()
    reindexer = Reindexer(vectors, ParagraphChunker(max_chars=50), HashEmbedder(), lexical)
    n = await reindexer.reindex(
        DocumentEvent(Operation.UPSERT, T, D, 1, "doc", "aaa one\n\nbbb two")
    )
    assert n == 1
    ctx = SecurityContext(T, UserId("u"), frozenset({GroupId("g")}), 1)
    assert len(await vectors.search(ctx, (0.5,) * 8, top_k=5)) == 1
    assert len(await lexical.search(ctx, "aaa", top_k=5)) == 1



    