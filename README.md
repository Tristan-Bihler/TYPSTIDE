# typst-writer

Local, offline-first Typst editor with a Word-like workflow: file actions and an insert
toolbar on top, file tree and problems on the left, source in the middle, live rendered
document on the right. AI assistance is optional and off by default.

See [CLAUDE.md](CLAUDE.md) for goals, architecture and the phase plan, and
[docs/ui-sketch.png](docs/ui-sketch.png) for the layout sketch.

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 automatically if needed)
- Node.js 22+ with npm

## Run

```sh
python scripts/dev.py
```

Starts the backend on `127.0.0.1:8000` and the frontend on
<http://127.0.0.1:5173>. Ctrl+C stops both. Ports live in `config.toml`.

## Check

```sh
python scripts/check.py
```

Runs ruff (lint + format), `mypy --strict`, pytest, `tsc` and vitest.

## Layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI app (`src/typst_writer/`), tests |
| `frontend/` | Vite + TypeScript UI |
| `scripts/` | `dev.py` (start), `check.py` (all checks) |
| `config.toml` | Ports, pinned Typst version, timings, limits, Claude model list |

Typst is pinned to **0.15.0** (typst-py). The backend refuses to start if the installed
version differs from `config.toml`.
