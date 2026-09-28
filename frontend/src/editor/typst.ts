// Lightweight Typst highlighting (markup mode with code calls and math).
// Good enough to read structure; Tinymist provides the real language support in Phase 6.

import { HighlightStyle, StreamLanguage, type StringStream } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";

interface TypstState {
  blockComment: boolean;
  raw: boolean;
  math: boolean;
  codeDepth: number; // open "(" after a #call
}

const KEYWORDS = /^#(let|set|show|import|include|if|else|for|in|while|return|context|break|continue)\b/;

function tokenCode(stream: StringStream, state: TypstState): string | null {
  if (stream.match(/^"(?:[^"\\]|\\.)*"?/)) return "string";
  if (stream.match(/^-?\d+(\.\d+)?(pt|mm|cm|in|em|fr|%|deg|rad)?\b/)) return "number";
  if (stream.match(/^(true|false|none|auto)\b/)) return "atom";
  if (stream.match(/^[A-Za-z_][\w-]*(?=\s*:)/)) return "property";
  const ch = stream.next();
  if (ch === "(") state.codeDepth++;
  if (ch === ")") state.codeDepth--;
  return null;
}

export const typstLanguage = StreamLanguage.define<TypstState>({
  name: "typst",
  startState: () => ({ blockComment: false, raw: false, math: false, codeDepth: 0 }),
  copyState: (s) => ({ ...s }),
  token(stream, state) {
    if (state.blockComment) {
      if (stream.skipTo("*/")) {
        stream.match("*/");
        state.blockComment = false;
      } else stream.skipToEnd();
      return "comment";
    }
    if (state.raw) {
      if (stream.skipTo("```")) {
        stream.match("```");
        state.raw = false;
      } else stream.skipToEnd();
      return "monospace";
    }
    if (stream.match("//")) {
      stream.skipToEnd();
      return "comment";
    }
    if (stream.match("/*")) {
      state.blockComment = true;
      return "comment";
    }
    if (state.math) {
      if (stream.match("$")) {
        state.math = false;
        return "math";
      }
      if (!stream.match(/^(\\.|[^$\\])+/)) stream.next();
      return "math";
    }
    if (state.codeDepth > 0) return tokenCode(stream, state);

    if (stream.sol()) {
      if (stream.match(/^\s*=+\s/)) {
        stream.skipToEnd();
        return "heading";
      }
      if (stream.match(/^\s*([-+]|\d+\.)\s/)) return "list";
    }
    if (stream.match("```")) {
      state.raw = true;
      return "monospace";
    }
    if (stream.match(/^`[^`]*`/)) return "monospace";
    if (stream.match("$")) {
      state.math = true;
      return "math";
    }
    if (stream.match(/^\\./)) return "escape";
    if (stream.match(KEYWORDS)) return "keyword";
    if (stream.match(/^#[A-Za-z_][\w-]*(\.[A-Za-z_][\w-]*)*/)) {
      if (stream.peek() === "(") {
        stream.next();
        state.codeDepth = 1;
      }
      return "function";
    }
    if (stream.match(/^@[\w:.-]*\w/)) return "ref";
    if (stream.match(/^<[\w:.-]+>/)) return "label";
    if (stream.match(/^\*[^*\n]+\*/)) return "strong";
    if (stream.match(/^_[^_\n]+_/)) return "emphasis";
    stream.next();
    return null;
  },
  tokenTable: {
    heading: t.heading,
    list: t.list,
    comment: t.comment,
    monospace: t.monospace,
    math: t.special(t.string),
    escape: t.escape,
    keyword: t.keyword,
    function: t.function(t.variableName),
    ref: t.link,
    label: t.labelName,
    strong: t.strong,
    emphasis: t.emphasis,
    string: t.string,
    number: t.number,
    atom: t.atom,
    property: t.propertyName,
  },
  languageData: { commentTokens: { line: "//", block: { open: "/*", close: "*/" } } },
});

// Colours come from CSS custom properties so light and dark themes both work.
export const typstHighlight = HighlightStyle.define([
  { tag: t.heading, color: "var(--accent)", fontWeight: "650" },
  { tag: t.list, color: "var(--accent)" },
  { tag: t.comment, color: "var(--pencil)", fontStyle: "italic" },
  { tag: [t.keyword, t.function(t.variableName)], color: "var(--syntax-code)" },
  { tag: t.special(t.string), color: "var(--syntax-math)" },
  { tag: [t.link, t.labelName], color: "var(--syntax-ref)" },
  { tag: t.strong, fontWeight: "700" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: [t.string, t.monospace], color: "var(--syntax-string)" },
  { tag: [t.number, t.atom], color: "var(--syntax-number)" },
  { tag: t.propertyName, color: "var(--pencil)" },
  { tag: t.escape, color: "var(--pencil)" },
]);
