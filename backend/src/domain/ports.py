from __future__ import annotations

from collections.abc import AsyncIterator, Collection, Sequence
from typing import Protocol

from domain.models import (
    AclSnapshot,
    Chunk,
    DocumentId,
    DocumentState,
    EmbeddedChunk,
    ParsedFile,
    PromotionOutcome,
    SearchHit,
    SecurityContext,
    TenantId,
)


class DocStateStore(Protocol):
    """Authoritative record of which document version is searchable.

    The vector index is NOT the commit point; this store is. Implementations
    must make each method atomic (a single transaction or conditional write).
    """

    async def record_seen(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> DocumentState:
        """Announce that `version` exists. Creates the record if missing.

        Sets latest_seen_version = max(current, version). Never lowers it, never
        touches active_version. Safe to call repeatedly with the same event.
        """
        ...

    async def promote(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> PromotionOutcome:
        """Compare-and-set: make `version` the active one if and only if it is
        newer than the currently active version, and newer than any tombstone.

        PROMOTED       -> this call changed active_version to `version`
                          (this also revives a deleted document if version > tombstone).
        ALREADY_ACTIVE -> active_version == version already (duplicate event).
        STALE          -> a newer version is active, or a tombstone at >= version exists.
        """
        ...

    async def tombstone(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> DocumentState:
        """Mark the document deleted as of `version`.

        Applies only if `version` >= latest_seen_version, so an old delete
        cannot kill a newer revival. After this, is_searchable is False.
        """
        ...

    async def get(
        self, tenant_id: TenantId, document_id: DocumentId
    ) -> DocumentState | None:
        """Read current state, or None if the document was never seen."""
        ...

    async def get_many(
        self, tenant_id: TenantId, document_ids: Collection[DocumentId]
    ) -> dict[DocumentId, DocumentState]:
        """Batch read for the query path. Unknown documents are simply absent."""
        ...

    async def mark_purged(self, tenant_id: TenantId, document_id: DocumentId) -> None:
        """Record that every stored copy of the content was erased. A newer version clears it."""
        ...


class VectorStore(Protocol):
    """Dense similarity index. Eventually consistent; NOT the security authority."""

    @property
    def index_version(self) -> str:
        """Embedding model + index generation this store reads and writes."""
        ...

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        """Insert or overwrite chunks by chunk_id. Must be idempotent."""
        ...

    async def search(
        self, ctx: SecurityContext, query_vector: Sequence[float], top_k: int
    ) -> list[SearchHit]:
        """Nearest chunks within ctx.tenant_id only. May return stale versions;
        callers must validate each hit against DocStateStore."""
        ...

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        """Physically remove chunks of versions older than `below_version`.
        Returns how many were removed. Cleanup only."""
        ...


class Chunker(Protocol):
    def chunk(
        self,
        tenant_id: TenantId,
        document_id: DocumentId,
        version: int,
        title: str,
        text: str,
    ) -> list[Chunk]:
        """Split a document into chunks with deterministic IDs and source offsets."""
        ...


class Embedder(Protocol):
    @property
    def model_version(self) -> str: ...

    async def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]: ...



class AclReader(Protocol):
    """Query-path read of current document ACLs from a local replica."""

    async def acls_for(
        self,
        tenant_id: TenantId,
        document_ids: Collection[DocumentId],
        *,
        min_epoch: int,
    ) -> AclSnapshot:
        """Return ACLs at an epoch >= min_epoch.

        Raises AuthzUnavailable if the replica is down or behind min_epoch.
        Must never return stale ACLs silently.
        """
        ...



class LexicalStore(Protocol):
    """Keyword (BM25-style) index. Same contract as VectorStore: eventually
    consistent, tenant-scoped, and NOT the security authority."""

    async def upsert(self, chunks: Sequence[Chunk]) -> None:
        """Insert or overwrite chunks by chunk_id. Must be idempotent."""
        ...

    async def search(self, ctx: SecurityContext, query: str, top_k: int) -> list[SearchHit]:
        """Best keyword matches within ctx.tenant_id only. May return stale versions."""
        ...

    async def delete_document_versions(
        self, tenant_id: TenantId, document_id: DocumentId, *, below_version: int
    ) -> int:
        """Physically remove chunks of versions older than `below_version`."""
        ...



class Reranker(Protocol):
    async def rerank(
        self, query: str, hits: Sequence[SearchHit], top_k: int
    ) -> list[SearchHit]:
        """Reorder hits by relevance to the query. Only ever receives authorized hits."""
        ...


class LLM(Protocol):
    async def generate(self, system: str, user: str) -> str:
        """Plain text in, plain text out. No tools: nothing in a prompt can trigger an action."""
        ...



class EpochSource(Protocol):
    """Where the server learns the current policy epoch at request start."""

    async def current_epoch(self) -> int:
        """Latest committed policy epoch. Raises AuthzUnavailable if it can't be established."""
        ...


        
class StreamingLLM(Protocol):
    def stream(self, system: str, user: str) -> AsyncIterator[str]:
        """Yields the answer in pieces as the model writes it."""
        ...


class Decomposer(Protocol):
    async def decompose(self, query: str) -> list[str]:
        """Split a multi-part question into independent sub-questions, or return an empty list
        or a single item when there is nothing to split."""
        ...


class FileParser(Protocol):
    def parse(self, data: bytes) -> ParsedFile:
        """Extract text from a file's bytes, detecting the type from the content.
        Raises FileRejected with a message safe to show the uploader."""
        ...
        



        
