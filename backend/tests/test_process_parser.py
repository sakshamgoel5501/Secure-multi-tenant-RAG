import pytest

from adapters.process_parser import ProcessFileParser
from domain.errors import FileRejected


def test_parses_in_a_child_process() -> None:
    parsed = ProcessFileParser(timeout=60).parse(b"hello world")
    assert (parsed.text, parsed.kind) == ("hello world", "text")


def test_a_rejection_crosses_the_process_boundary() -> None:
    with pytest.raises(FileRejected, match="binary"):
        ProcessFileParser(timeout=60).parse(b"\x00\x01\x02")


def test_a_child_that_takes_too_long_is_killed() -> None:
    with pytest.raises(FileRejected, match="too long"):
        ProcessFileParser(timeout=0.001).parse(b"hello")  # starting Python alone takes longer

        