import pytest
from cryptography.fernet import Fernet, InvalidToken

from adapters.encrypted_blobs import EncryptedBlobStore
from adapters.memory_blobs import InMemoryBlobStore
from domain.models import DocumentId, TenantId

T, D = TenantId("t1"), DocumentId("d1")


def key() -> str:
    return Fernet.generate_key().decode()


async def test_round_trip_and_the_stored_bytes_hide_the_content() -> None:
    inner = InMemoryBlobStore()
    s = EncryptedBlobStore(inner, [key()])
    await s.put(T, D, 1, "text", b"secret words")
    assert await s.get(T, D, 1, "text") == b"secret words"
    assert b"secret words" not in inner.data[(T, D)][(1, "text")]


async def test_a_file_copied_to_another_document_is_refused() -> None:
    inner = InMemoryBlobStore()
    s = EncryptedBlobStore(inner, [key()])
    await s.put(T, D, 1, "text", b"secret")
    inner.data[(T, DocumentId("d2"))] = {(1, "text"): inner.data[(T, D)][(1, "text")]}
    with pytest.raises(ValueError):
        await s.get(T, DocumentId("d2"), 1, "text")


async def test_the_wrong_key_cannot_read_and_rotation_keeps_old_files_readable() -> None:
    inner = InMemoryBlobStore()
    old, new = key(), key()
    await EncryptedBlobStore(inner, [old]).put(T, D, 1, "text", b"data")
    with pytest.raises(InvalidToken):
        await EncryptedBlobStore(inner, [new]).get(T, D, 1, "text")
    rotated = EncryptedBlobStore(inner, [new, old])
    assert await rotated.get(T, D, 1, "text") == b"data"
    await rotated.put(T, D, 2, "text", b"newer")
    assert await EncryptedBlobStore(inner, [new]).get(T, D, 2, "text") == b"newer"


async def test_plaintext_files_read_only_while_migrating() -> None:
    inner = InMemoryBlobStore()
    await inner.put(T, D, 1, "text", b"old plain file")
    k = key()
    assert await EncryptedBlobStore(inner, [k], allow_plaintext=True).get(T, D, 1, "text") == b"old plain file"
    with pytest.raises(InvalidToken):
        await EncryptedBlobStore(inner, [k]).get(T, D, 1, "text")
    assert EncryptedBlobStore(inner, [k]).is_encrypted(b"old plain file") is False


    