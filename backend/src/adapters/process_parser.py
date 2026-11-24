from __future__ import annotations

import multiprocessing
from multiprocessing.connection import Connection

from adapters.file_parsers import DefaultFileParser
from domain.errors import FileRejected
from domain.models import ParsedFile


def _child(conn: Connection, data: bytes, limits: dict[str, int], memory_bytes: int) -> None:
    try:
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        except (ImportError, ValueError, OSError):
            pass  # not supported on this platform (macOS): the timeout still applies
        parsed = DefaultFileParser(**limits).parse(data)
        conn.send(("ok", parsed.text, parsed.kind))
    except FileRejected as exc:
        conn.send(("rejected", str(exc), ""))
    except BaseException:  # noqa: BLE001
        conn.send(("error", "", ""))
    finally:
        conn.close()


class ProcessFileParser:
    """Same checks as DefaultFileParser, run in a fresh process that is killed on timeout."""

    def __init__(self, *, timeout: float = 15.0, memory_mb: int = 2048, **limits: int) -> None:
        self._timeout = timeout
        self._memory = memory_mb * 1024 * 1024
        self._limits = limits

    def parse(self, data: bytes) -> ParsedFile:
        ctx = multiprocessing.get_context("spawn")
        receive, send = ctx.Pipe(duplex=False)
        proc = ctx.Process(target=_child, args=(send, data, self._limits, self._memory), daemon=True)
        proc.start()
        send.close()
        try:
            if not receive.poll(self._timeout):
                raise FileRejected("reading the file took too long")
            kind, first, second = receive.recv()
        except EOFError:
            raise FileRejected("the file could not be read") from None
        finally:
            receive.close()
            if proc.is_alive():
                proc.kill()
            proc.join(5)
        if kind == "ok":
            return ParsedFile(first, second)
        if kind == "rejected":
            raise FileRejected(first)
        raise FileRejected("the file could not be read")
    
    