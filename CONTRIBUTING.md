# Contributing

## Tooling

- Python `3.13`
- `uv` for environments and locking
- `ruff` for linting and formatting

## Setup

```bash
uv sync --extra sender
```

If you only need receiver dependencies:

```bash
uv sync
```

## Common Commands

```bash
uv run ruff check .
uv run ruff format .
uv lock
docker compose --env-file .env up -d --build
```

## Project Layout

- `src/dl_over_bale/`: application package
- `deploy/`: deployment assets baked into Docker images

## Dependency Policy

- Keep Python on `3.13.x`.
- Keep `uv` current and refresh the lockfile with a recent release.
- Use the official `yt-dlp` nightly channel for sender builds.
- Prefer minimal dependency additions and document any new required environment variables in `.env.example` and `README.md`.
