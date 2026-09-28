---
name: typst-syntax
description: Correct Typst syntax for this repo's pinned Typst 0.15.0 — verified patterns for headings, emphasis, lists, footnotes, figures with images, tables, equations, labels, references, citations, bibliography and outline, plus the escaping rules for user-typed text inside generated code. Use this whenever you write or change anything that produces Typst code: snippets.toml, the snippet service or its dialogs, code generators, Typst test fixtures or example documents — and whenever you are unsure whether a piece of Typst syntax is valid in 0.15.0, even if the task does not say "Typst" explicitly.
---

# Typst syntax (pinned: Typst 0.15.0)

Typst changes syntax between versions, and generated code is easy to get subtly wrong: it
compiles in one version, breaks in the next, or compiles but renders something else. This
project pins **Typst 0.15.0** (typst-py `0.15.0`, see `config.toml`), so everything here is
verified against exactly that version.

**The rule: if you are not sure, compile it.** A two-second check beats a plausible guess:

```sh
echo '#figure(table(columns: 2, [a], [b]), caption: [x]) <tab:x>' \
  | uv run --project backend python .claude/skills/typst-syntax/scripts/compile_check.py -
```

Snippets from stdin are compiled inside `examples/` (a small project with a chapter in a
subfolder, an image and a `.bib` file), so references such as `@tab:messwerte`,
`@fig:logo`, `@eq:summe` and `@knuth1984` resolve. For anything not covered below, consult
the official documentation for **0.15.0** (Context7 MCP if available, typst.app/docs
otherwise) and then compile it — documentation for newer versions may not apply.

`examples/main.typ` + `examples/kapitel/eins.typ` contain every pattern below and are
compiled by `backend/tests/test_typst_skill.py`, so this file cannot silently rot when the
pin changes. If you add a pattern here, add it to the example project too.

## Verified patterns

| Want | Typst 0.15.0 |
|---|---|
| Heading level 1–6 | `= Titel`, `== Titel`, … at line start (followed by a space) |
| Bold / italic | `*fett*`, `_kursiv_` |
| Bullet / numbered list | `- Punkt` / `+ Schritt` at line start |
| Footnote | `#footnote[Text]` directly after the word, no space before `#` |
| Table of contents | `#outline()` |
| Page break | `#pagebreak()` on its own line |
| Inline math | `$a^2 + b^2 = c^2$` (no spaces inside the dollars) |
| Block math | `$ sum_(i=1)^n i $` (spaces inside the dollars) |
| Numbered, referenceable equation | `#math.equation(block: true, numbering: "(1)", $ … $) <eq:name>` |
| Table as figure | `#figure(table(columns: 3, table.header[*A*][*B*][*C*], [ ], [ ], [ ]), caption: [Text]) <tab:name>` |
| Image as figure | `#figure(image("/bilder/x.png", width: 80%), caption: [Text]) <fig:name>` |
| Reference / citation | `@tab:name`, `@fig:name`, `@eq:name`, `@bibkey` — same syntax for both |
| Bibliography | `#bibliography("refs.bib")` once, usually at the end of the main file |
| Include a chapter | `#include "kapitel/01.typ"` (path relative to the including file) |

Image formats `image()` accepts: png, jpg/jpeg, gif, svg, webp, pdf.

## Escaping user text

Captions, table cells and other user-typed text go inside content blocks `[...]`. Escape
these characters with a backslash: `\ # $ * _ [ ] @ < > ` ~ /`. After escaping, the text
renders exactly as typed (verified by round trip through `typst.query`).

Why each one matters: `#` starts code, `$` math, `*`/`_` emphasis, `[`/`]` end or nest the
block, `@` a reference, `<`/`>` a label, `` ` `` raw text, `~` a non-breaking space, `\` an
escape — and `/` because **`//` starts a comment that swallows the closing `]`** (and `/*`
silently hides the rest). Also collapse newlines to spaces in single-line fields.

At the **start** of the text, `= `, `- `, `+ ` and `1. ` turn the whole caption into a
heading or list item. Escape that leading marker (`\= `, `\- `, `\+ `, `1\. `). Leave
mid-text `--`/`---` alone: they become en/em dashes, which is typography, not structure.

Inside string literals (`image("…")`) escape only `\` and `"`.

Labels: `<prefix:name>` with letters (umlauts are fine), digits, `_ - . :`. Use the
prefixes `tab:`, `fig:`, `eq:` so references read clearly and never collide.

## Common mistakes

- **Referencing an unnumbered equation.** `$ x $ <eq:a>` compiles, but `@eq:a` fails with
  "cannot reference equation without numbering". Generate the `#math.equation(...,
  numbering: "(1)", ...)` form whenever a label is set.
- **Relative image paths in chapters.** `image("bilder/x.png")` resolves relative to the
  file it is in, so the same snippet breaks when pasted into `kapitel/`. Use the
  root-relative `"/bilder/x.png"`.
- **Old table header syntax.** Use `table.header[...]` for the header row (repeats on page
  breaks, marks it semantically); do not fake it with bold cells only.
- **Unescaped `//` or `]` in a caption** — see escaping above.
- **Citation without bibliography.** `@key` for a `.bib` entry only works once
  `#bibliography("…")` is somewhere in the document; otherwise Typst reports the label as
  missing.
- **Math in markup vs code.** Inside `#math.equation(...)` the body is still `$ … $`; do
  not put a raw string there.
- **Space before a footnote.** `Wort #footnote[...]` puts the marker after a space; write
  `Wort#footnote[...]`.
