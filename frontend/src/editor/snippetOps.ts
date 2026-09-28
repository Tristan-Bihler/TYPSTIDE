// How toolbar snippets change the document. Pure functions over CodeMirror state, so they
// are unit-tested; the Python mirror is `apply_simple` in backend/services/snippets.py.

import { EditorSelection, type EditorState, type TransactionSpec } from "@codemirror/state";

import type { Snippet } from "../api/types";

/** Heading or list marker at the start of a line: "== ", "- ", "+ ", "1. ". */
const LINE_MARKER = /^(\s*)(=+|[-+]|\d+\.)\s+/;

/** Wrap the selection (or the placeholder, which is then selected) in the template. */
export function wrap(state: EditorState, template: string, placeholder: string): TransactionSpec {
  const range = state.selection.main;
  const selected = state.sliceDoc(range.from, range.to);
  const inner = selected || placeholder;
  const [before = "", after = ""] = template.split("{selection}");
  const start = range.from + before.length;
  return {
    changes: { from: range.from, to: range.to, insert: before + inner + after },
    selection: EditorSelection.range(start, start + inner.length),
    scrollIntoView: true,
    userEvent: "input.snippet",
  };
}

/**
 * Put `prefix` at the start of every selected line, replacing any heading/list marker.
 * If every line already starts with this prefix, remove it instead (toggle).
 */
export function linePrefix(state: EditorState, prefix: string): TransactionSpec {
  const range = state.selection.main;
  const first = state.doc.lineAt(range.from).number;
  const last = state.doc.lineAt(range.to).number;
  const lines = [];
  for (let n = first; n <= last; n++) lines.push(state.doc.line(n));
  const marker = prefix.trim();
  const allHaveIt = lines.every((line) => LINE_MARKER.exec(line.text)?.[2] === marker);
  const changes = lines.map((line) => {
    const existing = LINE_MARKER.exec(line.text);
    const indent = existing?.[1] ?? /^\s*/.exec(line.text)?.[0] ?? "";
    const end = line.from + (existing ? existing[0].length : indent.length);
    return { from: line.from, to: end, insert: allHaveIt ? indent : indent + prefix };
  });
  return { changes, scrollIntoView: true, userEvent: "input.snippet" };
}

/**
 * Insert code as a block on its own line(s): on the cursor's line if it is empty,
 * otherwise on a new line after it. Like a word processor, the cursor continues on a
 * fresh empty line below the block.
 */
export function insertBlock(state: EditorState, code: string): TransactionSpec {
  const line = state.doc.lineAt(state.selection.main.head);
  const empty = line.text.trim() === "";
  const insert = empty ? `${code}\n` : `\n${code}\n`;
  const from = empty ? line.from : line.to;
  return {
    changes: { from, to: line.to, insert },
    selection: EditorSelection.cursor(from + insert.length),
    scrollIntoView: true,
    userEvent: "input.snippet",
  };
}

/** Replace the selection with inline code (a reference, an inline equation). */
export function insertInline(state: EditorState, code: string): TransactionSpec {
  const range = state.selection.main;
  return {
    changes: { from: range.from, to: range.to, insert: code },
    selection: EditorSelection.cursor(range.from + code.length),
    scrollIntoView: true,
    userEvent: "input.snippet",
  };
}

/** Transaction for a non-dialog snippet. */
export function applySnippet(state: EditorState, snippet: Snippet): TransactionSpec {
  switch (snippet.kind) {
    case "wrap":
      return wrap(state, snippet.template, snippet.placeholder);
    case "line_prefix":
      return linePrefix(state, snippet.template);
    case "block":
      return insertBlock(state, snippet.template);
    case "dialog":
      throw new Error(`${snippet.id} is inserted through its dialog`);
  }
}
