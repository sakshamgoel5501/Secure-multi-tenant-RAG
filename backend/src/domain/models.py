from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

# NewType makes mypy reject passing a UserId where a TenantId is expected.
TenantId = NewType("TenantId", str)
DocumentId = NewType("DocumentId", str)
UserId = NewType("UserId", str)
GroupId = NewType("GroupId", str)
ChunkId = NewType("ChunkId", str)


@dataclass(frozen=True, slots=True)
class SecurityContext:
    """Who is asking. Every query method will require one (isolation by construction)."""

    tenant_id: TenantId
    user_id: UserId
    group_ids: frozenset[GroupId]
    policy_epoch: int  # authorization state version this request is evaluated against


class DocStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"  # tombstone: authoritative even if vectors still exist


class PromotionOutcome(StrEnum):
    """Result of the compare-and-set that makes a version searchable."""

    PROMOTED = "promoted"  # we won: this version is now active
    ALREADY_ACTIVE = "already_active"  # duplicate event, safe no-op
    STALE = "stale"  # a newer version is already committed, discard this work


@dataclass(frozen=True, slots=True)
class DocumentState:
    """Commit-point record. This, not the vector index, decides what is searchable."""

    document_id: DocumentId
    tenant_id: TenantId
    latest_seen_version: int  # highest version any event has announced (may be in progress)
    active_version: int | None  # version currently searchable (None = nothing yet)
    status: DocStatus

    def __post_init__(self) -> None:
        if self.active_version is not None and self.active_version > self.latest_seen_version:
            raise ValueError("active_version cannot exceed latest_seen_version")

    @property
    def is_searchable(self) -> bool:
        return self.status is DocStatus.ACTIVE and self.active_version is not None


def make_chunk_id(document_id: DocumentId, version: int, ordinal: int) -> ChunkId:
    """Deterministic ID: retrying the same work overwrites instead of duplicating."""
    return ChunkId(f"{document_id}:{version}:{ordinal}")


@dataclass(frozen=True, slots=True)
class Chunk:
    """What ingestion produces and the stores index."""

    chunk_id: ChunkId
    tenant_id: TenantId
    document_id: DocumentId
    version: int
    ordinal: int
    text: str
    title: str
    section: str | None
    start_offset: int
    end_offset: int


class RetrievalSource(StrEnum):
    DENSE = "dense"
    LEXICAL = "lexical"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class SearchHit:
    """What retrieval returns. Carries everything citations and the final authz check need."""

    chunk_id: ChunkId
    tenant_id: TenantId  # lets the final check verify tenant match without a lookup
    document_id: DocumentId
    version: int  # compared against the active version at query time
    title: str
    section: str | None
    start_offset: int
    end_offset: int
    text: str
    score: float
    source: RetrievalSource


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """A chunk plus its embedding vector, ready to index."""

    chunk: Chunk
    vector: tuple[float, ...]


class Operation(StrEnum):
    UPSERT = "upsert"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class DocumentEvent:
    """One at-least-once message: may be duplicated, delayed or out of order."""

    operation: Operation
    tenant_id: TenantId
    document_id: DocumentId
    version: int
    title: str = ""
    text: str = ""

    
@dataclass(frozen=True, slots=True)
class AclSnapshot:
    """Document ACLs as of `epoch`. A document missing from `acls` has no grants."""

    epoch: int
    acls: dict[DocumentId, frozenset[GroupId]]



@dataclass(frozen=True, slots=True)
class Citation:
    marker: str  # the "S1" the model wrote; maps to exactly one retrieved chunk
    chunk_id: ChunkId
    document_id: DocumentId
    version: int
    title: str
    section: str | None
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    citations: tuple[Citation, ...]
    grounded: bool  # True only if the text carries at least one validated citation
    degraded: tuple[str, ...]  # stages that failed or timed out, for observability
    invalid_citations: int = 0




    


    



    