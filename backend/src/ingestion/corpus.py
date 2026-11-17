"""
A synthetic corpus is generated offline (no downloads) and is deterministic for a given seed. 
Ticket numbers and codenames repeat across tenants on purpose, so a leak between tenants would show 
up as a wrong answer.

Document texts are generated exactly as before, so your ingested data stays valid. The golden queries 
now carry an expected answer, and every 4th even-indexed one asks for an attribute the document doesn’t 
have, so the right answer is a refusal.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from domain.models import DocumentId, GroupId, TenantId

GROUPS = (GroupId("eng"), GroupId("hr"), GroupId("fin"))
_ADJ = ("amber", "brisk", "cobalt", "dusky", "ember", "frost", "golden", "hollow")
_NOUN = ("falcon", "harbor", "lantern", "meadow", "nebula", "orchard", "pylon", "quartz")
_TEAMS = ("platform", "payments", "security", "analytics", "mobile", "support")
_FACTS = (
    ("annual budget", "{n} thousand dollars"),
    ("team size", "{n} people"),
    ("review cadence", "every {n} weeks"),
    ("data retention period", "{n} months"),
    ("escalation window", "{n} hours"),
)


@dataclass(frozen=True, slots=True)
class CorpusDoc:
    tenant_id: TenantId
    document_id: DocumentId
    title: str
    text: str
    groups: tuple[GroupId, ...]


@dataclass(frozen=True, slots=True)
class GoldenQuery:
    tenant_id: TenantId
    group_id: GroupId  # a group that may read the relevant document
    question: str
    relevant_doc_id: DocumentId
    answerable: bool = True  # False: the document lacks the asked fact, so the right answer is a refusal
    expected: str = ""  # token that must appear in a correct answer


def generate_corpus(
    tenants: int = 3, docs_per_tenant: int = 40, seed: int = 7
) -> tuple[list[CorpusDoc], list[GoldenQuery]]:
    rng = random.Random(seed)
    docs: list[CorpusDoc] = []
    golden: list[GoldenQuery] = []
    for t in range(1, tenants + 1):
        tenant = TenantId(f"tenant-{t}")
        for i in range(docs_per_tenant):
            code = f"{_ADJ[i % len(_ADJ)]}-{_NOUN[(i // len(_ADJ)) % len(_NOUN)]}-{i}"
            ticket = f"TKT-{1000 + i}"
            team = rng.choice(_TEAMS)
            attr, template = rng.choice(_FACTS)
            n = rng.randint(2, 99)
            value = template.format(n=n)
            text = (
                f"Project {code} is owned by the {team} team. "
                f"The {attr} for project {code} is {value}. Tracking ticket: {ticket}."
            )
            primary = GROUPS[i % len(GROUPS)]
            groups = (primary,) if i % 5 else (primary, GROUPS[(i + 1) % len(GROUPS)])
            doc_id = DocumentId(f"t{t}-doc-{i:04d}")
            docs.append(CorpusDoc(tenant, doc_id, f"Project {code}", text, groups))

            if i % 2:
                question = f"Which project is tracked by ticket {ticket}?"
                golden.append(GoldenQuery(tenant, primary, question, doc_id, True, code))
            elif i % 4 == 2:
                other = next(a for a, _ in _FACTS if a != attr)
                question = f"What is the {other} for project {code}?"
                golden.append(GoldenQuery(tenant, primary, question, doc_id, False, ""))
            else:
                question = f"What is the {attr} for project {code}?"
                golden.append(GoldenQuery(tenant, primary, question, doc_id, True, str(n)))
    return docs, golden




