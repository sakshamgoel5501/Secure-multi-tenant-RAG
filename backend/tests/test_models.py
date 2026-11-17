from dataclasses import FrozenInstanceError

import pytest

from domain.models import (
    DocStatus,
    DocumentId,
    DocumentState,
    GroupId,
    SecurityContext,
    TenantId,
    UserId,
    make_chunk_id,
)


def test_security_context_is_immutable() -> None:
    ctx = SecurityContext(TenantId("t1"), UserId("u1"), frozenset({GroupId("g1")}), 7)
    with pytest.raises(FrozenInstanceError):
        ctx.policy_epoch = 8  # type: ignore[misc]


def test_active_version_cannot_exceed_latest_seen() -> None:
    with pytest.raises(ValueError):
        DocumentState(DocumentId("d1"), TenantId("t1"), 3, 4, DocStatus.ACTIVE)


def test_in_progress_version_keeps_old_one_searchable() -> None:
    state = DocumentState(DocumentId("d1"), TenantId("t1"), 11, 10, DocStatus.ACTIVE)
    assert state.is_searchable  # v11 is in progress, v10 still serves queries


def test_deleted_document_is_not_searchable() -> None:
    state = DocumentState(DocumentId("d1"), TenantId("t1"), 11, 11, DocStatus.DELETED)
    assert not state.is_searchable


def test_chunk_id_is_deterministic() -> None:
    a = make_chunk_id(DocumentId("d1"), 3, 0)
    assert a == make_chunk_id(DocumentId("d1"), 3, 0)
    assert a == "d1:3:0"


    