def test_packages_import() -> None:
    import adapters
    import domain
    import eval
    import ingestion
    import serving

    assert all([domain, adapters, ingestion, serving, eval])




