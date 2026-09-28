// Autocomplete for Typst code, labels and citations. The backend asks Tinymist; while it is
// not installed the answer is empty and nothing is shown.

import {
  snippet,
  type Completion,
  type CompletionContext,
  type CompletionResult,
  type CompletionSource,
} from "@codemirror/autocomplete";

import type { CompletionItem } from "../api/types";

export type CompleteFn = (content: string, offset: number, signal: AbortSignal) => Promise<CompletionItem[]>;

// After `#` (function, then `.field`), after `@` (label or citation key), or a lone `#`.
const TRIGGER = /(?:#[\w-]+(?:\.[\w-]*)*|#|@[\w\-:.]*)$/;
const VALID_FOR = /^[\w\-:.]*$/;

function escapeBraces(text: string): string {
  return text.replaceAll(/[{}]/g, (brace) => `\\${brace}`);
}

/** Convert an LSP snippet (`$1`, `${1:name}`, `${1|a,b|}`, `\$`) to CodeMirror's syntax,
 * where literal braces must be escaped and a placeholder cannot contain braces. */
export function lspSnippet(text: string): string {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const rest = text.slice(i);
    const c = text.charAt(i);
    if (c === "\\" && i + 1 < text.length && "$}\\".includes(text.charAt(i + 1))) {
      out += escapeBraces(text.charAt(i + 1));
      i += 2;
      continue;
    }
    if (c === "$") {
      const bare = /^\$(\d+)/.exec(rest);
      const field = /^\$\{(\d+)(?::((?:\\.|[^}\\])*))?\}/.exec(rest);
      const choice = /^\$\{(\d+)\|([^|]*)\|\}/.exec(rest);
      const variable = /^\$(?:\{[A-Za-z_]\w*(?::([^}]*))?\}|[A-Za-z_]\w*)/.exec(rest);
      if (bare) {
        out += `\${${bare[1]}}`;
        i += bare[0].length;
        continue;
      }
      if (field) {
        const placeholder = (field[2] ?? "").replaceAll(/\\(.)/g, "$1").replaceAll(/[{}]/g, "");
        out += placeholder ? `\${${field[1]}:${placeholder}}` : `\${${field[1]}}`;
        i += field[0].length;
        continue;
      }
      if (choice) {
        const first = (choice[2] ?? "").split(",")[0]?.replaceAll(/[{}]/g, "") ?? "";
        out += `\${${choice[1]}:${first}}`;
        i += choice[0].length;
        continue;
      }
      if (variable) {
        out += escapeBraces(variable[1] ?? "");
        i += variable[0].length;
        continue;
      }
    }
    out += escapeBraces(c);
    i += 1;
  }
  return out;
}

function toCompletion(item: CompletionItem, index: number): Completion {
  return {
    label: item.label,
    detail: item.detail,
    type: item.kind,
    apply: item.snippet ? snippet(lspSnippet(item.insert)) : item.insert,
    boost: Math.max(-99, -index), // keep Tinymist's order among equally good matches
  };
}

/** Completion source: asks `complete` after a trigger (or Ctrl+Space); a request is
 * aborted when the text changes before the answer arrives. */
export function typstCompletions(complete: CompleteFn): CompletionSource {
  return async (ctx: CompletionContext): Promise<CompletionResult | null> => {
    if (!ctx.explicit && ctx.matchBefore(TRIGGER) === null) return null;
    const controller = new AbortController();
    ctx.addEventListener("abort", () => controller.abort(), { onDocChange: true });
    let items: CompletionItem[];
    try {
      items = await complete(ctx.state.doc.toString(), ctx.pos, controller.signal);
    } catch {
      return null; // aborted, or the backend is not reachable
    }
    if (ctx.aborted || items.length === 0) return null;
    const from = Math.min(...items.map((item) => item.start));
    const options = items.filter((item) => item.start === from && item.end <= ctx.pos).map(toCompletion);
    return options.length === 0 ? null : { from, options, validFor: VALID_FOR };
  };
}
