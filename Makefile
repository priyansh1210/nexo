.PHONY: demo down test lint synthetic

demo:
	docker compose up --build --wait

down:
	docker compose down

test:
	uv run pytest -q
	cd apps/web && pnpm lint

lint:
	uv run ruff check .
	uv run ruff format --check .

synthetic:
	uv run python -m data.synthetic.generate
