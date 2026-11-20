# Design notes

## The five questions this system was built to answer

### 1. Where is authorization enforced, given an eventually consistent index?

At query time, from authoritative state, never from index metadata.

- **Tenant** is a mandatory filter inside the search call (the method requires a
  `SecurityContext`; there is no way to call it without one), re-checked in
  `backend/src/serving/query_service.py`.
- **Version and deletes** come from Postgres (`backend/src/adapters/postgres_doc_state.py`). A hit is served
  only if its document is searchable and the hit's version equals the active version. This one
  condition hides orphan chunks, superseded versions and tombstoned documents.
- **Group ACLs** come from the ACL store (`backend/src/adapters/postgres_acl.py`), not from the chunk
  metadata. Removing a group from a document therefore takes effect even though the stale chunk
  still lists that group.

Proven by `backend/tests/test_authz.py`, `backend/tests/test_postgres_acl.py` and the permission audit in
`backend/src/eval/runner.py`.

### 2. What is the revocation linearization point, and what happens when state is behind?

Every ACL write bumps one global epoch inside the same transaction as the change, and returns it.
That returned epoch is the linearization point. A request is stamped with the current epoch by the
server at request start (`backend/src/serving/auth.py`), never by the client. The reader fails closed with
`AuthzUnavailable` (HTTP 503 with `Retry-After`) if it cannot show state at or beyond that epoch.

The honest statement for the business: *revocation takes effect for every request that starts
after the revocation is acknowledged.* A request already in flight finishes under its own epoch.

The epoch and the ACL rows are read in one repeatable-read snapshot, so a reader cannot pair a new
epoch with old ACLs.

### 3. How do you keep ingestion correct with at-least-once, unordered events?

- Commit point: `doc_state` in Postgres holds `latest_seen_version` and `active_version`
  separately, so a newer version can be in flight while the old one keeps serving.
- Chunk IDs are deterministic, so a retry overwrites instead of duplicating. Qdrant point IDs
  include the tenant (`backend/src/adapters/qdrant_stores.py`).
- The worker (`backend/src/ingestion/worker.py`) writes chunks first, then promotes with a single
  conditional `UPDATE`. A crash before the promote leaves the old version serving; a crash after it
  leaves a valid new version and a harmless retry.
- Deletes are tombstones carrying the version at which the delete happened, so a late update
  cannot resurrect a deleted document, while a genuinely newer version can revive it.
- `backend/src/ingestion/consumer.py` acks only after success, retries by re-claiming idle messages, and
  dead-letters a message after a fixed number of deliveries.
- `backend/src/ingestion/reconciler.py` repairs drift. It protects the newest seen version, because the
  worker writes chunks before promoting; deleting "everything not active" would destroy in-flight
  work.

Proven by `backend/tests/test_ingestion_worker.py`, `backend/tests/test_postgres_doc_state.py` (a 40-way race
against real Postgres), `backend/tests/test_redis_events.py` and `backend/tests/test_reconciler.py`.

### 4. How does a request stay fast and degrade safely?

`backend/src/serving/query_service.py` runs dense and lexical retrieval in parallel, each with its own
timeout, fuses by rank (RRF, because dense and BM25 scores are not comparable), checks version
and ACL, and only then reranks, so the reranker never sees an unauthorized chunk.

| Dependency | When it fails | Behaviour |
|---|---|---|
| Reranker | slow or down | fused order, reported in `degraded` |
| One retriever | slow or down | the other carries the request |
| Both retrievers | down | 503, no answer |
| Document-state store | down | 503, fail closed |
| ACL store | down or behind | 503, fail closed |
| LLM | slow or down | 200, sources only, `grounded: false` |

The rule: degrade everywhere except the security boundary. Measured stage timings are exposed per
request in a `Server-Timing` header and aggregated at `/stats`. On the measured runs generation was
about 95% of request time, so that is where the optimisation effort went
(`backend/src/adapters/resilient_llm.py`).

### 5. How do you stop prompt injection from retrieved documents?

Treat it as a data-flow problem, not something the model is trusted to notice.

- The system prompt is a constant; retrieved text never goes into it.
- Sources are wrapped in tagged blocks with `<` escaped, so a document cannot close the wrapper.
- The LLM port has no tools, so nothing in a document can trigger an action.
- Citations are validated by the service against what was actually retrieved; invented markers are
  stripped and counted. An answer with no valid citation is never reported as grounded.
- The MCP server (`backend/src/mcp_server/server.py`) has no tenant, user or group parameters on its tools,
  so a model cannot ask for another identity; identity is fixed by the credential at launch.

Proven by `backend/tests/test_answer_service.py` and `backend/tests/test_mcp_server.py`.

## Why not one knowledge base per tenant?

Per-tenant collections ("silos") are a valid design. They isolate more strongly, keep BM25
statistics clean, and make deleting a tenant trivial. They cost more as tenants multiply: every
collection carries memory and operational overhead, and an embedding-model upgrade must be rolled
out once per tenant. This project uses one pool with a mandatory tenant filter, and the vector
store sits behind a port, so mapping large tenants to dedicated collections is a single adapter
change.

Silos would only replace the tenant filter. Group-level access inside a tenant, versioned updates,
immediate deletes and unordered events would all remain, and those are what the commit point in
Postgres exists for.

## Lifecycle demo

`backend/src/serving/admin.py` can create documents, publish new versions, delete them, and publish
events in a hostile order (late versions, updates after a delete, a delayed update). The
`frontend/src/app/lifecycle/page.tsx` page shows the authoritative state next to what a search
returns, so a stale or half-written version can be seen failing to appear.

## Decisions and trade-offs

| Decision | Alternative | Why |
|---|---|---|
| Plain Python orchestration | LangChain or LangGraph | Control over timeouts, fallbacks and tracing; the request path is short |
| Ports and adapters | Direct client calls | Swap Qdrant, Gemini or the ACL store without touching the core; also what makes fault injection possible |
| Synthetic corpus | A public dataset | True answers are known, so scoring is exact and needs no LLM judge |
| One global epoch row | Per-document versions | Gives a single total order of ACL changes and a simple fail-closed rule; costs write serialization |
| ACL check after search | Group IDs in the vector filter | Authoritative and immune to stale metadata; a pre-filter is the planned addition, with this check kept as defence in depth |
| Hedged LLM calls | Plain retry | Cuts the slow tail at the cost of extra calls for the slowest requests |
| Fake LLM in tests | Always call Gemini | Deterministic tests; the real model is measured separately by the eval |

## Capacity: back-of-envelope for 10 million documents

Assumptions, not measurements: about 5 chunks per document and 384-dimension float32 vectors.

- 50 million chunks × 1.5 KB per vector is about 77 GB raw, or about 19 GB with int8 scalar
  quantization, before index graph and payload overhead.
- That does not fit one small machine, so shard by tenant (the natural isolation boundary) and keep
  hot tenants on dedicated shards.
- BM25 at that size belongs in a dedicated search engine; the lexical port makes it a one-adapter
  change.
- Expect the reranker to be the first bottleneck on CPU; the production choice is a hosted
  reranker on a GPU.

## What would change in production

- Postgres and Qdrant managed or clustered; Qdrant as a server, which also makes its payload
  indexes effective.
- Identity from a verified identity provider, with groups resolved server-side.
- A Zanzibar-style authorization store (SpiceDB or OpenFGA), whose consistency tokens are the
  epoch idea made first-class.
- Prometheus histograms in place of the in-memory `/stats` collector.
- A human-labelled evaluation set alongside the synthetic one.