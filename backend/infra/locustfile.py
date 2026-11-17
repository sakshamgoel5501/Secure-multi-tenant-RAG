"""Load test. Run from the repo root with the venv active:
    locust -f infra/locustfile.py --headless -u 10 -r 2 -t 60s --host http://localhost:8000 --csv data/load
Env: RAG_TOKEN=<jwt> to use bearer auth (tenant-1 only); RAG_LOAD_ASK=0 to skip /ask (Gemini calls cost money)."""

import os
import random

from locust import HttpUser, between, task

from ingestion.corpus import GoldenQuery, generate_corpus

TOKEN = os.environ.get("RAG_LOAD_TOKEN")
ASK = os.environ.get("RAG_LOAD_ASK", "1") == "1"

_, _GOLDEN = generate_corpus(3, 40, 7)
GOLDEN: list[GoldenQuery] = [g for g in _GOLDEN if g.tenant_id == "tenant-1"] if TOKEN else _GOLDEN


def headers(g: GoldenQuery) -> dict[str, str]:
    if TOKEN:
        return {"Authorization": f"Bearer {TOKEN}"}
    return {
        "X-Tenant-Id": g.tenant_id,
        "X-User-Id": "load",
        "X-Groups": g.group_id,
        "X-Policy-Epoch": "0",
    }


class RagUser(HttpUser):
    wait_time = between(0.2, 1.0)

    @task(8)
    def search(self) -> None:
        g = random.choice(GOLDEN)
        self.client.post(
            "/search", json={"query": g.question, "top_k": 5}, headers=headers(g), name="/search"
        )

    @task(2)
    def ask(self) -> None:
        if not ASK:
            return
        g = random.choice(GOLDEN)
        self.client.post(
            "/ask", json={"question": g.question, "top_k": 5}, headers=headers(g), name="/ask"
        )


        