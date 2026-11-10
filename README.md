# Nexo

A self-hostable customer-success assistant: ask a business question, get an investigated answer with
evidence and data freshness, then approve the follow-up actions, all in one conversation.

Status: Phase 1 (synthetic data). The five services boot and the seeded demo data exists; features
arrive phase by phase.

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
uv sync && uv run pytest -q && uv run ruff check .   # Python
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

## Layout

```text
apps/api            FastAPI service (the agent will live here)
apps/web            Next.js app
data/pipelines      Dagster definitions (dbt project arrives in Phase 2)
data/synthetic      seeded data generator with the Acme scenario
services/mock_sources   stand-in CRM and helpdesk APIs for live rechecks
db/init.sql         database schemas
```
