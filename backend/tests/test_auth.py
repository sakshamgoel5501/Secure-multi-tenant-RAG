import time

import httpx
import jwt

from adapters.fake_embedder import HashEmbedder
from adapters.memory_acl import InMemoryAclPrimary, InMemoryAclReplica
from adapters.memory_doc_state import InMemoryDocStateStore
from adapters.memory_vector_store import InMemoryVectorStore
from adapters.simple_chunker import ParagraphChunker
from domain.errors import AuthzUnavailable
from domain.models import DocumentEvent, DocumentId, GroupId, Operation, TenantId
from ingestion.worker import IngestionWorker
from serving.api import create_app
from serving.auth import jwt_identity
from serving.query_service import QueryService

SECRET = "s" * 32
T = TenantId("t1")
D = DocumentId("d1")


class FakeEpochs:
    def __init__(self, epoch: int = 0, down: bool = False) -> None:
        self.epoch = epoch
        self.down = down

    async def current_epoch(self) -> int:
        if self.down:
            raise AuthzUnavailable("epoch source down")
        return self.epoch


def token(
    *,
    secret: str = SECRET,
    tenant: str = "t1",
    groups: tuple[str, ...] = ("g1",),
    aud: str = "rag",
    exp_in: int = 3600,
) -> str:
    now = int(time.time())
    claims = {
        "sub": "u1",
        "tenant": tenant,
        "groups": list(groups),
        "aud": aud,
        "iat": now,
        "exp": now + exp_in,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def bearer(**kwargs: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(**kwargs)}"}  # type: ignore[arg-type]


async def build(
    epochs: FakeEpochs, *, sync_replica_after: int | None = None
) -> tuple[httpx.AsyncClient, InMemoryAclPrimary, InMemoryAclReplica]:
    state = InMemoryDocStateStore()
    vectors = InMemoryVectorStore()
    embedder = HashEmbedder()
    worker = IngestionWorker(state, vectors, ParagraphChunker(max_chars=200), embedder)
    await worker.handle(DocumentEvent(Operation.UPSERT, T, D, 1, "doc", "aaa one"))
    primary = InMemoryAclPrimary()
    replica = InMemoryAclReplica(primary)
    primary.set_acl(T, D, {GroupId("g1")})
    replica.sync()
    service = QueryService(state, vectors, embedder, replica)
    app = create_app(service, identity=jwt_identity(SECRET, epochs))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, primary, replica


async def test_valid_token_is_authenticated_and_authorized() -> None:
    c, _, _ = await build(FakeEpochs(1))
    r = await c.post("/search", json={"query": "q"}, headers=bearer())
    assert r.status_code == 200
    assert [h["document_id"] for h in r.json()["hits"]] == ["d1"]


async def test_missing_token_is_401() -> None:
    c, _, _ = await build(FakeEpochs(1))
    assert (await c.post("/search", json={"query": "q"})).status_code == 401


async def test_expired_token_is_401() -> None:
    c, _, _ = await build(FakeEpochs(1))
    r = await c.post("/search", json={"query": "q"}, headers=bearer(exp_in=-10))
    assert r.status_code == 401


async def test_token_signed_with_wrong_secret_is_401() -> None:
    c, _, _ = await build(FakeEpochs(1))
    r = await c.post("/search", json={"query": "q"}, headers=bearer(secret="x" * 32))
    assert r.status_code == 401


async def test_wrong_audience_is_401() -> None:
    c, _, _ = await build(FakeEpochs(1))
    r = await c.post("/search", json={"query": "q"}, headers=bearer(aud="other"))
    assert r.status_code == 401


async def test_token_groups_win_over_client_headers() -> None:
    c, _, _ = await build(FakeEpochs(1))
    headers = {**bearer(groups=("g2",)), "X-Groups": "g1"}  # try to claim g1 via a header
    r = await c.post("/search", json={"query": "q"}, headers=headers)
    assert r.status_code == 200 and r.json()["hits"] == []


async def test_client_supplied_epoch_is_ignored() -> None:
    epochs = FakeEpochs(epoch=1)
    c, primary, replica = await build(epochs)
    epochs.epoch = primary.set_acl(T, D, {GroupId("g2")})  # revocation committed; replica behind
    headers = {**bearer(), "X-Policy-Epoch": "0"}  # client lies about the epoch
    r = await c.post("/search", json={"query": "q"}, headers=headers)
    assert r.status_code == 503  # the server's epoch was used, so the lagging replica fails closed
    replica.sync()
    assert (await c.post("/search", json={"query": "q"}, headers=bearer())).json()["hits"] == []


async def test_epoch_source_down_fails_closed() -> None:
    c, _, _ = await build(FakeEpochs(down=True))
    r = await c.post("/search", json={"query": "q"}, headers=bearer())
    assert r.status_code == 503


    