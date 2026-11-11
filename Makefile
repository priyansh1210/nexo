.PHONY: demo down reset test lint eval synthetic sync replay stall resume

demo:
	docker compose up --build --wait

down:
	docker compose down

# Drops the database and the demo data, so the next `make demo` regenerates data anchored to today.
reset:
	docker compose down -v

test:
	uv run pytest -q
	cd apps/web && pnpm lint

# The evaluation scenarios in evals/scenarios.yaml, with the mock model. Needs Docker running.
eval:
	uv run pytest evals -q

lint:
	uv run ruff check .
	uv run ruff format --check .

synthetic:
	uv run python -m data.synthetic.generate

# Pipeline commands run inside the running stack.
sync:
	docker compose exec dagster python -m data.pipelines.cli run

# make replay                               rebuild the whole warehouse from raw
# make replay FROM=2026-10-01 TO=2026-10-07  recompute usage for those days
replay:
	docker compose exec dagster python -m data.pipelines.cli replay $(if $(FROM),--from $(FROM) --to $(TO))

# make stall SOURCE=product_events   the source reads as stopped two days ago, and stops syncing
stall:
	docker compose exec dagster python -m data.pipelines.cli stall $(SOURCE)

resume:
	docker compose exec dagster python -m data.pipelines.cli resume $(SOURCE)
