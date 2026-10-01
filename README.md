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

Click anywhere in the preview to jump to that place in the source; with *Preview follows
the cursor* (Settings, Ctrl+,) the preview scrolls to the paragraph you are editing.

### Optional language tools

Both are downloaded only when you ask (Settings, or the status bar for spelling), checked
against the SHA-256 in `config.toml`, and then work offline:

```sh
python scripts/install_ltex.py       # spelling and grammar (LTeX+, about 320 MB)
python scripts/install_tinymist.py   # autocomplete (Tinymist, about 70 MB)
```

### Planner (optional)

Turn it on in Settings → *Extensions*. A *Plans* button appears next to the gear: create a
plan, add steps, drag them around, and Shift-click one step and then another to make the
second wait for the first. *Next* lists what can start now. Each step has notes in Typst,
rendered below them. Plans are saved as `plans/<name>.plan.json` in the open folder.
*Export* writes `plans/<name>.typ` (a figure you `#include`; it is updated with every
change to the plan) or `plans/<name>.puml` (PlantUML).

## Windows app

Every push builds a Windows installer on GitHub Actions (workflow *Windows app*). Open the
latest run on GitHub, download the artifact **typst-writer-setup**, unzip it and run
`typst-writer-setup.exe`. It installs for your user only (no administrator rights) and adds
typst-writer to the Start menu. The installer is not signed, so Windows SmartScreen asks
once: *More info* → *Run anyway*. The app needs the Microsoft Edge WebView2 runtime, which
Windows 10 and 11 normally include.

To build it yourself on Windows (needs uv, Node.js 22+ and
[Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```sh
python scripts/build_windows.py      # -> dist/typst-writer-setup.exe
```

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
| `scripts/` | `dev.py` (start), `check.py` (all checks), tool installers, `build_windows.py` |
| `packaging/` | Windows app: PyInstaller spec, Inno Setup script, icon |
| `docs/` | UI sketch, design notes |
| `config.toml` | Ports, pinned Typst version, timings, limits, Claude model list |

Typst is pinned to **0.15.0** (typst-py). The backend refuses to start if the installed
version differs from `config.toml`.
