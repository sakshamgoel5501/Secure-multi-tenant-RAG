import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
PATH = re.compile(r"`((?:backend|frontend)/[\w./-]+)`")


@pytest.mark.parametrize("doc", ["README.md", "DESIGN.md"])
def test_every_path_mentioned_in_docs_exists(doc: str) -> None:
    text = (REPO / doc).read_text()
    paths = set(PATH.findall(text))
    assert paths, f"{doc} mentions no paths"
    missing = sorted(p for p in paths if not (REPO / p).exists())
    assert missing == []

    