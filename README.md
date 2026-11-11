# Nexo

A self-hostable customer-success assistant: ask a business question, get an investigated answer with
evidence and data freshness, then approve the follow-up actions, all in one conversation.

Status: Phase 4 (assistant, read side). Ask questions about accounts and get answers with evidence,
freshness notes and labelled hypotheses. Actions with approval arrive in Phase 5, the UI in Phase 6.

## Quickstart

Needs Docker only. No API keys.

```bash
docker compose up --build --wait   # or: make demo
```

| Service | URL |
| --- | --- |
| Web | http://localhost:3000 |
| API | http://localhost:8000/health |
| Dagster | http://localhost:3001 |
| Mock source systems | http://localhost:8001/health |

Stop with `docker compose down` (add `-v` to drop the database volume).

## Development

```bash
uv sync && uv run pytest -q && uv run ruff check .   # Python; the pipeline tests need Docker running
cd apps/web && pnpm install && pnpm lint && pnpm build   # Web
```

## Synthetic data

```bash
uv run python -m data.synthetic.generate   # or: make synthetic
```

Writes accounts, contacts, invoices, tickets, documents and about 100,000 product events to
`data/synthetic/out/`. The same `--seed` and `--as-of` date give byte-identical files. The data
carries the demo story: six accounts renew next month, three are at risk, and Acme Corp's usage fell
40% after an import problem its admin reported in a ticket that is still open.

## API

Interactive docs are at http://localhost:8000/docs. Sign in first; the session is an HTTP-only cookie.

| Demo sign-in | Role | Can |
| --- | --- | --- |
| `viewer@nexo.example` | viewer | read accounts, notes, tasks and data freshness |
| `maya.okafor@nexo.example` (also `daniel.reyes`, `aiko.tanaka`, `lena.fischer`) | csm | also write notes and tasks, and read the audit log |
| `admin@nexo.example` | admin | everything, including users and API keys |

The password for every demo sign-in is `nexo-demo`. After 5 wrong passwords for one email, sign-in for that
email is blocked for 15 minutes. They exist only because the Compose file sets
`NEXO_DEMO_USERS=1`; remove that line for anything but a demo.

```bash
curl -c cookies.txt -H 'Content-Type: application/json'   -d '{"email": "maya.okafor@nexo.example", "password": "nexo-demo"}' http://localhost:8000/auth/login
curl -b cookies.txt http://localhost:8000/accounts/acct_acme
```

To add real users, create the first admin from the command line (the password is asked for):

```bash
docker compose exec api python -m apps.api.users create --email you@company.com --name "Your Name"
```

That admin can then add others with `POST /users`. `GET /accounts/{id}/usage` gives usage per feature
and a 60-day daily series for a chart.

Every response that carries account data also carries `freshness` (each source's last sync and
whether it is stale) and `checks` (whether the warehouse tests passed). Every write adds a row to
the append-only audit log in the same transaction.

### Pushing data in

Besides the hourly pull, a source system can push records. An admin creates an API key once:

```bash
curl -b cookies.txt -H 'Content-Type: application/json' -d '{"name": "product backend"}'   http://localhost:8000/api-keys          # the key is shown once; only its hash is stored
```

| Route | Body |
| --- | --- |
| `POST /ingest/events` | `{"events": [...]}`, up to 5,000 product events |
| `POST /ingest/tickets` | `{"tickets": [...]}`, up to 1,000 support tickets |
| `POST /import/crm/accounts`, `/import/crm/contacts` | the CRM's CSV export, as `text/csv`, up to 5 MB |

Send the key as `Authorization: Bearer <key>`. Everything is validated before it lands: one bad
record or CSV row refuses the whole batch, with the reasons, and nothing is stored. Accepted records
reach the warehouse on the next pipeline run (`make sync` to run it now). Revoke a key with
`DELETE /api-keys/{key_id}`.

## Asking the assistant

```bash
curl -b cookies.txt -H 'Content-Type: application/json'   -d '{"message": "Which customers renewing next month need attention?"}'   http://localhost:8000/conversations/demo/messages
curl -b cookies.txt -H 'Content-Type: application/json' -d '{"message": "Investigate Acme."}'   http://localhost:8000/conversations/demo/messages
```

Each answer has a `summary`, `observations` (facts, each citing the tool calls it came from),
`hypotheses` (possible causes, labelled as such), `data_notes` (what is stale or failed a check, and
what that means), `evidence` (the records behind each tool call) and `tool_calls`. A conversation is
private to the user who started it; `GET /conversations/{id}` lists its earlier questions.

Three rules hold whatever the model does, because they are enforced in code:

- A field whose source is stale, or whose warehouse check failed, is withheld before the model sees
  it, and the answer says so.
- A claim with a number that is not in the data it cites is dropped, and listed under
  `dropped_claims`.
- Ticket and document text is marked as customer-written, and the tools can only read.

The default model is a rule-based mock that needs no key. To use Claude, set
`NEXO_MODEL_PROVIDER=claude` and `ANTHROPIC_API_KEY` for the `api` service (model
`claude-opus-5-5` by default; override with `NEXO_CLAUDE_MODEL`).

### Evaluations

`make eval` (or `uv run pytest evals -q`) runs the scenarios in `evals/scenarios.yaml`: the at-risk
renewals, the Acme investigation, stale usage data, a failed warehouse check, an account with no
linked workspace, a prompt-injection ticket, and a freshness question. Each runs on its own copy of
the seeded warehouse.

## Data pipeline

Every hour (and once at startup) the pipeline lands new records in the append-only `raw` schema,
then dbt builds and tests the warehouse. The models the assistant reads are in `marts`.

| Command | What it does |
| --- | --- |
| `make sync` | Run the pipeline now |
| `make replay` | Rebuild the whole warehouse from `raw` |
| `make replay FROM=2026-10-01 TO=2026-10-07` | Recompute usage for a range of days |
| `make stall SOURCE=product_events` | Make a source look as if it stopped two days ago |
| `make resume SOURCE=product_events` | Undo a stall |
| `make reset` | Drop the database and demo data; the next `make demo` regenerates them |

Without `make`, run the same thing directly, for example
`docker compose exec dagster python -m data.pipelines.cli stall product_events`.

- **Freshness** is in `meta.source_freshness`: each source's last successful sync and whether it is
  `fresh` or `stale` (older than twice its expected interval).
- **Check results** from the latest build are in `meta.check_results`, one row per test.
- **Duplicates and late events** are handled in one place: an event id is staged once, and a run
  recomputes exactly the days that received new events.
- **Records that match no account** are listed in `marts.identity_unmatched`, never dropped.
- The demo data is anchored to the day it was generated. After a few days, `make reset` and
  `make demo` give a fresh set.

## Layout

```text
apps/api            FastAPI service: sign-in and roles, accounts, notes, tasks, audit, users
apps/api/agent      the assistant: read tools, model providers, the conversation graph
evals               evaluation scenarios and their runner
apps/web            Next.js app
data/connectors.py  the connector interface and the three connectors
data/pipelines      sync runner, pipeline commands, Dagster job
data/dbt            warehouse models, tests and the accounts history snapshot
data/synthetic      seeded data generator with the Acme scenario
services/mock_sources   stand-in CRM and helpdesk APIs for live rechecks
db/init.sql         database schemas
```
