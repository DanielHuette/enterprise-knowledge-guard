# Refactoring report

[Deutsche Fassung](REFACTORING_REPORT.de.md)

## Scope

**Context:** Rework of `enterprise-knowledge-guard` into an English, typed, production-grade code base | **Input:** original service (German identifiers, UI, data and tests; 74 tests) | **Output:** same security model, English throughout, 149 tests

| Item | Before | After |
|---|---|---|
| Language of code, API, UI, demo data, page | German | English (README also in German) |
| Package | `api/app` with path hacks in tests | installable `src/knowledge_guard` |
| Tests | 74, database only | 149: 52 unit, 97 integration |
| Line coverage | not measured | 96 % |
| `mypy --strict` | not run | 0 errors |
| Linting | none | ruff incl. security rules (bandit) |
| Dependencies | unpinned ranges per service | `uv.lock`, exported `requirements*.txt` |
| CI | none | lint, types, unit tests, integration tests in Docker |

## Security fixes

**Context:** Defects that weakened the access model | **Input:** original code | **Output:** fixes with regression tests

| Finding | Change | Evidence |
|---|---|---|
| `POST /admin/seed?force=true` needed no login and could wipe every table | Bearer token and Admin role required | `test_reseed_requires_admin` |
| A manager could approve their own access request | Policy `requests_decide` forbids deciding one's own request | `test_nobody_approves_their_own_request` |
| A manager could insert a grant for themselves directly | Policy `grants_insert` forbids grants to oneself | `test_managers_cannot_grant_themselves_access` |
| A manager could release documents outside their own access (HR approving sales documents) | New `kg_has_regular_access`; deciding and granting require regular access to the document | `test_managers_cannot_hand_out_documents_they_cannot_read` |
| SECURITY DEFINER functions were executable by PUBLIC | `REVOKE EXECUTE ... FROM PUBLIC`, granted to the service only | `db/04_grants.sql` |
| A non-ASCII token signature caused HTTP 500 | Signatures compared as bytes | `test_malformed_tokens_are_rejected` |
| Impossible decisions returned HTTP 200 with an error field and were audited as allowed | `ActionRejected` → 404/422, audited as `deny`; UI shows buttons only where the server allows a decision | `test_impossible_decision_is_404_and_audited` |
| Agent could create grants with negative or unbounded duration | Days validated to 1-365 on every path | `test_invalid_decisions_are_rejected` |
| A malformed token payload caused HTTP 500 | Decoding errors map to 401 | `test_malformed_tokens_are_rejected` |
| On pgvector < 0.8 the fallback rolled back the transaction and dropped the caller's identity | Savepoint around the optional setting | `retrieval._enable_iterative_scan` |
| Containers ran as root | Dedicated unprivileged user in both images | `Dockerfile`, `ui/Dockerfile` |
| Document titles were inserted unescaped into the prompt markup | Titles are HTML-escaped | `test_context_marks_documents_as_material_and_escapes_titles` |

## Robustness

**Context:** Behaviour under load and failure | **Input:** single attempts, broad exceptions | **Output:** bounded retries, precise errors

| Finding | Change | Evidence |
|---|---|---|
| Model and embedding calls had no retry | Exponential backoff on 429/5xx/network errors, bounded, configurable | `tests/unit/test_llm_and_upstream.py` |
| Provider failures surfaced as HTTP 500 with a traceback | `UpstreamError` → HTTP 502 with a clear message | `api._upstream_failed` |
| Startup wait caught every exception | Waits only on `OperationalError`, with a deadline | `db.wait_for_database` |
| Connection pool never closed | Closed on shutdown | `api.lifespan` |
| Settings read at import time via `os.getenv` | `pydantic-settings`, validated ranges, secrets as `SecretStr` | `tests/unit/test_auth_and_config.py` |
| Keyword router concatenated all digits ("document 4 for 7 days" → 47) | First number only; word-boundary matching | `test_request_uses_the_first_number_only` |
| Benchmark committed nothing but deleted rows by title | Runs in one transaction and rolls back | `scripts/bench.py` |
| Plan check of the benchmark reported a sequential scan after the wide run | Search width reset before the check | benchmark output |
| Benchmark noise was so large that the "topic clusters" were uniform random vectors | Noise scaled to the dimension; filtered run no longer inherits the wide search setting | README performance section |

## Structure

**Context:** Single responsibility and typing | **Input:** dict-based modules | **Output:** typed modules

| Finding | Change | Evidence |
|---|---|---|
| Users passed around as dicts | `User`, `Hit`, `SearchResult` dataclasses | `models.py` |
| Duplicated HTTP code in `llm.py` and `embeddings.py` | One `upstream.post_json` | `upstream.py` |
| Agent loop of 100 lines | Split into routing, model loop and tool call | `agent.py` |
| API responses untyped | Pydantic request and response models | `/docs` |
| Tool handlers returned private `_chunk_ids` keys mixed into results | Handlers return result and search separately | `tools.Handler` |

## Publication

**Context:** Bringing the reworked version to GitHub and the project page | **Input:** the local rework, the German project page | **Output:** CI, a recorded live run, a bilingual page

| Finding | Change | Evidence |
|---|---|---|
| The README shows a CI badge, but no workflow existed | `.github/workflows/ci.yml`: pgvector service, roles and schema as the container sets them up, ruff, mypy, pytest | CI run on the first push |
| The project page described the system but showed no run of it | `scripts/demo_run.py` records five users × seven questions, the approval path, the planted instruction and a forged token through the real API | `web/data/demo_run.json`, 0 leaks |
| The live page was German and named the German interface of the old version | one page in German and English; quoted outputs, button and tab names are those of the English interface | browser run at 390 px and 1280 px, both languages |

## Final check

**Context:** Acceptance before publication | **Input:** fresh images, fresh database | **Output:** all checks passed

| Check | Result |
|---|---|
| `ruff format --check`, `ruff check` (src, tests, scripts, ui) | passed |
| `mypy --strict src scripts` | 0 errors |
| `pytest` locally against pgvector | 149 passed, 96 % coverage, warnings treated as errors |
| `docker compose` build of api, test and ui images | passed |
| Full stack: health check, UI reachable, 149 tests inside the test container | passed |
| Benchmark inside the container | runs, leaves no rows behind |
| UI walk-through (switch user, ask, catalog) in a headless browser | as described in the guide |
| `scripts/demo_run.py` against PostgreSQL 16 with pgvector 0.8.1 | 35 answers, 0 leaks, self-approval 403, forged token 401 |
| `scripts/bench.py` with 5,015 and 50,015 chunks | index 28× and 105× faster than the exact search, recall 100 % and 96 % at ef_search 40 |
| Search for secrets, local paths, German leftovers, TODO, debug output | nothing found |
| Independent security and code review | 10 findings, all fixed with regression tests |
