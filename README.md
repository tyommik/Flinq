# Flinq

Self-hosted content-driven language learning platform — a LingQ-style reader, personal vocabulary, SRS and AI-assisted translation, designed for personal and small-team installations.

**Status:** pre-implementation. This repository currently contains specifications, architectural decision records (ADRs) and a project skeleton. No application logic yet.

## Documentation

All product and architecture decisions live in `docs/`:

- [`docs/lingq-like-self-hosted-spec-2026.md`](docs/lingq-like-self-hosted-spec-2026.md) — source product specification.
- [`docs/specs/2026-04-11-mvp-product-alignment-design.md`](docs/specs/2026-04-11-mvp-product-alignment-design.md) — MVP decision log.
- [`docs/architecture/2026-04-11-mvp-architecture-overview.md`](docs/architecture/2026-04-11-mvp-architecture-overview.md) — high-level architecture.
- [`docs/adr/`](docs/adr/) — ADRs (0001..0006).

Agent guidance: [`AGENTS.md`](AGENTS.md) (English) / [`AGENTS_RU.md`](AGENTS_RU.md) (Russian).

## Repository layout

```
Flinq/
├── backend/          # Python 3.13 + FastAPI + SQLAlchemy + Taskiq
├── frontend/         # React 19 + TypeScript + Vite + Tailwind v4
├── docs/             # Product and architecture docs
├── scripts/          # Dev and build helper scripts
├── docker-compose.yml
├── docker-compose.dev.yml
└── .github/workflows/
```

See [ADR-0006](docs/adr/ADR-0006-tech-stack.md) for the full tech stack.

## Quick start (development)

Requirements: Docker, `uv` (backend deps), `pnpm` (frontend deps).

```bash
# 1. Copy env template
cp .env.example .env

# 2. Install backend deps
cd backend && uv sync && cd ..

# 3. Install frontend deps
cd frontend && pnpm install && cd ..

# 4. Bring up the dev stack (Postgres, Redis, API, worker, frontend dev server)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Backend API: <http://localhost:8000>
Frontend dev server: <http://localhost:5173>
Health check: <http://localhost:8000/health>

## Production build

```bash
docker compose up --build -d
```

This builds and runs `app-api` and `app-worker` containers, both serving the frontend static assets from the same `backend/` image.

## Development commands

### Backend

```bash
cd backend
uv sync                          # install deps
uv run flinq serve               # run API locally (http://localhost:8000)
uv run flinq worker              # run Taskiq worker
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run pyright                   # type check
uv run alembic upgrade head      # apply migrations
uv run alembic revision --autogenerate -m "message"  # create a migration
```

### Frontend

```bash
cd frontend
pnpm install                     # install deps
pnpm dev                         # start Vite dev server
pnpm build                       # production 80build
pnpm test                        # run Vitest
pnpm lint                        # ESLint
pnpm format                      # Prettier
```

## License

MIT — see [LICENSE](LICENSE).

Note: Flinq uses Wiktionary-derived dictionary data under CC-BY-SA 4.0. Attribution is shown in the UI wherever dictionary data is displayed. See [ADR-0004](docs/adr/ADR-0004-dictionary-wiktionary-provider.md).
