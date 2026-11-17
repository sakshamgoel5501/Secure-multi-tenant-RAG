from ingestion.corpus import generate_corpus


def test_generation_is_deterministic_for_a_seed() -> None:
    assert generate_corpus(2, 5, seed=1) == generate_corpus(2, 5, seed=1)
    docs_a, _ = generate_corpus(2, 5, seed=1)
    docs_b, _ = generate_corpus(2, 5, seed=2)
    assert docs_a != docs_b


def test_counts_and_unique_ids() -> None:
    docs, golden = generate_corpus(3, 4, seed=1)
    assert len(docs) == len(golden) == 12
    assert len({(d.tenant_id, d.document_id) for d in docs}) == 12
    assert len({d.tenant_id for d in docs}) == 3


def test_golden_queries_point_at_documents_their_group_can_read() -> None:
    docs, golden = generate_corpus(3, 10, seed=1)
    by_key = {(d.tenant_id, d.document_id): d for d in docs}
    for g in golden:
        doc = by_key[(g.tenant_id, g.relevant_doc_id)]
        assert g.group_id in doc.groups



        