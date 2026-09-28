# Design notes

**Subject:** a writing desk for long academic documents (German/English theses) in Typst.
**Audience:** a student or researcher who writes for hours and wants to see the real
typeset page, not learn syntax. **Primary job:** write in the middle, see the finished
main document on the right, always.

## Principles

- **The rendered page is the hero.** Pages sit on a cool grey "desk" with a paper
  shadow. Everything else is quiet, flat chrome.
- **One ink colour for state.** The royal-blue ink of the hand-drawn sketch
  (`docs/ui-sketch.png`) marks only what is active or important: focus, active tab,
  selected tree item, the main-file badge. No decorative colour anywhere else.
- **Words over icons.** File actions are labelled like in a word processor; icons are
  small helpers, never alone (except zoom − / +).
- **Plain status, no jargon.** "Compiled in 12 ms", "1 error", "No main file".
- **Offline:** no web fonts. System UI font; a system monospace for source.

## Tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `--paper` | `#ffffff` | `#16181e` | editor surface |
| `--chrome` | `#f3f4f7` | `#1c1f26` | top bar, left column, status bar |
| `--desk` | `#e3e6ec` | `#0e1014` | preview background |
| `--rule` | `#d9dce3` | `#2b2f39` | borders, splitters |
| `--ink` | `#1c2233` | `#e3e6ee` | text |
| `--pencil` | `#646c7e` | `#949cb0` | secondary text |
| `--accent` | `#2b4acb` | `#8ea2ff` | royal-blue ink: focus, active, main file |
| `--error` | `#c4302b` | `#ff7b72` | compile errors |
| `--warning` | `#a86a12` | `#e3b341` | warnings |

Type: UI `"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif` at 13 px;
source `"Cascadia Code", "JetBrains Mono", "SF Mono", Consolas, ui-monospace, monospace`
at 14 px / 1.6. Typst headings in the source are bold and in ink blue, so the source
reads like an outline.

## Layout

```
+---------------------------------------------------------------------------+
| New file  New folder  Open folder  Save  Export PDF | (insert toolbar, P2)  |
+-----------+--------------------------+------------------------------------+
| Files     | main.typ | 01-intro.typ  |  − 100 % +  Fit width               |
| tree      |--------------------------|   +---------+                      |
|           | = Einleitung             |   | page 1  |   desk                |
|-----------|                          |   +---------+                      |
| Problems  |                          |   +---------+                      |
| list      |                          |   | page 2  |                      |
+-----------+--------------------------+------------------------------------+
| Ln 12, Col 4   de-DE   Compiled in 12 ms          Local AI [None] Claude [None] |
+---------------------------------------------------------------------------+
```

Left-aligned text everywhere; pages centred on the desk.
