import pytest

from cli.main import build_parser, serve_env


def parse(*argv: str):  # type: ignore[no-untyped-def]
    return build_parser().parse_args(["serve", *argv])


def test_fake_llm_removes_gcp_project() -> None:
    env = serve_env(parse("--llm", "fake"), {"GCP_PROJECT": "p"})
    assert "GCP_PROJECT" not in env


def test_chaos_flag_sets_switch_and_tight_timeouts_without_overriding() -> None:
    env = serve_env(parse("--llm", "fake", "--chaos"), {"RAG_GENERATION_TIMEOUT": "9"})
    assert env["RAG_CHAOS"] == "1"
    assert env["RAG_RETRIEVAL_TIMEOUT"] == "1"
    assert env["RAG_GENERATION_TIMEOUT"] == "9"  # an explicit value wins


def test_jwt_requires_a_secret_and_dev_mode_drops_it() -> None:
    with pytest.raises(SystemExit):
        serve_env(parse("--llm", "fake", "--jwt"), {})
    assert "RAG_JWT_SECRET" not in serve_env(parse("--llm", "fake"), {"RAG_JWT_SECRET": "s"})


def test_admin_is_off_unless_requested() -> None:
    leaked = {"RAG_ADMIN": "1"}
    assert "RAG_ADMIN" not in serve_env(parse("--llm", "fake"), leaked)
    assert serve_env(parse("--llm", "fake", "--admin"), {})["RAG_ADMIN"] == "1"



