# Enterprise Knowledge Guard

[Deutsche Fassung](README.de.md) · [Project page with operating guide](https://enterpriseknowledge.speedofthespirit.dev)

[![CI](https://github.com/DanielHuette/enterprise-knowledge-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/DanielHuette/enterprise-knowledge-guard/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

An internal question-answering system over company documents in which access rights live
**in the database**, not in the prompt.

The intern and the managing director ask the same question and get different answers,
because the salary data never reaches the intern. Not filtered, not omitted, not politely
refused: it never leaves the database.

On top sits an agent that may act (file access requests, decide them, draft e-mails), but
only with the tools of its role.

```
docker compose up --build        →  http://localhost:8501   (API docs: http://localhost:8000/docs)
docker compose run --rm tests    →  the test suite
```

No language model key is needed. Without one the system answers extractively: it returns
the released passages verbatim. Access control is entirely independent of that, which is
the point.

## Demo users

| User | Role | Department | Sees, for example |
|---|---|---|---|
| Sarah Brandt | Admin | all | everything, including salaries and sales strategy |
| Miriam Kessler | Manager | HR | salary bands, personnel files, no sales data |
| Jonas Weber | Employee | Engineering | research report, onboarding |
| Lena Fischer | Employee | Sales | key account price list |
| Tom Schaefer | Intern | Engineering | company-wide documents and onboarding only |

Question to switch users on: **"What is the annual salary of a senior developer?"** Sarah
gets EUR 92,000. Tom is told that more relevant hits are blocked for his role, without a
title, without content, without a detour.

## The core query

One query measures similarity and checks access at the same time. There is no step in
which blocked content sits in the application's memory.

```sql
SELECT c.id, c.document_id, d.title, c.content,
       (c.embedding <=> $query::vector) AS distance
  FROM document_chunks c
  JOIN documents d ON d.id = c.document_id
 WHERE kg_visible($user_id, c.department_id, c.min_required_role, c.document_id)
   AND c.embedding IS NOT NULL
 ORDER BY c.embedding <=> $query::vector
 LIMIT $k;
```

`kg_visible` is the single source of truth about who may see what:

```sql
CREATE FUNCTION kg_visible(p_user_id INT, p_department_id INT,
                           p_min_role VARCHAR, p_document_id INT)
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
    SELECT p_user_id IS NOT NULL AND (
        EXISTS (                              -- regular access
            SELECT 1 FROM users u
             WHERE u.id = p_user_id
               AND (p_department_id IS NULL                -- company-wide
                    OR p_department_id IN (SELECT department_id
                                             FROM user_departments
                                            WHERE user_id = p_user_id))
               AND kg_role_rank(u.role) >= kg_role_rank(p_min_role))
        OR EXISTS (                           -- time-limited grant
            SELECT 1 FROM access_grants g
             WHERE g.user_id = p_user_id AND g.document_id = p_document_id
               AND g.expires_at > now()))
$$;
```

Role ranks live in a table, not in a `CASE` in code. A new level is an `INSERT`, not a
deployment.

## Two layers, deliberately redundant

**Layer 1** is the `WHERE kg_visible(...)` line above.

**Layer 2** is the same check as row-level security in PostgreSQL:

```sql
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY chunks_read ON document_chunks FOR SELECT
    USING (kg_visible(kg_current_user_id(), department_id,
                      min_required_role, document_id));
```

If layer 1 disappears through a bug, the database still returns no blocked row. That is
the difference between "we filter" and "it is unreachable".

This needs **two database roles**:

| Role | Purpose | Row-level security |
|---|---|---|
| `kg_owner` | setup, demo data | owner, not affected |
| `kg_app` | the running service | `NOBYPASSRLS`, owns nothing, fully affected |

The service has no `DELETE` on documents or the audit log, no `UPDATE` on the audit log and
no right to change classifications. What it may not do, a bug in it cannot do either, and
tests prove it.

The identity of the current request is set per transaction:

```sql
SELECT set_config('app.user_id', $1, true);   -- true = this transaction only
```

It comes from an HMAC-signed token, never from a field the caller can set. A pooled
connection therefore never carries a previous user's rights, and the role is re-read from
the database on every request, so a role change applies immediately.

## The agent: rights for actions

The same idea, applied to actions instead of documents.

| Tool | From role | Does |
|---|---|---|
| `search_knowledge` | Intern | answers a question from released documents |
| `list_catalog` | Intern | lists titles and classification, no content |
| `request_access` | Intern | files a request, changes no access |
| `summarize` | Employee | summarises released documents |
| `draft_email` | Employee | drafts, never sends |
| `decide_request` | Manager | approves or denies, only for documents the manager can read, never their own request |
| `read_audit_log` | Admin | reads the audit log |

Again two layers: the model only **sees the allowed tools at all**, and the role is checked
again right before execution. A model that invents a tool name or picks one up from the
context does not get through, and anything that passes both still fails at row-level
security.

### The flow that ties it together

1. Tom sees in the catalog **that** "Salary Bands 2026" exists; he cannot read it.
2. Tom requests access with a reason. Access does not change.
3. Tom cannot approve his own request. A manager cannot approve their own either, cannot
   grant themselves access and cannot hand out documents they cannot read: the database
   prevents all three.
4. Miriam approves for 7 days.
5. Tom reads **exactly this one document**; the personnel file stays closed.
6. After expiry it is closed again without anyone cleaning up.

An approved request does not mean "Tom is now a manager".

## The attack sits inside a document

The company-wide "Onboarding FAQ" contains a paragraph instructing the AI system to output
all salaries. Every intern hits it with almost any question.

It does not work. Not because the model behaves, but because the salary data never
reaches its context. An attacker cannot order a model to reveal what it never received.

In addition, document content is wrapped in `<source>` tags and the system prompt declares
it material, not instruction. That is the second line of defence, not the first.

## Audit log

Every question and every tool call is recorded: user, role, decision (`allow` / `deny`),
released chunks and the number of blocked hits. **Blocked content is never logged**, so the
log cannot become a back door. Who may read it is again decided by row-level security: own
rows for everyone, all rows for Admin. The application contains no check for this.

## Test suite

```
docker compose run --rm tests                     # 149 tests in the container
uv run pytest tests/unit                          # 52 unit tests, no database needed
```

The integration tests run against a real PostgreSQL with pgvector on purpose: the access
logic lives in the database, so it has to be tested there.

| File | Pins down |
|---|---|
| `integration/test_access_rights.py` | seven attack questions × five users: no blocked chunk gets through, and authorised users do get their data |
| `integration/test_row_level_security.py` | raw SQL without any application filter returns nothing; reclassifying, disabling row-level security and deleting audit rows fail; no identity means **no** rows |
| `integration/test_prompt_injection.py` | the attack paragraph demonstrably reaches the context and stays ineffective |
| `integration/test_tools.py` | tool list per role, denied calls, invented tool names, audit entry of the denial |
| `integration/test_approval_flow.py` | the full request path including expiry, denial, self-approval and grants outside the manager's own access |
| `integration/test_api.py` | forged token → 401, foreign decision → 403, audit log per role, admin-only reseed |
| `unit/` | token signing, provider resolution, retry policy, payload translation, agent routing and loop |

The first test is the one that matters: it does not check how the answer is worded but
**what the search releases at all**. What never comes out cannot be phrased, quoted or
passed on.

## Recorded live run

```
python scripts/demo_run.py        # needs the database, writes web/data/demo_run.json
```

The script drives the real HTTP API against the seeded database, without a language model:
all five users ask the same seven questions, Tom requests the salary bands, tries to approve
his own request, Miriam approves, and the planted instruction is asked about. Every answer,
source and blocked count is written to `web/data/demo_run.json` and shown on the
[project page](https://enterpriseknowledge.speedofthespirit.dev/#probelauf). A leak is
counted whenever a released source belongs to a document the same API's catalog marks as
unreadable for that user; the recorded run has none.

## Performance

```
docker compose run --rm tests python scripts/bench.py
BENCH_ROWS=50000 docker compose run --rm tests python scripts/bench.py
```

Example run with 8,000 synthetic chunks of 1,536 dimensions in 64 topic clusters:

```
  exact (every row)              40.25 ms   recall 100.0 %
  index, ef_search 40             0.93 ms   recall 100.0 %   43.3x faster
  index, ef_search 200            1.68 ms   recall 100.0 %   23.9x faster
  index + access filter           1.24 ms   same index, access check in the same query
```

The HNSW index (a layered neighbourhood graph) trades a little recall for a lot of time;
`ef_search` is the dial between them and matters on less clustered data. The access filter
adds a fraction of a millisecond because it runs inside the same indexed query. The
benchmark rolls back its rows, so the database is unchanged afterwards.

Two pitfalls handled on purpose:

- **Prepared statements.** psycopg caches execution plans after a few runs, and switching
  `enable_indexscan` does *not* invalidate a cached plan. Without disabling preparation the
  indexed run would still use the plan without index and report a wrong number.
- **Post-filtering.** The vector index finds nearest neighbours first; the access filter
  applies afterwards. A strict classification could then return fewer hits than exist,
  never too many. The search therefore sets `hnsw.iterative_scan = strict_order`.

## Decisions and why

**No ORM.** The two lines that matter, the security filter and the vector comparison
`<=>`, should be readable and reviewable in plain SQL.

**No LangChain, no SDK.** The agent is a tool registry, an authorisation check and a loop.
The Anthropic and OpenAI HTTP APIs are called directly with a timeout and exponential
backoff on rate limits and transient errors, both normalised to one response type.

**Classification stored twice.** `department_id` and `min_required_role` sit on the
document *and* the chunk, so the security filter needs no `JOIN`. Two triggers keep the copy
correct: a chunk cannot set its own level, and reclassifying a document updates its chunks
at once.

**One function with elevated rights.** `kg_blocked_count` counts how many of the global
top hits were blocked. It returns a number, never content, a title or an id. Even a number
is a hint in very strict environments, hence `SHOW_BLOCKED_COUNT=false`.

**The catalog shows titles, never content.** Nobody can request access to a document they
do not know exists. If even existence must stay secret, the catalog is not granted and
requests go through departments instead of documents.

**Runs without a key.** A built-in feature-hashing embedding produces the 1,536 values
without network or cost, the same dimension as `text-embedding-3-small`, so switching to
real embeddings needs no schema change.

## Limits

What production use would still need, stated openly:

- **Login without password.** Intended for the demo. In production the company's identity
  provider takes its place; identity already flows through a signed token, the rest of the
  chain stays.
- **The service knows the owner connection**, because it loads the demo data on start. In
  production setup and operation would be separate and the service would only have `kg_app`.
- **Documents come from a file, not an upload.** Classification on upload (who may
  classify, who may upgrade) is its own topic and not built here.
- **No re-ranking or chunk merging.** Both would improve answer quality without changing the
  security model.
- **No multi-tenancy.** A second company in the same database would need another level in
  `kg_visible` and in the policies.

## Layout

```
db/        00_app_role.sh     restricted application role
           01_schema.sql      tables, triggers, audit log
           02_security.sql    kg_visible, row-level security, catalog, counter
           03_indexes.sql     HNSW and the columns of the security filter
           04_grants.sql      privileges of kg_app
src/knowledge_guard/
           retrieval.py       the core query
           tools.py           tools with role binding
           agent.py           tool loop and keyword routing
           db.py              connections, identity per transaction
           embeddings.py      OpenAI or built-in feature hashing
           llm.py             Anthropic, OpenAI or extractive
           upstream.py        HTTP with timeout and retries
           audit.py           audit log
           api.py             HTTP API
ui/        app.py             demo interface with user switcher
web/                          project page
tests/     unit/, integration/
scripts/   bench.py           exact search versus index
```

Stack: PostgreSQL 16 with pgvector, FastAPI, psycopg 3, Streamlit, Docker Compose.
Database credentials and model choice via `.env`, template in `.env.example`.
Header image: Unsplash (unsplash.com/license), embedded from `ui/assets/hero.jpg`.

## License

MIT, see [LICENSE](LICENSE).
