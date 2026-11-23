from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence

DEFAULT_PG = "postgresql://localhost/rag"
DEFAULT_REDIS = "redis://localhost:6379/0"

# Subcommands that simply forward their arguments to an existing module.
PASSTHROUGH = {
    "load": "ingestion.load_corpus",
    "eval": "eval.main",
    "chaos-run": "eval.chaos",
    "reconcile": "ingestion.reconcile_main",
    "token": "serving.mint_token",
    "mcp": "mcp_server.server",
    "seed-users": "ingestion.seed_users",
    "migrate-tenant": "ingestion.migrate_tenant",
}


def serve_env(args: argparse.Namespace, base: Mapping[str, str]) -> dict[str, str]:
    """Pure function: the environment the server needs for the chosen flags."""
    env = dict(base)
    if args.llm == "fake":
        env.pop("GCP_PROJECT", None)
    elif not env.get("GCP_PROJECT"):
        project = _gcloud_project()
        if project is None:
            raise SystemExit("--llm gemini needs GCP_PROJECT, and gcloud returned no project")
        env["GCP_PROJECT"] = project
    if args.chaos:
        env["RAG_CHAOS"] = "1"
        env.setdefault("RAG_RETRIEVAL_TIMEOUT", "1")
        env.setdefault("RAG_RERANK_TIMEOUT", "1")
        env.setdefault("RAG_GENERATION_TIMEOUT", "3")
    else:
        env.pop("RAG_CHAOS", None)  # never mount /chaos unless explicitly asked
    if args.admin:
        env["RAG_ADMIN"] = "1"
    else:
        env.pop("RAG_ADMIN", None)
    if args.jwt and not env.get("RAG_JWT_SECRET"):
        raise SystemExit("--jwt needs RAG_JWT_SECRET exported (same value for `rag token`)")
    if not args.jwt:
        env.pop("RAG_JWT_SECRET", None)
    return env


def _gcloud_project() -> str | None:
    try:
        out = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def _serve(args: argparse.Namespace) -> int:
    app = "serving.main:app" if args.memory else "serving.main_stack:app"
    env = serve_env(args, os.environ) if not args.memory else dict(os.environ)
    cmd = [sys.executable, "-m", "uvicorn", app, "--host", args.host, "--port", str(args.port), "--log-level", "info"]
    print(f"[rag] {' '.join(cmd)}")
    os.execvpe(sys.executable, cmd, env)  # replaces this process; Ctrl+C reaches uvicorn directly


def _forward(module: str, rest: Sequence[str]) -> int:
    return subprocess.call([sys.executable, "-m", module, *rest])


def _test(args: argparse.Namespace) -> int:
    env = dict(os.environ)
    if args.all:
        env.setdefault("RAG_PG_DSN", "postgresql://localhost/rag_test")  # scratch DB: tests TRUNCATE
        env.setdefault("RAG_REDIS_URL", DEFAULT_REDIS)
        env.setdefault("RAG_RUN_MODEL_TESTS", "1")
    steps = [
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "mypy", "src", "tests"],
        [sys.executable, "-m", "ruff", "check", "."],
    ]
    for step in steps:
        if subprocess.call(step, env=env) != 0:
            return 1
    return 0


def _loadtest(rest: Sequence[str]) -> int:
    extra = list(rest)
    if "-t" not in extra and "--run-time" not in extra:
        extra += ["-t", "60s"]  # always bounded
    if "-u" not in extra and "--users" not in extra:
        extra += ["-u", "10"]
    if "-r" not in extra and "--spawn-rate" not in extra:
        extra += ["-r", "2"]
    cmd = [
        sys.executable, "-m", "locust", "-f", "infra/locustfile.py", "--headless",
        "--host", "http://localhost:8000", "--csv", "data/load", *extra,
    ]  # fmt: skip
    return subprocess.call(cmd)


async def _doctor() -> int:
    ok = True

    async def check(name: str, probe: object) -> None:
        nonlocal ok
        try:
            detail = await probe  # type: ignore[misc]
            print(f"  ok    {name}: {detail}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  FAIL  {name}: {exc!r}"[:140])

    async def postgres() -> str:
        import asyncpg

        conn = await asyncpg.connect(os.environ.get("RAG_PG_DSN", DEFAULT_PG), timeout=3)
        try:
            return str(await conn.fetchval("SHOW server_version"))
        finally:
            await conn.close()

    async def redis() -> str:
        from redis.asyncio import Redis

        r = Redis.from_url(os.environ.get("RAG_REDIS_URL", DEFAULT_REDIS))
        try:
            await r.ping()
            return "PONG"
        finally:
            await r.aclose()

    async def gcp() -> str:
        project = os.environ.get("GCP_PROJECT") or _gcloud_project()
        if not project:
            raise RuntimeError("no project (fine if you only use --llm fake)")
        return project

    print("rag doctor")
    await check("postgres", postgres())
    await check("redis", redis())
    await check("gcp project", gcp())
    print(f"  info  server mode: {'JWT' if os.environ.get('RAG_JWT_SECRET') else 'dev headers'}")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rag", description="Entry point for the RAG project")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="start the API server")
    s.add_argument("--memory", action="store_true", help="in-memory demo: no Postgres/Redis/Qdrant")
    s.add_argument("--llm", choices=("fake", "gemini"), default="gemini")
    s.add_argument("--chaos", action="store_true", help="mount /chaos with tight timeouts")
    s.add_argument("--jwt", action="store_true", help="verified identity (needs RAG_JWT_SECRET)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--admin", action="store_true", help="mount /admin (needs RAG_ADMIN_KEY)")

    t = sub.add_parser("test", help="pytest, then mypy, then ruff")
    t.add_argument("--all", action="store_true", help="also run Postgres, Redis and model tests")

    sub.add_parser("doctor", help="check that Postgres, Redis and GCP are reachable")
    sub.add_parser("loadtest", help="Locust; extra args pass through, e.g. -u 40 -t 120s")
    for name, module in PASSTHROUGH.items():
        sub.add_parser(name, help=f"runs {module}; extra args pass through")
    return p


def main() -> None:
    argv = sys.argv[1:]
    # Forwarded subcommands keep their own flags (e.g. `rag eval --revocation`).
    if argv and argv[0] in PASSTHROUGH:
        sys.exit(_forward(PASSTHROUGH[argv[0]], argv[1:]))
    if argv and argv[0] == "loadtest":
        sys.exit(_loadtest(argv[1:]))

    args = build_parser().parse_args(argv)
    if args.command == "serve":
        sys.exit(_serve(args))
    if args.command == "test":
        sys.exit(_test(args))
    if args.command == "doctor":
        sys.exit(asyncio.run(_doctor()))
    sys.exit(0)


if __name__ == "__main__":
    main()



    