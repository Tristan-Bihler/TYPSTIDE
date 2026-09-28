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

Open a folder, and the preview on the right always shows the folder's **main file**
(`main.typ`, or whichever file you pick with right-click → *Set as main file*), including
unsaved edits in any open chapter. *Save* (Ctrl+S) writes all changed files; *Export PDF*
exports exactly what the preview shows.

## Check

```sh
python scripts/check.py          # ruff, mypy --strict, pytest, tsc, vitest
python scripts/check.py --e2e    # plus the Playwright UI tests
```

The UI tests need Chromium once (`uv run --project backend playwright install chromium`)
and free ports 8000/5173, so stop `dev.py` first.

## Layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI app (`src/typst_writer/`), tests |
| `frontend/` | Vite + TypeScript UI (CodeMirror 6) |
| `e2e/` | Playwright UI tests |
| `scripts/` | `dev.py` (start), `check.py` (all checks) |
| `docs/` | UI sketch, design notes |
| `config.toml` | Ports, pinned Typst version, timings, limits, Claude model list |

Typst is pinned to **0.15.0** (typst-py). The backend refuses to start if the installed
version differs from `config.toml`.
