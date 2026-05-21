# AGENTS.md

## Project Overview

`dl-over-bale` transfers downloaded files through Bale using two services:

- `sender`: receives user URLs, downloads files, chunks them, and uploads parts to a Bale channel.
- `receiver`: reads the Bale channel, rebuilds files, writes them to disk, and returns protected download links.

## Tooling

- Python `3.13`
- `uv` for environments and locking
- `ruff` for linting and formatting
- Docker Compose for local service runs

## Setup

Install all dependencies, including sender-only `yt-dlp` support:

```bash
uv sync --extra sender
```

Install receiver-only dependencies:

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

- `src/`: top-level Python modules
- `src/sender.py`: sender bot and upload workflow
- `src/receiver.py`: receiver bot and public download workflow
- `deploy/`: deployment assets baked into Docker images
- `.env.example`: documented environment variables

## Development Notes

- Keep Python on `3.13.x`.
- Keep `uv` current and refresh `uv.lock` with a recent release.
- Use the official `yt-dlp` nightly channel for sender builds.
- Prefer minimal dependency additions.
- Document any new required environment variables in both `.env.example` and `README.md`.
- Do not commit secrets, generated working data, or downloaded files.
